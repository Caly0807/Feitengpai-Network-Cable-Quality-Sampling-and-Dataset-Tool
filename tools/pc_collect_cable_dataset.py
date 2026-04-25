#!/usr/bin/env python3
"""
PC-side dataset collector for a Phytium Pi Ethernet cable tester.

The PC controls sampling over SSH, while the Phytium Pi measures its test
interface with ip/ethtool/ping/iperf3. Results are saved on the PC.
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
import signal
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
    "pc_host",
    "ssh_target",
    "pc_ip",
    "gateway_ip",
    "ping_target",
    "iperf_server",
    "operator",
    "topology",
    "iface",
    "cable_id",
    "label",
    "fault_type",
    "category",
    "length_m",
    "notes",
    "ssh_ok",
    "carrier",
    "link_detected",
    "speed_mbps",
    "duplex",
    "autoneg",
    "pi_ipv4",
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


PLAN_FIELDS = [
    "cable_id",
    "label",
    "fault_type",
    "category",
    "length_m",
    "notes",
    "samples_per_cable",
    "enabled",
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


@dataclass
class Section:
    text: str
    rc: str = ""


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def slug(value: str, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run_local(args: List[str], timeout: Optional[float] = None) -> CommandResult:
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


def save_local_command(raw_dir: Path, filename: str, args: List[str], timeout: Optional[float] = None) -> CommandResult:
    result = run_local(args, timeout=timeout)
    text = "$ " + " ".join(args) + "\n\n"
    if result.stdout:
        text += result.stdout
    if result.stderr:
        text += ("\n" if text and not text.endswith("\n") else "") + "[stderr]\n" + result.stderr
    save_text(raw_dir / filename, text)
    return result


def ensure_csv_schema(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return

    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames == CSV_FIELDS:
            return
        rows = list(reader)

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.stem}_schema_backup_{stamp}{path.suffix}")
    path.replace(backup)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for old_row in rows:
            writer.writerow({field: old_row.get(field, "") for field in CSV_FIELDS})

    print(f"Updated CSV schema: {path} (backup: {backup})", file=sys.stderr)


def append_csv(path: Path, row: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_csv_schema(path)
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


def parse_key_values(text: str) -> Dict[str, int]:
    values: Dict[str, int] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            values[key.strip()] = int(value.strip())
        except ValueError:
            pass
    return values


def delta_stats(before_text: str, after_text: str) -> Dict[str, str]:
    before = parse_key_values(before_text)
    after = parse_key_values(after_text)
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


def parse_sections(text: str) -> Dict[str, Section]:
    sections: Dict[str, Section] = {}
    current: Optional[str] = None
    buf: List[str] = []
    rc_map: Dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("__CABLE_BEGIN__:"):
            current = line.split(":", 1)[1].strip()
            buf = []
            continue
        if line.startswith("__CABLE_RC__:"):
            payload = line.split(":", 1)[1]
            name, _, rc = payload.partition(":")
            rc_map[name.strip()] = rc.strip()
            continue
        if line.startswith("__CABLE_END__:"):
            name = line.split(":", 1)[1].strip()
            if current == name:
                sections[name] = Section("\n".join(buf).strip(), rc_map.get(name, ""))
                current = None
                buf = []
            continue
        if current is not None:
            buf.append(line)
    return sections


def make_stats_function() -> str:
    stats_names = " ".join(SYSFS_STATS)
    return f"""
stats() {{
  for f in {stats_names}; do
    v=$(cat "/sys/class/net/$IFACE/statistics/$f" 2>/dev/null || true)
    printf '%s=%s\\n' "$f" "$v"
  done
}}
"""


def section_eval(name: str, command: str) -> str:
    return f"""
