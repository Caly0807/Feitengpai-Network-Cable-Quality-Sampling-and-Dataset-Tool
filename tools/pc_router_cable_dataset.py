#!/usr/bin/env python3
"""
PC-only cable dataset collector using a router as the link partner.

This is useful when you do not want to use the Phytium Pi. The PC records its
own Ethernet link state, ping to the router, and optional iperf3 to a server.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


CSV_FIELDS = [
    "session_id",
    "sample_id",
    "repeat_index",
    "timestamp_start",
    "timestamp_end",
    "pc_host",
    "os",
    "operator",
    "topology",
    "adapter",
    "router_ip",
    "iperf_server",
    "cable_id",
    "label",
    "fault_type",
    "category",
    "length_m",
    "notes",
    "link_status",
    "link_speed",
    "media_state",
    "mac_address",
    "ping_sent",
    "ping_received",
    "ping_loss_percent",
    "ping_min_ms",
    "ping_avg_ms",
    "ping_max_ms",
    "tcp_sender_mbps",
    "tcp_receiver_mbps",
    "tcp_retransmits",
    "udp_mbps",
    "udp_jitter_ms",
    "udp_lost_percent",
    "udp_lost_packets",
    "udp_packets",
    "raw_dir",
    "errors",
]


@dataclass
class CommandResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def slug(value: str, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(args: List[str], timeout: Optional[float] = None) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            completed.returncode == 0,
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )
    except FileNotFoundError:
        return CommandResult(False, 127, "", f"command not found: {args[0]}\n")
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            False,
            124,
            exc.stdout or "",
            f"timeout after {timeout}s\n{exc.stderr or ''}",
            True,
        )


def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", errors="replace")


def save_command(raw_dir: Path, filename: str, args: List[str], timeout: Optional[float] = None) -> CommandResult:
    result = run_command(args, timeout=timeout)
    text = "$ " + " ".join(args) + "\n\n"
    if result.stdout:
        text += result.stdout
    if result.stderr:
        text += ("\n" if text and not text.endswith("\n") else "") + "[stderr]\n" + result.stderr
    save_text(raw_dir / filename, text)
    return result


def append_csv(path: Path, row: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def append_jsonl(path: Path, row: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_powershell(command: str, timeout: Optional[float] = None) -> CommandResult:
    executable = "powershell"
    if not command_exists(executable) and command_exists("pwsh"):
        executable = "pwsh"
    return run_command([executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], timeout=timeout)


def parse_json_object(text: str) -> Dict[str, object]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, list):
        return data[0] if data and isinstance(data[0], dict) else {}
    return data if isinstance(data, dict) else {}


def collect_windows_adapter(raw_dir: Path, adapter: str) -> Dict[str, str]:
    record = {
        "link_status": "",
        "link_speed": "",
        "media_state": "",
        "mac_address": "",
    }
    if not adapter:
        save_command(raw_dir, "pc_netadapter_all.txt", ["powershell", "-NoProfile", "-Command", "Get-NetAdapter | Format-Table -Auto"], timeout=10)
        return record

    adapter_q = ps_quote(adapter)
    adapter_cmd = (
        f"Get-NetAdapter -Name {adapter_q} | "
        "Select-Object Name,InterfaceDescription,Status,LinkSpeed,MacAddress,MediaConnectionState | "
        "ConvertTo-Json -Compress"
    )
    adapter_result = run_powershell(adapter_cmd, timeout=10)
    save_text(raw_dir / "pc_netadapter.json", adapter_result.stdout or adapter_result.stderr)
    data = parse_json_object(adapter_result.stdout)
    record["link_status"] = str(data.get("Status", "") or "")
    record["link_speed"] = str(data.get("LinkSpeed", "") or "")
    record["media_state"] = str(data.get("MediaConnectionState", "") or "")
    record["mac_address"] = str(data.get("MacAddress", "") or "")

    stats_cmd = f"Get-NetAdapterStatistics -Name {adapter_q} | ConvertTo-Json -Compress"
    stats_result = run_powershell(stats_cmd, timeout=10)
    save_text(raw_dir / "pc_netadapter_statistics.json", stats_result.stdout or stats_result.stderr)
    return record


def collect_linux_adapter(raw_dir: Path, iface: str) -> Dict[str, str]:
    record = {
        "link_status": "",
        "link_speed": "",
        "media_state": "",
        "mac_address": "",
    }
    if not iface:
        if command_exists("ip"):
            save_command(raw_dir, "pc_ip_addr.txt", ["ip", "-br", "addr"], timeout=10)
        return record

    if command_exists("ip"):
        ip_result = save_command(raw_dir, "pc_ip_addr.json", ["ip", "-j", "addr", "show", "dev", iface], timeout=10)
        data = parse_json_object(ip_result.stdout)
        record["link_status"] = str(data.get("operstate", "") or "")
        record["mac_address"] = str(data.get("address", "") or "")
    if command_exists("ethtool"):
        ethtool = save_command(raw_dir, "pc_ethtool.txt", ["ethtool", iface], timeout=10)
        speed_match = re.search(r"^\s*Speed:\s*(.+)$", ethtool.stdout, flags=re.MULTILINE)
        link_match = re.search(r"^\s*Link detected:\s*(.+)$", ethtool.stdout, flags=re.MULTILINE)
        if speed_match:
            record["link_speed"] = speed_match.group(1).strip()
        if link_match:
            record["media_state"] = link_match.group(1).strip()
    return record


def collect_adapter(raw_dir: Path, adapter: str) -> Dict[str, str]:
    if platform.system().lower() == "windows":
        return collect_windows_adapter(raw_dir, adapter)
    return collect_linux_adapter(raw_dir, adapter)


def parse_ping(text: str) -> Dict[str, str]:
    result = {
        "ping_sent": "",
        "ping_received": "",
        "ping_loss_percent": "",
        "ping_min_ms": "",
        "ping_avg_ms": "",
        "ping_max_ms": "",
    }

    linux_packet = re.search(
        r"(\d+)\s+packets transmitted,\s+(\d+)\s+(?:packets )?received,.*?([0-9.]+)%\s+packet loss",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if linux_packet:
        result["ping_sent"] = linux_packet.group(1)
        result["ping_received"] = linux_packet.group(2)
        result["ping_loss_percent"] = linux_packet.group(3)

    windows_packet = re.search(
        r"Packets:\s*Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+),\s*Lost\s*=\s*(\d+)\s*\(([0-9.]+)%\s*loss\)",
        text,
        flags=re.IGNORECASE,
    )
    if windows_packet:
        result["ping_sent"] = windows_packet.group(1)
        result["ping_received"] = windows_packet.group(2)
        result["ping_loss_percent"] = windows_packet.group(4)

    linux_rtt = re.search(
        r"(?:rtt|round-trip).*?=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)",
        text,
        flags=re.IGNORECASE,
    )
    if linux_rtt:
        result["ping_min_ms"] = linux_rtt.group(1)
        result["ping_avg_ms"] = linux_rtt.group(2)
        result["ping_max_ms"] = linux_rtt.group(3)

    windows_rtt = re.search(
        r"Minimum\s*=\s*([0-9]+)ms,\s*Maximum\s*=\s*([0-9]+)ms,\s*Average\s*=\s*([0-9]+)ms",
        text,
        flags=re.IGNORECASE,
    )
    if windows_rtt:
        result["ping_min_ms"] = windows_rtt.group(1)
        result["ping_max_ms"] = windows_rtt.group(2)
        result["ping_avg_ms"] = windows_rtt.group(3)
    return result


def ping_args(router_ip: str, count: int, timeout_s: int) -> List[str]:
    if platform.system().lower() == "windows":
        return ["ping", "-n", str(count), "-w", str(timeout_s * 1000), router_ip]
    return ["ping", "-c", str(count), "-W", str(timeout_s), router_ip]


def bps_to_mbps(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value) / 1_000_000:.3f}"
    except (TypeError, ValueError):
        return ""


def load_json_text(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def parse_iperf_tcp(data: Optional[dict]) -> Dict[str, str]:
    result = {
        "tcp_sender_mbps": "",
        "tcp_receiver_mbps": "",
        "tcp_retransmits": "",
    }
    if not data:
        return result
    end = data.get("end", {})
    sent = end.get("sum_sent") or {}
    received = end.get("sum_received") or {}
    result["tcp_sender_mbps"] = bps_to_mbps(sent.get("bits_per_second"))
    result["tcp_receiver_mbps"] = bps_to_mbps(received.get("bits_per_second"))
    if sent.get("retransmits") is not None:
        result["tcp_retransmits"] = str(sent.get("retransmits"))
    return result


def parse_iperf_udp(data: Optional[dict]) -> Dict[str, str]:
    result = {
        "udp_mbps": "",
        "udp_jitter_ms": "",
        "udp_lost_percent": "",
        "udp_lost_packets": "",
        "udp_packets": "",
    }
    if not data:
        return result
    stream = data.get("end", {}).get("sum") or data.get("end", {}).get("sum_received") or {}
    result["udp_mbps"] = bps_to_mbps(stream.get("bits_per_second"))
    mapping = {
        "jitter_ms": "udp_jitter_ms",
        "lost_percent": "udp_lost_percent",
        "lost_packets": "udp_lost_packets",
        "packets": "udp_packets",
    }
    for src, dst in mapping.items():
        value = stream.get(src)
        if value is not None:
            result[dst] = str(round(float(value), 3) if isinstance(value, float) else value)
    return result


def prompt(default: str, message: str) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{message}{suffix}: ").strip()
    return value if value else default


def prompt_metadata(args: argparse.Namespace) -> Optional[Dict[str, str]]:
    cable_id = prompt("", "Cable ID, blank to finish")
    if not cable_id:
        return None
    label = prompt(args.label or "unknown", "Label (good/open/short/cross/split_pair/poor/unknown)")
    fault_type = prompt(args.fault_type or label, "Fault type")
    category = prompt(args.category or "", "Category, for example Cat5e/Cat6")
    length_m = prompt(args.length_m or "", "Length in meters")
    notes = prompt(args.notes or "", "Notes")
    input("Connect this cable between PC and router, then press Enter to start sampling...")
    return {
        "cable_id": cable_id,
        "label": label,
        "fault_type": fault_type,
        "category": category,
        "length_m": length_m,
        "notes": notes,
    }


def metadata_from_args(args: argparse.Namespace) -> Dict[str, str]:
    return {
        "cable_id": args.cable_id,
        "label": args.label or "unknown",
        "fault_type": args.fault_type or args.label or "unknown",
        "category": args.category or "",
        "length_m": args.length_m or "",
        "notes": args.notes or "",
    }


def collect_one_sample(
    args: argparse.Namespace,
    session_id: str,
    metadata: Dict[str, str],
    repeat_index: int,
    csv_path: Path,
    jsonl_path: Path,
) -> Dict[str, str]:
    sample_stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    sample_id = f"{sample_stamp}_{slug(metadata['cable_id'])}_r{repeat_index:03d}"
    raw_dir = Path(args.out) / "raw" / session_id / sample_id
    raw_dir.mkdir(parents=True, exist_ok=True)

    errors: List[str] = []
    record: Dict[str, str] = {
        "session_id": session_id,
        "sample_id": sample_id,
        "repeat_index": str(repeat_index),
        "timestamp_start": now_iso(),
        "pc_host": socket.gethostname(),
        "os": platform.system(),
        "operator": args.operator or "",
        "topology": args.topology,
        "adapter": args.adapter,
        "router_ip": args.router_ip,
        "iperf_server": args.iperf_server or "",
        "raw_dir": str(raw_dir),
    }
    record.update(metadata)

    if args.stabilize > 0:
        time.sleep(args.stabilize)

    record.update(collect_adapter(raw_dir, args.adapter))

    if not args.skip_ping:
        ping = save_command(
            raw_dir,
            "ping_router.txt",
            ping_args(args.router_ip, args.ping_count, args.ping_timeout),
            timeout=max(args.ping_count * (args.ping_timeout + 1), 8),
        )
        record.update(parse_ping(ping.stdout + "\n" + ping.stderr))
        if not ping.ok:
            errors.append("ping failed")

    if args.iperf_server and not args.skip_iperf:
        tcp = run_command(
            ["iperf3", "-c", args.iperf_server, "-t", str(args.tcp_seconds), "-P", str(args.tcp_parallel), "-J"],
            timeout=args.tcp_seconds + 20,
        )
        save_text(raw_dir / "iperf_tcp.json", tcp.stdout if tcp.stdout else tcp.stderr)
        record.update(parse_iperf_tcp(load_json_text(tcp.stdout)))
        if not tcp.ok:
            errors.append("iperf tcp failed")

    if args.iperf_server and not args.skip_udp:
        udp = run_command(
            ["iperf3", "-c", args.iperf_server, "-u", "-b", args.udp_bandwidth, "-t", str(args.udp_seconds), "-J"],
            timeout=args.udp_seconds + 20,
        )
        save_text(raw_dir / "iperf_udp.json", udp.stdout if udp.stdout else udp.stderr)
        record.update(parse_iperf_udp(load_json_text(udp.stdout)))
        if not udp.ok:
            errors.append("iperf udp failed")

    record["timestamp_end"] = now_iso()
    record["errors"] = "; ".join(errors)
    append_csv(csv_path, record)
    append_jsonl(jsonl_path, record)
    return record


def run_for_cable(
    args: argparse.Namespace,
    session_id: str,
    metadata: Dict[str, str],
    csv_path: Path,
    jsonl_path: Path,
) -> None:
    print(f"\nSampling cable={metadata['cable_id']} label={metadata['label']}")
    for repeat in range(1, args.samples_per_cable + 1):
        print(f"  sample {repeat}/{args.samples_per_cable} ...", flush=True)
        record = collect_one_sample(args, session_id, metadata, repeat, csv_path, jsonl_path)
        print(
            "    link={link} speed={speed} ping_loss={loss} tcp={tcp} errors={errors}".format(
                link=record.get("link_status", "") or record.get("media_state", ""),
                speed=record.get("link_speed", ""),
                loss=record.get("ping_loss_percent", ""),
                tcp=record.get("tcp_receiver_mbps", ""),
                errors=record.get("errors", ""),
            )
        )
        if repeat < args.samples_per_cable and args.interval > 0:
            time.sleep(args.interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect cable samples on a PC using a router as the link partner.")
    parser.add_argument("--router-ip", required=True, help="router IP to ping, for example 192.168.10.1")
    parser.add_argument("--adapter", default="", help="PC Ethernet adapter name, for example Ethernet")
    parser.add_argument("--iperf-server", default="", help="optional iperf3 server IP, router OpenWrt or another PC")
    parser.add_argument("--out", default="data/raw/dataset_router", help="output dataset directory")
    parser.add_argument("--operator", default="", help="operator name or team member")
    parser.add_argument("--topology", default="pc_router", help="pc_router, pc_router_second_pc, or custom text")

    parser.add_argument("--cable-id", default="", help="non-interactive cable ID. If omitted, interactive mode starts.")
    parser.add_argument("--label", default="", help="label, for example good/open/short/cross/split_pair/poor")
    parser.add_argument("--fault-type", default="", help="more specific fault label, for example open_pin_1")
    parser.add_argument("--category", default="", help="cable category, for example Cat5e or Cat6")
    parser.add_argument("--length-m", default="", help="cable length in meters")
    parser.add_argument("--notes", default="", help="free-form notes")

    parser.add_argument("--samples-per-cable", type=int, default=5, help="repeat samples for each cable")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between repeats")
    parser.add_argument("--stabilize", type=float, default=2.0, help="seconds to wait before each sample")

    parser.add_argument("--ping-count", type=int, default=10, help="ping packets per sample")
    parser.add_argument("--ping-timeout", type=int, default=2, help="ping timeout seconds per packet")
    parser.add_argument("--tcp-seconds", type=int, default=5, help="iperf3 TCP duration per sample")
    parser.add_argument("--tcp-parallel", type=int, default=4, help="iperf3 TCP parallel streams")
    parser.add_argument("--udp-seconds", type=int, default=5, help="iperf3 UDP duration per sample")
    parser.add_argument("--udp-bandwidth", default="100M", help="iperf3 UDP target bandwidth")

    parser.add_argument("--skip-ping", action="store_true", help="skip ping")
    parser.add_argument("--skip-iperf", action="store_true", help="skip TCP iperf3")
    parser.add_argument("--skip-udp", action="store_true", help="skip UDP iperf3")
    return parser


def validate(args: argparse.Namespace) -> int:
    if args.samples_per_cable < 1:
        print("--samples-per-cable must be >= 1", file=sys.stderr)
        return 2
    if args.iperf_server and not command_exists("iperf3"):
        print("Warning: iperf3 not found. Throughput tests will fail unless iperf3 is in PATH.", file=sys.stderr)
    if platform.system().lower() == "windows" and args.adapter and not (command_exists("powershell") or command_exists("pwsh")):
        print("Warning: PowerShell not found. Adapter link details may be missing.", file=sys.stderr)
    return 0


def main() -> int:
    args = build_parser().parse_args()
    validation = validate(args)
    if validation:
        return validation

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "samples.csv"
    jsonl_path = out_dir / "samples.jsonl"
    session_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + slug(socket.gethostname())

    print(f"Session: {session_id}")
    print(f"Summary CSV: {csv_path}")
    print(f"Raw data: {out_dir / 'raw' / session_id}")
    if not args.iperf_server:
        print("No --iperf-server set: collecting link and ping data only.")

    if args.cable_id:
        run_for_cable(args, session_id, metadata_from_args(args), csv_path, jsonl_path)
        return 0

    print("\nInteractive router-link mode.")
    print("Recommended labels: good, open, short, cross, split_pair, poor, long, unknown.")
    while True:
        metadata = prompt_metadata(args)
        if metadata is None:
            break
        run_for_cable(args, session_id, metadata, csv_path, jsonl_path)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
