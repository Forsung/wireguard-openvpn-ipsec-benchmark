#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run_staged_matrix.sh vm 5GHz all
#   ./run_staged_matrix.sh pi 2.4GHz mobility
#
# Arguments:
#   $1 = client role (vm|pi)
#   $2 = Wi-Fi band label for metadata (default: 5GHz)
#   $3 = stage (default: all)
#
# Stages:
#   baseline | latency | loss | mtu | cpu_stress | mobility | all
#
# Notes:
# - Run this on the client machine.
# - Start iperf3 server on the VPS before running.
# - Handshake/reconnect are only measured in the mobility stage.
# - Adjust IPSEC_SERVER_IP if your strongSwan tunnel endpoint differs.

ROLE="${1:-}"
WIFI_BAND="${2:-${WIFI_BAND:-5GHz}}"
TARGET_STAGE="${3:-all}"

if [[ -z "$ROLE" ]]; then
  echo "Usage: $0 <vm|pi> [wifi-band] [stage]"
  exit 1
fi

BASE_DIR="$HOME/vpn-thesis/results"
SCRIPT_DIR="$HOME/vpn-thesis/scripts"
TEST_SYSTEM="$SCRIPT_DIR/test_run.py"

REPEATS=3
DURATION=60
PING_COUNT=50
PING_INTERVAL="0.2"
UDP_BW="50M"
CPU_WORKERS=2

if [[ "$ROLE" == "vm" ]]; then
  IFACE="enp0s3"
  WG_SERVER_IP="10.10.0.1"
  OVPN_SERVER_IP="10.20.0.1"
  IPSEC_SERVER_IP="192.168.1.175"
  OVPN_CLIENT_CONF="$HOME/vm-client.ovpn"
elif [[ "$ROLE" == "pi" ]]; then
  IFACE="eth0"
  WG_SERVER_IP="10.10.0.1"
  OVPN_SERVER_IP="10.20.0.1"
  IPSEC_SERVER_IP="192.168.1.175"
  OVPN_CLIENT_CONF="$HOME/pi-client.ovpn"
else
  echo "Invalid role: $ROLE"
  exit 1
fi

cleanup_vpn() {
  sudo wg-quick down wg0 2>/dev/null || true
  sudo pkill openvpn 2>/dev/null || true
  sudo ipsec down ikev2-client 2>/dev/null || true
  sudo systemctl stop strongswan-starter 2>/dev/null || true
}

run_case() {
  local stage="$1"
  local vpn="$2"
  local server_ip="$3"
  local repeat_id="$4"
  shift 4

  cleanup_vpn

  python3 "$TEST_SYSTEM" \
    --stage "$stage" \
    --client-role "$ROLE" \
    --wifi-band "$WIFI_BAND" \
    --vpn "$vpn" \
    --server-ip "$server_ip" \
    --iface "$IFACE" \
    --duration "$DURATION" \
    --ping-count "$PING_COUNT" \
    --ping-interval "$PING_INTERVAL" \
    --udp-bandwidth "$UDP_BW" \
    --cpu-workers "$CPU_WORKERS" \
    --start-vpn \
    --stop-vpn \
    --clear-netem \
    "$@" \
    --repeat-id "$repeat_id"
}