echo "__CABLE_BEGIN__:{name}"
eval {sh_quote(command)} 2>&1
rc=$?
echo "__CABLE_RC__:{name}:$rc"
echo "__CABLE_END__:{name}"
"""


def test_targets(args: argparse.Namespace) -> Tuple[str, str]:
    ping_target = args.ping_target or args.gateway_ip or args.pc_ip
    iperf_target = args.iperf_server or args.pc_ip
    return ping_target, iperf_target


def build_remote_script(args: argparse.Namespace) -> str:
    iface_q = sh_quote(args.iface)
    pc_ip_q = sh_quote(args.pc_ip)
    ping_target, iperf_target = test_targets(args)
    ping_target_q = sh_quote(ping_target)
    iperf_target_q = sh_quote(iperf_target)
    lines = [
        "set +e",
        "export LC_ALL=C LANG=C",
        f"IFACE={iface_q}",
        f"PC_IP={pc_ip_q}",
        f"PING_TARGET={ping_target_q}",
        f"IPERF_TARGET={iperf_target_q}",
        make_stats_function(),
        section_eval("ip_addr", 'ip -j addr show dev "$IFACE"'),
        section_eval("carrier", 'cat "/sys/class/net/$IFACE/carrier"'),
    ]

    if not args.skip_ethtool:
        lines.append(section_eval("ethtool", 'ethtool "$IFACE"'))

    lines.append(section_eval("stats_before", "stats"))

    if ping_target and not args.skip_ping:
        lines.append(section_eval("ping", f'timeout {max(8, args.ping_count * (args.ping_timeout + 1))} ping -c {args.ping_count} -W {args.ping_timeout} "$PING_TARGET"'))

    if iperf_target and not args.skip_iperf:
        tcp_limit = args.tcp_seconds + 20
        lines.append(section_eval("iperf_tcp", f'timeout {tcp_limit} iperf3 -c "$IPERF_TARGET" -t {args.tcp_seconds} -P {args.tcp_parallel} -J'))

    if iperf_target and not args.skip_udp:
        udp_limit = args.udp_seconds + 20
        udp_bw = sh_quote(args.udp_bandwidth)
        lines.append(section_eval("iperf_udp", f'timeout {udp_limit} iperf3 -c "$IPERF_TARGET" -u -b {udp_bw} -t {args.udp_seconds} -J'))

    lines.append(section_eval("stats_after", "stats"))

    if not args.skip_ethtool:
        lines.append(section_eval("ethtool_stats", 'ethtool -S "$IFACE"'))

    if args.run_cable_test:
        lines.append(section_eval("cable_test", 'ethtool --cable-test "$IFACE"'))

    return "\n".join(lines)


def run_remote_sample(args: argparse.Namespace, raw_dir: Path) -> Tuple[CommandResult, Dict[str, Section]]:
    remote_script = build_remote_script(args)
    save_text(raw_dir / "remote_script.sh", remote_script)
    ssh_args = [
        "ssh",
        "-o",
        f"ConnectTimeout={args.ssh_connect_timeout}",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if args.ssh_key:
        ssh_args.extend(["-i", args.ssh_key])
    ssh_args.extend([args.ssh_target, "sh -s"])

    timeout = (
        args.ssh_connect_timeout
        + args.ping_count * (args.ping_timeout + 1)
        + args.tcp_seconds
        + args.udp_seconds
        + 60
    )
    try:
        completed = subprocess.run(
            ssh_args,
            input=remote_script,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        result = CommandResult(
            completed.returncode == 0,
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )
    except FileNotFoundError:
        result = CommandResult(False, 127, "", "command not found: ssh\n")
    except subprocess.TimeoutExpired as exc:
        result = CommandResult(
            False,
            124,
            exc.stdout or "",
            f"timeout after {timeout}s\n{exc.stderr or ''}",
            True,
        )

    save_text(raw_dir / "ssh_stdout.txt", result.stdout)
    save_text(raw_dir / "ssh_stderr.txt", result.stderr)
    sections = parse_sections(result.stdout)
    for name, section in sections.items():
        save_text(raw_dir / f"{name}.txt", section.text)
    return result, sections


def collect_pc_context(raw_dir: Path) -> None:
    system = platform.system().lower()
    if system == "windows":
        save_local_command(raw_dir, "pc_ipconfig.txt", ["ipconfig", "/all"], timeout=10)
        if command_exists("powershell"):
            save_local_command(
                raw_dir,
                "pc_netadapter.txt",
                ["powershell", "-NoProfile", "-Command", "Get-NetAdapter | Format-Table -Auto"],
                timeout=10,
            )
    else:
        if command_exists("ip"):
            save_local_command(raw_dir, "pc_ip_addr.txt", ["ip", "-br", "addr"], timeout=10)


def start_iperf_server(args: argparse.Namespace) -> Optional[subprocess.Popen]:
    if not args.start_iperf_server:
        return None
    if not command_exists("iperf3"):
        print("Warning: iperf3 not found on PC. Start the server manually or add iperf3 to PATH.", file=sys.stderr)
        return None
    log_dir = Path(args.out) / "pc_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = (log_dir / "iperf3_server_stdout.log").open("a", encoding="utf-8")
    stderr = (log_dir / "iperf3_server_stderr.log").open("a", encoding="utf-8")
    process = subprocess.Popen(["iperf3", "-s"], stdout=stdout, stderr=stderr)
    time.sleep(1)
    if process.poll() is not None:
        print("Warning: iperf3 server exited immediately. Check firewall or whether the port is occupied.", file=sys.stderr)
        return None
    print("Started local iperf3 server on the PC.")
    return process


def stop_iperf_server(process: Optional[subprocess.Popen]) -> None:
    if process is None or process.poll() is not None:
        return
    if platform.system().lower() == "windows":
        process.terminate()
    else:
        process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()


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
    if not args.no_connect_prompt:
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


def plan_row_enabled(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "no", "n", "off", "skip"}


def load_plan(path: Path) -> List[Tuple[int, Dict[str, str], Optional[int]]]:
    if not path.exists():
        raise ValueError(f"plan file does not exist: {path}")

    items: List[Tuple[int, Dict[str, str], Optional[int]]] = []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"plan file has no header: {path}")

        for line_no, raw_row in enumerate(reader, start=2):
            row = {str(key).strip(): (value or "").strip() for key, value in raw_row.items() if key}
            if not any(row.values()):
                continue
            if not plan_row_enabled(row.get("enabled", "1")):
                continue

            cable_id = row.get("cable_id", "")
            if not cable_id:
                raise ValueError(f"{path}:{line_no}: cable_id is required")

            label = row.get("label") or "unknown"
            metadata = {
                "cable_id": cable_id,
                "label": label,
                "fault_type": row.get("fault_type") or label,
                "category": row.get("category", ""),
                "length_m": row.get("length_m", ""),
                "notes": row.get("notes", ""),
            }

            samples_text = row.get("samples_per_cable", "")
            samples_per_cable: Optional[int] = None
            if samples_text:
                try:
                    samples_per_cable = int(samples_text)
                except ValueError as exc:
                    raise ValueError(f"{path}:{line_no}: samples_per_cable must be an integer") from exc
                if samples_per_cable < 1:
                    raise ValueError(f"{path}:{line_no}: samples_per_cable must be >= 1")

            items.append((line_no, metadata, samples_per_cable))

    if not items:
        raise ValueError(f"plan file has no enabled cables: {path}")
    return items


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

    record: Dict[str, str] = {
        "session_id": session_id,
        "sample_id": sample_id,
        "repeat_index": str(repeat_index),
        "timestamp_start": now_iso(),
        "pc_host": socket.gethostname(),
        "ssh_target": args.ssh_target,
        "pc_ip": args.pc_ip,
        "gateway_ip": args.gateway_ip,
        "ping_target": test_targets(args)[0],
        "iperf_server": test_targets(args)[1],
        "operator": args.operator or "",
        "topology": args.topology,
        "iface": args.iface,
        "raw_dir": str(raw_dir),
    }
    record.update(metadata)
    errors: List[str] = []

    if args.stabilize > 0:
        time.sleep(args.stabilize)

    collect_pc_context(raw_dir)
    ssh_result, sections = run_remote_sample(args, raw_dir)
    record["ssh_ok"] = "1" if ssh_result.ok else "0"
    if not ssh_result.ok:
        errors.append(f"ssh failed rc={ssh_result.returncode}")

    if "ip_addr" in sections:
        record["pi_ipv4"] = parse_ip_json(sections["ip_addr"].text)
    if "carrier" in sections:
        carrier = sections["carrier"].text.strip().splitlines()
        record["carrier"] = carrier[0].strip() if carrier else ""
    if "ethtool" in sections:
        record.update(parse_ethtool(sections["ethtool"].text))
    if not record.get("link_detected") and record.get("carrier"):
        record["link_detected"] = "yes" if record["carrier"] == "1" else "no"

    if "stats_before" in sections and "stats_after" in sections:
        record.update(delta_stats(sections["stats_before"].text, sections["stats_after"].text))

    if "ping" in sections:
        record.update(parse_ping(sections["ping"].text))
    if "iperf_tcp" in sections:
        record.update(parse_iperf_tcp(load_json_text(sections["iperf_tcp"].text)))
    if "iperf_udp" in sections:
        record.update(parse_iperf_udp(load_json_text(sections["iperf_udp"].text)))
    if "cable_test" in sections:
        record["cable_test_status"] = parse_cable_test(sections["cable_test"].text, sections["cable_test"].rc == "0")

    for name, section in sections.items():
        if section.rc and section.rc != "0":
            errors.append(f"{name} rc={section.rc}")

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
            "    ssh={ssh} link={link} speed={speed} tcp={tcp} udp_loss={loss} errors={errors}".format(
                ssh=record.get("ssh_ok", ""),
                link=record.get("link_detected", ""),
                speed=record.get("speed_mbps", ""),
                tcp=record.get("tcp_receiver_mbps", ""),
                loss=record.get("udp_lost_percent", ""),
                errors=record.get("errors", ""),
            )
        )
        if repeat < args.samples_per_cable and args.interval > 0:
            time.sleep(args.interval)


def run_plan(
    args: argparse.Namespace,
    session_id: str,
    csv_path: Path,
    jsonl_path: Path,
) -> None:
    plan_path = Path(args.plan)
    items = load_plan(plan_path)
    print(f"\nPlan mode: {len(items)} enabled cable(s) from {plan_path}")
    print("Plan columns: " + ", ".join(PLAN_FIELDS))

    for index, (line_no, metadata, samples_per_cable) in enumerate(items, start=1):
        cable_args = argparse.Namespace(**vars(args))
        if samples_per_cable is not None:
            cable_args.samples_per_cable = samples_per_cable

        print(
            "\n[{index}/{total}] line {line_no}: cable={cable} label={label} fault={fault}".format(
                index=index,
                total=len(items),
                line_no=line_no,
                cable=metadata["cable_id"],
                label=metadata["label"],
                fault=metadata["fault_type"],
            )
        )
        if not args.no_connect_prompt:
            input("Connect this cable, then press Enter to start sampling...")
        run_for_cable(cable_args, session_id, metadata, csv_path, jsonl_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control Phytium Pi cable dataset sampling from the PC.")
    parser.add_argument("--ssh-target", required=True, help="SSH target for the Phytium Pi, for example user@192.168.10.3")
    parser.add_argument("--ssh-key", default="", help="optional SSH private key path")
    parser.add_argument("--ssh-connect-timeout", type=int, default=5, help="SSH connect timeout seconds")
    parser.add_argument("--pc-ip", default="", help="PC IP reachable from the Pi test interface, used when the PC runs iperf3 -s")
    parser.add_argument("--gateway-ip", default="", help="router/gateway IP reachable from the Pi test interface, for example 192.168.10.1")
    parser.add_argument("--ping-target", default="", help="override ping target. Defaults to --gateway-ip, then --pc-ip")
    parser.add_argument("--iperf-server", default="", help="iperf3 server IP. Use router IP if the router runs iperf3 -s, or PC IP if the PC runs iperf3 -s")
    parser.add_argument("--iface", default="eth0", help="Pi test interface, for example eth0")
    parser.add_argument("--out", default="data/raw/dataset_pc", help="output dataset directory on the PC")
    parser.add_argument("--operator", default="", help="operator name or team member")
    parser.add_argument("--topology", default="pc_direct", help="pc_direct, pc_switch, or custom text")

    parser.add_argument("--cable-id", default="", help="non-interactive cable ID. If omitted, interactive mode starts.")
    parser.add_argument("--label", default="", help="label, for example good/open/short/cross/split_pair/poor")
    parser.add_argument("--fault-type", default="", help="more specific fault label, for example open_pin_1")
    parser.add_argument("--category", default="", help="cable category, for example Cat5e or Cat6")
    parser.add_argument("--length-m", default="", help="cable length in meters")
    parser.add_argument("--notes", default="", help="free-form notes")
    parser.add_argument("--plan", default="", help="CSV plan with cable_id,label,fault_type,category,length_m,notes,samples_per_cable")
    parser.add_argument("--no-connect-prompt", action="store_true", help="do not wait for Enter before sampling each cable")

    parser.add_argument("--samples-per-cable", type=int, default=5, help="repeat samples for each cable")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between repeats")
    parser.add_argument("--stabilize", type=float, default=2.0, help="seconds to wait before each sample")

    parser.add_argument("--ping-count", type=int, default=10, help="ping packets per sample")
    parser.add_argument("--ping-timeout", type=int, default=2, help="ping timeout seconds per packet")
    parser.add_argument("--tcp-seconds", type=int, default=5, help="iperf3 TCP duration per sample")
    parser.add_argument("--tcp-parallel", type=int, default=4, help="iperf3 TCP parallel streams")
    parser.add_argument("--udp-seconds", type=int, default=5, help="iperf3 UDP duration per sample")
    parser.add_argument("--udp-bandwidth", default="100M", help="iperf3 UDP target bandwidth")

    parser.add_argument("--start-iperf-server", action="store_true", help="start iperf3 -s on the PC for this run")
    parser.add_argument("--skip-ping", action="store_true", help="skip ping")
    parser.add_argument("--skip-iperf", action="store_true", help="skip TCP iperf3")
    parser.add_argument("--skip-udp", action="store_true", help="skip UDP iperf3")
    parser.add_argument("--skip-ethtool", action="store_true", help="skip ethtool commands")
    parser.add_argument("--run-cable-test", action="store_true", help="run ethtool --cable-test on the Pi")
    return parser


def validate(args: argparse.Namespace) -> int:
    if args.samples_per_cable < 1:
        print("--samples-per-cable must be >= 1", file=sys.stderr)
        return 2
    if args.plan and args.cable_id:
        print("--plan and --cable-id cannot be used together.", file=sys.stderr)
        return 2
    if not command_exists("ssh"):
        print("Missing ssh command on the PC.", file=sys.stderr)
        return 2
    ping_target, iperf_target = test_targets(args)
    if not ping_target and not args.skip_ping:
        print("Warning: no --ping-target/--gateway-ip/--pc-ip set, so remote ping will be skipped.", file=sys.stderr)
    if not iperf_target and (not args.skip_iperf or not args.skip_udp):
        print("Warning: no --iperf-server/--pc-ip set, so remote iperf3 tests will be skipped.", file=sys.stderr)
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

    server = start_iperf_server(args)
    try:
        if args.plan:
            try:
                run_plan(args, session_id, csv_path, jsonl_path)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            print("\nDone.")
            return 0

        if args.cable_id:
            run_for_cable(args, session_id, metadata_from_args(args), csv_path, jsonl_path)
            return 0

        print("\nInteractive PC-control mode.")
        print("Recommended labels: good, open, short, cross, split_pair, poor, long, unknown.")
        while True:
            metadata = prompt_metadata(args)
            if metadata is None:
                break
            run_for_cable(args, session_id, metadata, csv_path, jsonl_path)
        print("\nDone.")
        return 0
    finally:
        stop_iperf_server(server)


if __name__ == "__main__":
    raise SystemExit(main())
