#!/usr/bin/env python3
"""
Batch data collector for Ethernet cable tester datasets.

Target platform: Phytium Pi or any Linux board with an Ethernet interface.
The script keeps one append-only CSV/JSONL summary and a raw folder per sample.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


CSV_FIELDS = [
    "session_id",
    "sample_id",
    "repeat_index",
    "timestamp_start",
    "timestamp_end",
    "host",
    "operator",
    "topology",
    "iface",
    "server",
    "cable_id",
    "label",
    "fault_type",
    "category",
    "length_m",
    "notes",
    "carrier",
    "link_detected",
    "speed_mbps",
    "duplex",
    "autoneg",
    "ipv4",
    "rx_bytes_delta",
    "tx_bytes_delta",
    "rx_packets_delta",
    "tx_packets_delta",
    "rx_errors_delta",
    "tx_errors_delta",
    "rx_dropped_delta",
    "tx_dropped_delta",
    "collisions_delta",
    "rx_crc_errors_delta",
    "rx_frame_errors_delta",
    "tx_carrier_errors_delta",
    "ping_sent",
    "ping_received",
    "ping_loss_percent",
    "ping_min_ms",
    "ping_avg_ms",
    "ping_max_ms",
    "ping_mdev_ms",
    "tcp_sender_mbps",
    "tcp_receiver_mbps",
    "tcp_retransmits",
    "udp_mbps",
    "udp_jitter_ms",
    "udp_lost_percent",
    "udp_lost_packets",
    "udp_packets",
    "cable_test_status",
    "raw_dir",
    "errors",
]


SYSFS_STATS = [
    "rx_bytes",
    "tx_bytes",
    "rx_packets",
    "tx_packets",
    "rx_errors",
    "tx_errors",
    "rx_dropped",
    "tx_dropped",
    "collisions",
    "rx_crc_errors",
    "rx_frame_errors",
    "tx_carrier_errors",
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
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    try:
        completed = subprocess.run(
            args,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
        return CommandResult(
            ok=completed.returncode == 0,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
    except FileNotFoundError:
        return CommandResult(False, 127, "", f"command not found: {args[0]}\n")
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            False,
            124,
            exc.stdout or "",
            f"timeout after {timeout}s\n{exc.stderr or ''}",
            timed_out=True,
        )


def save_command(raw_dir: Path, filename: str, args: List[str], timeout: Optional[float] = None) -> CommandResult:
    result = run_command(args, timeout=timeout)
    text = "$ " + " ".join(args) + "\n\n"
    if result.stdout:
        text += result.stdout
    if result.stderr:
        text += ("\n" if text and not text.endswith("\n") else "") + "[stderr]\n" + result.stderr
    (raw_dir / filename).write_text(text, encoding="utf-8", errors="replace")
    return result


def write_raw(raw_dir: Path, filename: str, text: str) -> None:
    (raw_dir / filename).write_text(text, encoding="utf-8", errors="replace")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def read_carrier(iface: str) -> str:
    value = read_text(Path("/sys/class/net") / iface / "carrier")
    if value == "1":
        return "1"
    if value == "0":
        return "0"
    return ""


def read_sysfs_stats(iface: str) -> Dict[str, int]:
    base = Path("/sys/class/net") / iface / "statistics"
    stats: Dict[str, int] = {}
    for name in SYSFS_STATS:
        value = read_text(base / name)
        try:
            stats[name] = int(value)
        except ValueError:
            pass
    return stats


def delta_stats(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for name in SYSFS_STATS:
        key = f"{name}_delta"
        if name in before and name in after:
            out[key] = str(after[name] - before[name])
        else:
            out[key] = ""
    return out


def parse_ethtool(text: str) -> Dict[str, str]:
    result = {
        "speed_mbps": "",
        "duplex": "",
        "autoneg": "",
        "link_detected": "",
    }
    speed_match = re.search(r"^\s*Speed:\s*([0-9]+)\s*Mb/s", text, flags=re.MULTILINE | re.IGNORECASE)
    if speed_match:
        result["speed_mbps"] = speed_match.group(1)

    duplex_match = re.search(r"^\s*Duplex:\s*([A-Za-z]+)", text, flags=re.MULTILINE)
    if duplex_match:
        result["duplex"] = duplex_match.group(1)

    autoneg_match = re.search(r"^\s*Auto-negotiation:\s*([A-Za-z]+)", text, flags=re.MULTILINE)
    if autoneg_match:
        result["autoneg"] = autoneg_match.group(1)

    link_match = re.search(r"^\s*Link detected:\s*([A-Za-z]+)", text, flags=re.MULTILINE)
    if link_match:
        result["link_detected"] = link_match.group(1).lower()

    return result


def parse_ip_json(text: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ""
    addresses: List[str] = []
    if isinstance(data, list):
        for item in data:
            for info in item.get("addr_info", []):
                if info.get("family") == "inet" and info.get("local"):
                    addresses.append(str(info["local"]))
    return ",".join(addresses)


def parse_ping(text: str) -> Dict[str, str]:
    result = {
        "ping_sent": "",
        "ping_received": "",
        "ping_loss_percent": "",
        "ping_min_ms": "",
        "ping_avg_ms": "",
        "ping_max_ms": "",
        "ping_mdev_ms": "",
    }

    packet_match = re.search(
        r"(\d+)\s+packets transmitted,\s+(\d+)\s+(?:packets )?received,.*?([0-9.]+)%\s+packet loss",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if packet_match:
        result["ping_sent"] = packet_match.group(1)
        result["ping_received"] = packet_match.group(2)
        result["ping_loss_percent"] = packet_match.group(3)

    rtt_match = re.search(
        r"(?:rtt|round-trip).*?=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)(?:/([0-9.]+))?\s*ms",
        text,
        flags=re.IGNORECASE,
    )
    if rtt_match:
        result["ping_min_ms"] = rtt_match.group(1)
        result["ping_avg_ms"] = rtt_match.group(2)
        result["ping_max_ms"] = rtt_match.group(3)
        result["ping_mdev_ms"] = rtt_match.group(4) or ""

    return result


def load_json_text(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def bps_to_mbps(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value) / 1_000_000:.3f}"
    except (TypeError, ValueError):
        return ""


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
    end = data.get("end", {})
    stream = end.get("sum") or end.get("sum_received") or {}
    result["udp_mbps"] = bps_to_mbps(stream.get("bits_per_second"))
    for key in ("jitter_ms", "lost_percent", "lost_packets", "packets"):
        value = stream.get(key)
        if value is not None:
            result[f"udp_{key}"] = str(round(float(value), 3) if isinstance(value, float) else value)
    return result


def parse_cable_test(text: str, ok: bool) -> str:
    lowered = text.lower()
    if "operation not supported" in lowered or "not supported" in lowered:
        return "unsupported"
    if "permission denied" in lowered or "operation not permitted" in lowered:
        return "permission_denied"
    if "open" in lowered:
        return "open"
    if "short" in lowered:
        return "short"
    if "ok" in lowered or "normal" in lowered:
        return "ok"
    if ok:
        return "done"
    return "failed"


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


def can_run_network_tests(args: argparse.Namespace, record: Dict[str, str]) -> Tuple[bool, str]:
    if not args.server:
        return False, "server not set"
    if record.get("carrier") == "0" or record.get("link_detected") == "no":
        return False, "link is down"
    return True, ""


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
        "host": socket.gethostname(),
        "operator": args.operator or "",
        "topology": args.topology,
        "iface": args.iface,
        "server": args.server or "",
        "raw_dir": str(raw_dir),
    }
    record.update(metadata)

    if args.stabilize > 0:
        time.sleep(args.stabilize)

    before_stats = read_sysfs_stats(args.iface)

    ip_json = save_command(raw_dir, "ip_addr.json", ["ip", "-j", "addr", "show", "dev", args.iface], timeout=5)
    if ip_json.ok:
        record["ipv4"] = parse_ip_json(ip_json.stdout)
    else:
        errors.append("ip failed")

    if not args.skip_ethtool:
        ethtool = save_command(raw_dir, "ethtool.txt", ["ethtool", args.iface], timeout=5)
        record.update(parse_ethtool(ethtool.stdout + "\n" + ethtool.stderr))
        if not ethtool.ok:
            errors.append("ethtool failed")

    record["carrier"] = read_carrier(args.iface)
    if not record.get("link_detected") and record["carrier"]:
        record["link_detected"] = "yes" if record["carrier"] == "1" else "no"

    should_test, skip_reason = can_run_network_tests(args, record)
    if not should_test:
        errors.append(f"network tests skipped: {skip_reason}")

    if should_test and not args.skip_ping:
        ping = save_command(
            raw_dir,
            "ping.txt",
            ["ping", "-c", str(args.ping_count), "-W", str(args.ping_timeout), args.server],
            timeout=max(args.ping_count * (args.ping_timeout + 1), 8),
        )
        record.update(parse_ping(ping.stdout + "\n" + ping.stderr))
        if not ping.ok:
            errors.append("ping failed")

    if should_test and not args.skip_iperf:
        tcp = run_command(
            ["iperf3", "-c", args.server, "-t", str(args.tcp_seconds), "-P", str(args.tcp_parallel), "-J"],
            timeout=args.tcp_seconds + 20,
        )
        write_raw(raw_dir, "iperf_tcp.json", tcp.stdout if tcp.stdout else tcp.stderr)
        record.update(parse_iperf_tcp(load_json_text(tcp.stdout)))
        if not tcp.ok:
            errors.append("iperf tcp failed")

    if should_test and not args.skip_udp:
        udp = run_command(
            ["iperf3", "-c", args.server, "-u", "-b", args.udp_bandwidth, "-t", str(args.udp_seconds), "-J"],
            timeout=args.udp_seconds + 20,
        )
        write_raw(raw_dir, "iperf_udp.json", udp.stdout if udp.stdout else udp.stderr)
        record.update(parse_iperf_udp(load_json_text(udp.stdout)))
        if not udp.ok:
            errors.append("iperf udp failed")

    after_stats = read_sysfs_stats(args.iface)
    record.update(delta_stats(before_stats, after_stats))

    if not args.skip_ethtool:
        stats = save_command(raw_dir, "ethtool_stats.txt", ["ethtool", "-S", args.iface], timeout=5)
        if not stats.ok:
            errors.append("ethtool stats failed")

    if args.run_cable_test:
        cable = save_command(raw_dir, "ethtool_cable_test.txt", ["ethtool", "--cable-test", args.iface], timeout=15)
        record["cable_test_status"] = parse_cable_test(cable.stdout + "\n" + cable.stderr, cable.ok)
        if not cable.ok:
            errors.append("cable test failed")

    record["timestamp_end"] = now_iso()
    record["errors"] = "; ".join(errors)

    append_csv(csv_path, record)
    append_jsonl(jsonl_path, record)
    return record


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
    input("Connect this cable, then press Enter to start sampling...")
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


def validate_tools(args: argparse.Namespace) -> None:
    required = ["ip"]
    optional = []
    if not args.skip_ethtool:
        optional.append("ethtool")
    if args.run_cable_test:
        optional.append("ethtool")
    if args.server and not args.skip_ping:
        optional.append("ping")
    if args.server and not args.skip_iperf:
        optional.append("iperf3")
    if args.server and not args.skip_udp:
        optional.append("iperf3")

    missing_required = [name for name in required if not command_exists(name)]
    missing_optional = sorted({name for name in optional if not command_exists(name)})
    if missing_required:
        print(f"Missing required command(s): {', '.join(missing_required)}", file=sys.stderr)
        sys.exit(2)
    if missing_optional:
        print(f"Warning: missing optional command(s): {', '.join(missing_optional)}", file=sys.stderr)


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
            "    link={link} speed={speed} tcp={tcp} udp_loss={loss} errors={errors}".format(
                link=record.get("link_detected", ""),
                speed=record.get("speed_mbps", ""),
                tcp=record.get("tcp_receiver_mbps", ""),
                loss=record.get("udp_lost_percent", ""),
                errors=record.get("errors", ""),
            )
        )
        if repeat < args.samples_per_cable and args.interval > 0:
            time.sleep(args.interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect labeled Ethernet cable samples into CSV/JSONL plus raw command outputs."
    )
    parser.add_argument("--server", default="", help="iperf3 server IP. If omitted, only link/status data is collected.")
    parser.add_argument("--iface", default="eth0", help="network interface to test, for example eth0")
    parser.add_argument("--out", default="data/raw/dataset_pi", help="output dataset directory")
    parser.add_argument("--operator", default="", help="operator name or team member")
    parser.add_argument("--topology", default="direct", help="direct, switch, router, loopback, or custom text")

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
    parser.add_argument("--skip-ethtool", action="store_true", help="skip ethtool commands")
    parser.add_argument(
        "--run-cable-test",
        action="store_true",
        help="run ethtool --cable-test after network metrics. It may need sudo and driver support.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.samples_per_cable < 1:
        print("--samples-per-cable must be >= 1", file=sys.stderr)
        return 2

    validate_tools(args)

    session_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + slug(socket.gethostname())
    out_dir = Path(args.out)
    csv_path = out_dir / "samples.csv"
    jsonl_path = out_dir / "samples.jsonl"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Session: {session_id}")
    print(f"Summary CSV: {csv_path}")
    print(f"Raw data: {out_dir / 'raw' / session_id}")

    if args.cable_id:
        run_for_cable(args, session_id, metadata_from_args(args), csv_path, jsonl_path)
        return 0

    print("\nInteractive mode. Give every physical cable a stable ID before sampling.")
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
