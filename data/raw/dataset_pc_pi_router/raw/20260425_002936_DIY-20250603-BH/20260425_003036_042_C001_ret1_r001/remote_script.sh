set +e
export LC_ALL=C LANG=C
IFACE='eth0'
GATEWAY_IP='192.168.10.1'
IPERF_SERVER=''
stats() {
  for f in rx_bytes tx_bytes rx_packets tx_packets rx_errors tx_errors rx_dropped tx_dropped collisions rx_crc_errors rx_frame_errors tx_carrier_errors; do
    v=$(cat "/sys/class/net/$IFACE/statistics/$f" 2>/dev/null || true)
    printf '%s=%s\n' "$f" "$v"
  done
}
section() {
  name="$1"
  shift
  echo "__CABLE_BEGIN__:$name"
  "$@" 2>&1
  rc=$?
  echo "__CABLE_RC__:$name:$rc"
  echo "__CABLE_END__:$name"
}
echo "__CABLE_BEGIN__:ip_addr"
ip -j addr show dev "$IFACE" 2>&1
rc=$?
echo "__CABLE_RC__:ip_addr:$rc"
echo "__CABLE_END__:ip_addr"
echo "__CABLE_BEGIN__:carrier"
cat "/sys/class/net/$IFACE/carrier" 2>&1
rc=$?
echo "__CABLE_RC__:carrier:$rc"
echo "__CABLE_END__:carrier"
echo "__CABLE_BEGIN__:ethtool"
ethtool "$IFACE" 2>&1
rc=$?
echo "__CABLE_RC__:ethtool:$rc"
echo "__CABLE_END__:ethtool"
echo "__CABLE_BEGIN__:stats_before"
stats
echo "__CABLE_RC__:stats_before:0"
echo "__CABLE_END__:stats_before"
if [ -n "$GATEWAY_IP" ]; then
  echo "__CABLE_BEGIN__:ping"
  timeout 30 ping -c 10 -W 2 "$GATEWAY_IP" 2>&1
  rc=$?
  echo "__CABLE_RC__:ping:$rc"
  echo "__CABLE_END__:ping"
fi
echo "__CABLE_BEGIN__:stats_after"
stats
echo "__CABLE_RC__:stats_after:0"
echo "__CABLE_END__:stats_after"
echo "__CABLE_BEGIN__:ethtool_stats"
ethtool -S "$IFACE" 2>&1
rc=$?
echo "__CABLE_RC__:ethtool_stats:$rc"
echo "__CABLE_END__:ethtool_stats"