run_stage() {
  local stage="$1"
  echo "=================================================="
  echo "STAGE: $stage"
  echo "ROLE : $ROLE"
  echo "BAND : $WIFI_BAND"
  echo "=================================================="

  case "$stage" in
    baseline)
      for r in $(seq 1 "$REPEATS"); do
        echo "[baseline] WireGuard run $r"
        run_case baseline wireguard "$WG_SERVER_IP" "$r" --mtu 1500 --capture

        echo "[baseline] OpenVPN run $r"
        run_case baseline openvpn "$OVPN_SERVER_IP" "$r" --client-conf "$OVPN_CLIENT_CONF" --mtu 1500 --capture

        echo "[baseline] IPsec run $r"
        run_case baseline ipsec "$IPSEC_SERVER_IP" "$r" --mtu 1500 --capture
      done
      ;;

    latency)
      for r in $(seq 1 "$REPEATS"); do
        echo "[latency] WireGuard run $r"
        run_case latency wireguard "$WG_SERVER_IP" "$r" --delay 50 --mtu 1500 --capture

        echo "[latency] OpenVPN run $r"
        run_case latency openvpn "$OVPN_SERVER_IP" "$r" --client-conf "$OVPN_CLIENT_CONF" --delay 50 --mtu 1500 --capture

        echo "[latency] IPsec run $r"
        run_case latency ipsec "$IPSEC_SERVER_IP" "$r" --delay 50 --mtu 1500 --capture
      done
      ;;

    loss)
      for r in $(seq 1 "$REPEATS"); do
        echo "[loss] WireGuard run $r"
        run_case loss wireguard "$WG_SERVER_IP" "$r" --loss 1 --mtu 1500 --capture

        echo "[loss] OpenVPN run $r"
        run_case loss openvpn "$OVPN_SERVER_IP" "$r" --client-conf "$OVPN_CLIENT_CONF" --loss 1 --mtu 1500 --capture

        echo "[loss] IPsec run $r"
        run_case loss ipsec "$IPSEC_SERVER_IP" "$r" --loss 1 --mtu 1500 --capture
      done
      ;;

    mtu)
      for r in $(seq 1 "$REPEATS"); do
        echo "[mtu1400] WireGuard run $r"
        run_case mtu wireguard "$WG_SERVER_IP" "$r" --mtu 1400 --capture

        echo "[mtu1400] OpenVPN run $r"
        run_case mtu openvpn "$OVPN_SERVER_IP" "$r" --client-conf "$OVPN_CLIENT_CONF" --mtu 1400 --capture

        echo "[mtu1400] IPsec run $r"
        run_case mtu ipsec "$IPSEC_SERVER_IP" "$r" --mtu 1400 --capture
      done
      ;;

    cpu_stress)
      for r in $(seq 1 "$REPEATS"); do
        echo "[cpu_stress] WireGuard run $r"
        run_case cpu_stress wireguard "$WG_SERVER_IP" "$r" --mtu 1500 --capture --cpu-stress

        echo "[cpu_stress] OpenVPN run $r"
        run_case cpu_stress openvpn "$OVPN_SERVER_IP" "$r" --client-conf "$OVPN_CLIENT_CONF" --mtu 1500 --capture --cpu-stress

        echo "[cpu_stress] IPsec run $r"
        run_case cpu_stress ipsec "$IPSEC_SERVER_IP" "$r" --mtu 1500 --capture --cpu-stress
      done
      ;;

    mobility)
      for r in $(seq 1 "$REPEATS"); do
        echo "[mobility] WireGuard run $r"
        run_case mobility wireguard "$WG_SERVER_IP" "$r" --mtu 1500 --capture --measure-reconnect --measure-handshake

        echo "[mobility] OpenVPN run $r"
        run_case mobility openvpn "$OVPN_SERVER_IP" "$r" --client-conf "$OVPN_CLIENT_CONF" --mtu 1500 --capture --measure-reconnect --measure-handshake

        echo "[mobility] IPsec run $r"
        run_case mobility ipsec "$IPSEC_SERVER_IP" "$r" --mtu 1500 --capture --measure-reconnect --measure-handshake
      done
      ;;

    all)
      run_stage baseline
      run_stage latency
      run_stage loss
      run_stage mtu
      run_stage cpu_stress
      run_stage mobility
      ;;

    *)
      echo "Unknown stage: $stage"
      echo "Use: baseline | latency | loss | mtu | cpu_stress | mobility | all"
      exit 1
      ;;
  esac
}

mkdir -p "$BASE_DIR"
echo "[*] Starting staged matrix for role: $ROLE"
echo "[*] Wi-Fi band label: $WIFI_BAND"
echo "[*] Results will be stored under: $BASE_DIR"

run_stage "$TARGET_STAGE"

echo "[*] Done."