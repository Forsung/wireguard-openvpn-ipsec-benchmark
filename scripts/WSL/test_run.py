#!/usr/bin/env python3
"""
test_system.py
Automated VPN test runner for:
- WireGuard
- OpenVPN
- IPsec (strongSwan)

Features:
- Optional tunnel enable/disable
- Optional tc/netem impairment
- Ping, iperf3 TCP/UDP, CPU/memory sampling
- MTU control
- tcpdump capture
- CPU stress
- Optional reconnect timing
- Mobility-only handshake/reconnect support
- Structured output per run
- Unique per-run output folders
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None


DEFAULT_RESULTS_DIR = Path.home() / "vpn-thesis" / "results"


def run(cmd: str, check: bool = True, capture: bool = False, text: bool = True):
    print(f"[cmd] {cmd}")
    return subprocess.run(
        cmd,
        shell=True,
        check=check,
        capture_output=capture,
        text=text,
    )


def mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def timestamp_utc() -> str:
    return dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")


def hostname() -> str:
    return subprocess.check_output(["hostname"], text=True).strip()


def save_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def save_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def get_env_snapshot() -> str:
    parts = []
    parts.append(f"host={hostname()}")
    parts.append(f"utc={timestamp_utc()}")
    parts.append("")
    parts.append(run("uname -a", capture=True).stdout.strip())
    parts.append("")
    parts.append(run("ip route show", capture=True).stdout.strip())
    parts.append("")
    parts.append(run("ip addr show", capture=True).stdout.strip())
    return "\n".join(parts)


def set_mtu(iface: str, mtu: int | None):
    if mtu is not None:
        run(f"sudo ip link set dev {shlex.quote(iface)} mtu {int(mtu)}")


def start_capture(iface: str, outfile: Path):
    return subprocess.Popen(
        f"sudo tcpdump -i {shlex.quote(iface)} -w {shlex.quote(str(outfile))}",
        shell=True,
    )


def stop_capture(proc):
    if proc is not None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def start_cpu_stress(cpu_workers: int):
    # Run until explicitly terminated in cleanup
    return subprocess.Popen(
        f"stress-ng --cpu {int(cpu_workers)}",
        shell=True,
    )


def start_cpu_sampler(interval_s: float = 1.0):
    if psutil is None:
        raise RuntimeError("psutil is not installed. Install with: pip3 install psutil")

    samples = []
    stop_event = threading.Event()

    def worker():
        while not stop_event.is_set():
            samples.append(
                {
                    "ts": time.time(),
                    "cpu_percent": psutil.cpu_percent(interval=None),
                    "mem_percent": psutil.virtual_memory().percent,
                }
            )
            stop_event.wait(interval_s)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return stop_event, thread, samples


def wait_for_connectivity(server_ip: str, timeout_s: int = 120) -> bool:
    start = time.time()
    while time.time() - start < timeout_s:
        if (
            subprocess.run(
                ["ping", "-c", "1", "-W", "1", server_ip],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        ):
            return True
        time.sleep(1)
    return False


def start_vpn(vpn: str, client_conf: str | None = None):
    vpn = vpn.lower()

    if vpn == "wireguard":
        run("sudo wg-quick up wg0")
    elif vpn == "openvpn":
        if client_conf is None:
            client_conf = os.path.expanduser("~/vm-client.ovpn")
        run(f"sudo openvpn --config {shlex.quote(client_conf)} > /tmp/openvpn.log 2>&1 &")
        time.sleep(5)
    elif vpn == "ipsec":
        run("sudo systemctl restart strongswan-starter", check=False)
        time.sleep(2)
        run("sudo ipsec up ikev2-client", check=False)
    else:
        raise ValueError(f"Unsupported VPN: {vpn}")


def stop_vpn(vpn: str):
    vpn = vpn.lower()

    if vpn == "wireguard":
        run("sudo wg-quick down wg0", check=False)
    elif vpn == "openvpn":
        run("sudo pkill openvpn", check=False)
    elif vpn == "ipsec":
        run("sudo ipsec down ikev2-client || true", check=False)
        run("sudo systemctl stop strongswan-starter", check=False)
    else:
        raise ValueError(f"Unsupported VPN: {vpn}")


def apply_netem(iface: str, delay_ms: int | None, loss_pct: float | None):
    args = ["sudo tc qdisc replace dev", iface, "root netem"]
    if delay_ms is not None:
        args.append(f"delay {delay_ms}ms")
    if loss_pct is not None:
        args.append(f"loss {loss_pct}%")
    run(" ".join(args))


def clear_netem(iface: str):
    run(f"sudo tc qdisc del dev {shlex.quote(iface)} root", check=False)


def protocol_snapshot(vpn: str, outdir: Path):
    vpn = vpn.lower()

    if vpn == "wireguard":
        save_text(outdir / "wg_show.txt", run("sudo wg show", capture=True, check=False).stdout)
    elif vpn == "openvpn":
        save_text(outdir / "openvpn_ps.txt", run("ps aux | grep [o]penvpn", capture=True, check=False).stdout)
        save_text(outdir / "openvpn_status.txt", run("sudo cat /tmp/openvpn.log", capture=True, check=False).stdout)
    elif vpn == "ipsec":
        save_text(outdir / "ipsec_status.txt", run("sudo ipsec statusall", capture=True, check=False).stdout)


def measure_reconnect(vpn: str, server_ip: str, iface: str, client_conf: str | None = None, timeout_s: int = 60) -> int:
    """
    Measure time from a protocol-specific disruption to first successful ping to server.
    Returns milliseconds, or -1 on timeout.
    """
    vpn = vpn.lower()
    t0 = time.time()

    if vpn == "wireguard":
        run("sudo wg-quick down wg0", check=False)
        time.sleep(2)
        run("sudo wg-quick up wg0", check=False)
    elif vpn == "openvpn":
        run("sudo pkill openvpn", check=False)
        time.sleep(2)
        start_vpn("openvpn", client_conf)
    elif vpn == "ipsec":
        run("sudo ipsec down ikev2-client || true", check=False)
        time.sleep(2)
        start_vpn("ipsec", client_conf)
    else:
        raise ValueError(f"Unsupported VPN for reconnect test: {vpn}")

    start = time.time()
    while time.time() - start < timeout_s:
        res = subprocess.run(
            ["ping", "-c", "1", "-W", "1", server_ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if res.returncode == 0:
            return int((time.time() - t0) * 1000)
        time.sleep(1)

    return -1


def measure_handshake(vpn: str, server_ip: str, client_conf: str | None = None, timeout_s: int = 120) -> int:
    """
    Measure time from tunnel stop/start to first successful ping to server.
    Returns milliseconds, or -1 on timeout.
    """
    t0 = time.time()
    stop_vpn(vpn)
    start_vpn(vpn, client_conf)

    if wait_for_connectivity(server_ip, timeout_s=timeout_s):
        return int((time.time() - t0) * 1000)
    return -1


def run_single_test(args, outdir: Path):
    mkdir(outdir)

    #cap_proc = None
    stress_proc = None
    cpu_stop_event = None
    cpu_thread = None
    cpu_samples = []
    cpu_written = False

    try:
        # Start VPN first if requested by driver
        if args.start_vpn:
            start_vpn(args.vpn, args.client_conf)

        # Apply MTU before traffic begins
        set_mtu(args.iface, args.mtu)

        # Apply netem before measurements
        if args.delay is not None or args.loss is not None:
            apply_netem(args.iface, args.delay, args.loss)

        # Start packet capture if requested
        #if args.capture:
         #   cap_proc = start_capture(args.iface, outdir / "capture.pcap")

        # Start CPU stress if requested
        if args.cpu_stress:
            stress_proc = start_cpu_stress(args.cpu_workers)

        # Save environment snapshot early
        save_text(outdir / "environment.txt", get_env_snapshot())

        # Wait for reachability
        if not wait_for_connectivity(args.server_ip, timeout_s=args.wait_timeout):
            raise RuntimeError(f"Server {args.server_ip} did not become reachable within timeout")

        # Start CPU sampler for the actual measurement window
        cpu_stop_event, cpu_thread, cpu_samples = start_cpu_sampler(interval_s=args.cpu_sample_interval)

        # Ping
        ping_cmd = f"ping -i {args.ping_interval} -c {args.ping_count} {shlex.quote(args.server_ip)}"
        ping_res = run(ping_cmd, capture=True)
        save_text(outdir / "ping.log", ping_res.stdout + "\n" + ping_res.stderr)

        # iperf3 TCP
        tcp_cmd = f"iperf3 -c {shlex.quote(args.server_ip)} -t {args.duration} -J"
        tcp_res = run(tcp_cmd, capture=True)
        save_text(outdir / "iperf_tcp.json", tcp_res.stdout)

        # iperf3 UDP
        udp_cmd = f"iperf3 -c {shlex.quote(args.server_ip)} -u -b {args.udp_bandwidth} -t {args.duration} -J"
        udp_res = run(udp_cmd, capture=True)
        save_text(outdir / "iperf_udp.json", udp_res.stdout)

        # Stop CPU sampler and save CPU/memory samples for the active measurement window
        if cpu_stop_event is not None:
            cpu_stop_event.set()
        if cpu_thread is not None:
            cpu_thread.join(timeout=5)
        if cpu_samples:
            save_json(outdir / "cpu.json", cpu_samples)
            cpu_written = True

        # Save route/interface info
        save_text(outdir / "ip_route.txt", run("ip route show", capture=True).stdout)
        save_text(outdir / "ip_addr.txt", run("ip addr show", capture=True).stdout)

        # Mobility-only measurements
        if args.measure_reconnect:
            reconnect = measure_reconnect(
                args.vpn,
                args.server_ip,
                args.iface,
                client_conf=args.client_conf,
                timeout_s=args.wait_timeout,
            )
            save_text(outdir / "reconnect_ms.txt", str(reconnect))

        if args.measure_handshake:
            handshake = measure_handshake(
                args.vpn,
                args.server_ip,
                client_conf=args.client_conf,
                timeout_s=args.wait_timeout,
            )
            save_text(outdir / "handshake_ms.txt", str(handshake))

        # Public IP
        pub = run("curl -s ifconfig.me", capture=True, check=False)
        save_text(outdir / "public_ip.txt", pub.stdout.strip() + "\n")

        # Snapshot VPN state
        protocol_snapshot(args.vpn, outdir)

        # Metadata
        metadata = {
            "run_id": outdir.name,
            "stage": args.stage,
            "timestamp_utc": timestamp_utc(),
            "host": hostname(),
            "client_role": args.client_role,
            "wifi_band": args.wifi_band,
            "vpn": args.vpn,
            "server_ip": args.server_ip,
            "duration_sec": args.duration,
            "ping_count": args.ping_count,
            "ping_interval_sec": args.ping_interval,
            "udp_bandwidth": args.udp_bandwidth,
            "iface": args.iface,
            "delay_ms": args.delay,
            "loss_pct": args.loss,
            "mtu": args.mtu,
            "repeat": args.repeat_id,
            "cpu_stress": args.cpu_stress,
            "cpu_workers": args.cpu_workers,
            "cpu_sample_interval_sec": args.cpu_sample_interval,
            "capture": args.capture,
            "start_vpn": args.start_vpn,
            "stop_vpn": args.stop_vpn,
            "measure_handshake": args.measure_handshake,
            "measure_reconnect": args.measure_reconnect,
            "client_conf": args.client_conf,
        }
        save_json(outdir / "metadata.json", metadata)

    finally:
        # Ensure sampler stops even if a test fails
        if cpu_stop_event is not None and not cpu_stop_event.is_set():
            cpu_stop_event.set()
        if cpu_thread is not None:
            cpu_thread.join(timeout=5)
        if cpu_samples and not cpu_written:
            try:
                save_json(outdir / "cpu.json", cpu_samples)
            except Exception:
                pass

        #if cap_proc is not None:
         #   stop_capture(cap_proc)

        if stress_proc is not None:
            stress_proc.terminate()
            try:
                stress_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                stress_proc.kill()

        if args.clear_netem:
            clear_netem(args.iface)

        if args.stop_vpn:
            stop_vpn(args.vpn)


def parse_args():
    p = argparse.ArgumentParser()

    p.add_argument("--stage", default="run")
    p.add_argument("--client-role", default="unknown", help="vm or pi")
    p.add_argument("--wifi-band", required=True, choices=["5GHz", "2.4GHz"])

    p.add_argument("--vpn", required=True, choices=["wireguard", "openvpn", "ipsec"])
    p.add_argument("--server-ip", required=True)
    p.add_argument("--duration", type=int, default=60)
    p.add_argument("--ping-count", type=int, default=50)
    p.add_argument("--ping-interval", type=float, default=0.2)
    p.add_argument("--udp-bandwidth", default="50M")
    p.add_argument("--iface", default="eth0")
    p.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    p.add_argument("--client-conf", default=None)
    p.add_argument("--wait-timeout", type=int, default=120)

    p.add_argument("--delay", type=int)
    p.add_argument("--loss", type=float)
    p.add_argument("--mtu", type=int)

    p.add_argument("--capture", action="store_true")
    p.add_argument("--cpu-stress", action="store_true")
    p.add_argument("--cpu-workers", type=int, default=2)
    p.add_argument("--cpu-sample-interval", type=float, default=1.0)
    p.add_argument("--repeat-id", default="1")

    p.add_argument("--start-vpn", action="store_true")
    p.add_argument("--stop-vpn", action="store_true")
    p.add_argument("--clear-netem", action="store_true")
    p.add_argument("--measure-handshake", action="store_true")
    p.add_argument("--measure-reconnect", action="store_true")

    return p.parse_args()


def main():
    args = parse_args()
    base = Path(args.results_dir)
    mkdir(base)

    band_tag = args.wifi_band.replace(" ", "").replace("/", "-")
    role_tag = args.client_role.replace(" ", "").replace("/", "-")

    # Unique run folder: stage + vpn + role + band + timestamp + repeat + random suffix
    run_id = (
        f"{args.stage}_{args.vpn}_{role_tag}_{band_tag}_"
        f"{timestamp_utc()}_r{args.repeat_id}_{uuid.uuid4().hex[:8]}"
    )
    outdir = base / run_id

    try:
        run_single_test(args, outdir)
        print(f"[done] results saved to {outdir}")
    except Exception as e:
        mkdir(outdir)
        save_text(outdir / "error.txt", f"{type(e).__name__}: {e}\n")
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
