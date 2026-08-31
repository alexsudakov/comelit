#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
CONFIG=/root/.config/comelit/p14-firewall.env
TABLE=comelit_p14
[[ "${EUID}" -eq 0 ]] || { echo 'P14_FIREWALL_REQUIRES_ROOT=true'; exit 1; }
[[ $# -eq 1 ]] || { echo 'usage: p14_firewall.sh start|stop' >&2; exit 64; }
ACTION="$1"
stop_table(){ if nft list table inet "$TABLE" >/dev/null 2>&1; then nft delete table inet "$TABLE"; fi; }
case "$ACTION" in
 stop) stop_table; echo 'P14_FIREWALL_ACTIVE=false' ;;
 start)
  [[ -f "$CONFIG" ]] || { echo 'P14_FIREWALL_CONFIG_PRESENT=false'; exit 1; }
  [[ "$(stat -c '%u:%a' "$CONFIG")" == '0:600' ]]
  source "$CONFIG"; : "${P14_HA_CLIENT_IP:?}" "${P14_BRIDGE_PORT:?}"
  python3 - "$P14_HA_CLIENT_IP" "$P14_BRIDGE_PORT" <<'PY'
import ipaddress,sys
addr=ipaddress.ip_address(sys.argv[1])
if addr.version != 4 or not addr.is_private or addr.is_loopback or addr.is_unspecified or addr.is_multicast or addr.is_link_local: raise SystemExit("P14_FIREWALL_HA_ADDRESS=FAIL")
if int(sys.argv[2]) != 18014: raise SystemExit("P14_FIREWALL_PORT=FAIL")
PY
  stop_table
  nft -f - <<EOF
add table inet $TABLE
add chain inet $TABLE input { type filter hook input priority 10; policy accept; }
add rule inet $TABLE input tcp dport $P14_BRIDGE_PORT iifname != "lo" ip saddr != $P14_HA_CLIENT_IP drop
EOF
  nft list table inet "$TABLE" >/dev/null
  echo 'P14_FIREWALL_ACTIVE=true'; echo 'P14_FIREWALL_PORT=18014'; echo 'P14_FIREWALL_POLICY=HA_CLIENT_PLUS_LOOPBACK_ONLY' ;;
 *) echo 'usage: p14_firewall.sh start|stop' >&2; exit 64 ;;
esac
