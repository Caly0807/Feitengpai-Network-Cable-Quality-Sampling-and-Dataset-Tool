param(
    [string]$SshTarget = "user@192.168.31.109",
    [string]$GatewayIp = "192.168.10.1",
    [string]$Iface = "eth0",
    [string]$Out = "data/raw/dataset_pc_pi_router",
    [string]$Operator = "your_name",
    [string]$Topology = "pi_router_gateway",
    [int]$SamplesPerCable = 5,
    [int]$PingCount = 10,
    [int]$PingTimeout = 2,
    [int]$TcpSeconds = 5,
    [int]$TcpParallel = 4,
    [int]$UdpSeconds = 5,
    [string]$UdpBandwidth = "100M",
    [string]$IperfServer = "",
    [switch]$SkipIperf,
    [switch]$SkipUdp,
    [switch]$RunCableTest
)

$ErrorActionPreference = "Continue"

$Fields = @(
    "session_id",
    "sample_id",
    "repeat_index",
    "timestamp_start",
    "timestamp_end",
    "pc_host",
    "ssh_target",
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
    "errors"
)

$Stats = @(
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
    "tx_carrier_errors"
)

function Get-IsoNow {
    return (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
}

function Get-Slug([string]$Value, [string]$Fallback = "unknown") {
    $clean = ($Value.Trim() -replace '[^A-Za-z0-9_.-]+', '_').Trim("._-")
    if ([string]::IsNullOrWhiteSpace($clean)) { return $Fallback }
    return $clean
}

function Shell-SingleQuote([string]$Value) {
    return "'" + ($Value -replace "'", "'`"`"`'") + "'"
}

function Add-Row {
    param(
        [string]$Path,
        [hashtable]$Row
    )
    $obj = [ordered]@{}
    foreach ($field in $Fields) {
        if ($Row.ContainsKey($field)) {
            $obj[$field] = [string]$Row[$field]
        } else {
            $obj[$field] = ""
        }
    }
    $psObj = [pscustomobject]$obj
    if (-not (Test-Path $Path)) {
        $psObj | Export-Csv -Path $Path -NoTypeInformation -Encoding UTF8
    } else {
        $psObj | Export-Csv -Path $Path -NoTypeInformation -Encoding UTF8 -Append
    }
}

function Add-Jsonl {
    param(
        [string]$Path,
        [hashtable]$Row
    )
    $obj = [ordered]@{}
    foreach ($field in $Fields) {
        if ($Row.ContainsKey($field)) {
            $obj[$field] = [string]$Row[$field]
        } else {
            $obj[$field] = ""
        }
    }
    ($obj | ConvertTo-Json -Compress) | Add-Content -Path $Path -Encoding UTF8
}

function Get-Section {
    param(
        [string[]]$Lines,
        [string]$Name
    )
    $begin = "__CABLE_BEGIN__:$Name"
    $end = "__CABLE_END__:$Name"
    $inside = $false
    $buf = New-Object System.Collections.Generic.List[string]
    foreach ($line in $Lines) {
        if ($line -eq $begin) {
            $inside = $true
            continue
        }
        if ($line -eq $end) {
            break
        }
        if ($inside -and -not $line.StartsWith("__CABLE_RC__:$Name")) {
            $buf.Add($line)
        }
    }
    return ($buf -join "`n")
}

function Get-SectionRc {
    param(
        [string[]]$Lines,
        [string]$Name
    )
    foreach ($line in $Lines) {
        if ($line.StartsWith("__CABLE_RC__:$Name`:")) {
            return $line.Substring(("__CABLE_RC__:$Name`:").Length).Trim()
        }
    }
    return ""
}

function Parse-IpJson([string]$Text) {
    try {
        $data = $Text | ConvertFrom-Json
        $ips = @()
        foreach ($item in @($data)) {
            foreach ($addr in @($item.addr_info)) {
                if ($addr.family -eq "inet" -and $addr.local) {
                    $ips += $addr.local
                }
            }
        }
        return ($ips -join ",")
    } catch {
        return ""
    }
}

function Parse-Ethtool {
    param(
        [string]$Text,
        [hashtable]$Row
    )
    if ($Text -match '(?m)^\s*Speed:\s*([0-9]+)\s*Mb/s') { $Row["speed_mbps"] = $Matches[1] }
    if ($Text -match '(?m)^\s*Duplex:\s*([A-Za-z]+)') { $Row["duplex"] = $Matches[1] }
    if ($Text -match '(?m)^\s*Auto-negotiation:\s*([A-Za-z]+)') { $Row["autoneg"] = $Matches[1] }
    if ($Text -match '(?m)^\s*Link detected:\s*([A-Za-z]+)') { $Row["link_detected"] = $Matches[1].ToLower() }
}

function Parse-Ping {
    param(
        [string]$Text,
        [hashtable]$Row
    )
    if ($Text -match '(\d+)\s+packets transmitted,\s+(\d+)\s+(?:packets )?received,.*?([0-9.]+)%\s+packet loss') {
        $Row["ping_sent"] = $Matches[1]
        $Row["ping_received"] = $Matches[2]
        $Row["ping_loss_percent"] = $Matches[3]
    }
    if ($Text -match '(?:rtt|round-trip).*?=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)') {
        $Row["ping_min_ms"] = $Matches[1]
        $Row["ping_avg_ms"] = $Matches[2]
        $Row["ping_max_ms"] = $Matches[3]
    }
}

function Parse-IperfTcp {
    param(
        [string]$Text,
        [hashtable]$Row
    )
    try {
        $data = $Text | ConvertFrom-Json
        if ($null -ne $data.end.sum_sent.bits_per_second) {
            $Row["tcp_sender_mbps"] = "{0:N3}" -f ([double]$data.end.sum_sent.bits_per_second / 1000000)
        }
        if ($null -ne $data.end.sum_received.bits_per_second) {
            $Row["tcp_receiver_mbps"] = "{0:N3}" -f ([double]$data.end.sum_received.bits_per_second / 1000000)
        }
        if ($null -ne $data.end.sum_sent.retransmits) {
            $Row["tcp_retransmits"] = [string]$data.end.sum_sent.retransmits
        }
    } catch {}
}

function Parse-IperfUdp {
    param(
        [string]$Text,
        [hashtable]$Row
    )
    try {
        $data = $Text | ConvertFrom-Json
        $sum = $data.end.sum
        if ($null -ne $sum.bits_per_second) { $Row["udp_mbps"] = "{0:N3}" -f ([double]$sum.bits_per_second / 1000000) }
        if ($null -ne $sum.jitter_ms) { $Row["udp_jitter_ms"] = [string]([math]::Round([double]$sum.jitter_ms, 3)) }
        if ($null -ne $sum.lost_percent) { $Row["udp_lost_percent"] = [string]([math]::Round([double]$sum.lost_percent, 3)) }
        if ($null -ne $sum.lost_packets) { $Row["udp_lost_packets"] = [string]$sum.lost_packets }
        if ($null -ne $sum.packets) { $Row["udp_packets"] = [string]$sum.packets }
    } catch {}
}

function Parse-Stats([string]$Text) {
    $map = @{}
    foreach ($line in ($Text -split "`n")) {
        if ($line -match '^([^=]+)=(-?\d+)$') {
            $map[$Matches[1].Trim()] = [int64]$Matches[2]
        }
    }
    return $map
}

function Add-StatsDelta {
    param(
        [string]$BeforeText,
        [string]$AfterText,
        [hashtable]$Row
    )
    $before = Parse-Stats $BeforeText
    $after = Parse-Stats $AfterText
    foreach ($name in $Stats) {
        $key = "${name}_delta"
        if ($before.ContainsKey($name) -and $after.ContainsKey($name)) {
            $Row[$key] = [string]($after[$name] - $before[$name])
        }
    }
}

function New-RemoteScript {
    param(
        [string]$Iface,
        [string]$GatewayIp,
        [string]$IperfServer,
        [int]$PingCount,
        [int]$PingTimeout,
        [int]$TcpSeconds,
        [int]$TcpParallel,
        [int]$UdpSeconds,
        [string]$UdpBandwidth,
        [bool]$SkipIperf,
        [bool]$SkipUdp,
        [bool]$RunCableTest
    )
    $statsNames = $Stats -join " "
    $ifaceQ = Shell-SingleQuote $Iface
    $gatewayQ = Shell-SingleQuote $GatewayIp
    $iperfQ = Shell-SingleQuote $IperfServer
    $udpQ = Shell-SingleQuote $UdpBandwidth
    $pingLimit = [math]::Max(8, $PingCount * ($PingTimeout + 1))
    $tcpLimit = $TcpSeconds + 20
    $udpLimit = $UdpSeconds + 20

    $script = @"
set +e
export LC_ALL=C LANG=C
IFACE=$ifaceQ
GATEWAY_IP=$gatewayQ
IPERF_SERVER=$iperfQ
stats() {
  for f in $statsNames; do
    v=`$(cat "/sys/class/net/`$IFACE/statistics/`$f" 2>/dev/null || true)
    printf '%s=%s\n' "`$f" "`$v"
  done
}
section() {
  name="`$1"
  shift
  echo "__CABLE_BEGIN__:`$name"
  "`$@" 2>&1
  rc=`$?
  echo "__CABLE_RC__:`$name:`$rc"
  echo "__CABLE_END__:`$name"
}
echo "__CABLE_BEGIN__:ip_addr"
ip -j addr show dev "`$IFACE" 2>&1
rc=`$?
echo "__CABLE_RC__:ip_addr:`$rc"
echo "__CABLE_END__:ip_addr"
echo "__CABLE_BEGIN__:carrier"
cat "/sys/class/net/`$IFACE/carrier" 2>&1
rc=`$?
echo "__CABLE_RC__:carrier:`$rc"
echo "__CABLE_END__:carrier"
echo "__CABLE_BEGIN__:ethtool"
ethtool "`$IFACE" 2>&1
rc=`$?
echo "__CABLE_RC__:ethtool:`$rc"
echo "__CABLE_END__:ethtool"
echo "__CABLE_BEGIN__:stats_before"
stats
echo "__CABLE_RC__:stats_before:0"
echo "__CABLE_END__:stats_before"
if [ -n "`$GATEWAY_IP" ]; then
  echo "__CABLE_BEGIN__:ping"
  timeout $pingLimit ping -c $PingCount -W $PingTimeout "`$GATEWAY_IP" 2>&1
  rc=`$?
  echo "__CABLE_RC__:ping:`$rc"
  echo "__CABLE_END__:ping"
fi

"@

    if (-not $SkipIperf) {
        $script += @"
if [ -n "`$IPERF_SERVER" ]; then
  echo "__CABLE_BEGIN__:iperf_tcp"
  timeout $tcpLimit iperf3 -c "`$IPERF_SERVER" -t $TcpSeconds -P $TcpParallel -J 2>&1
  rc=`$?
  echo "__CABLE_RC__:iperf_tcp:`$rc"
  echo "__CABLE_END__:iperf_tcp"
fi

"@
    }
    if (-not $SkipUdp) {
        $script += @"
if [ -n "`$IPERF_SERVER" ]; then
  echo "__CABLE_BEGIN__:iperf_udp"
  timeout $udpLimit iperf3 -c "`$IPERF_SERVER" -u -b $udpQ -t $UdpSeconds -J 2>&1
  rc=`$?
  echo "__CABLE_RC__:iperf_udp:`$rc"
  echo "__CABLE_END__:iperf_udp"
fi

"@
    }
    $script += @"
echo "__CABLE_BEGIN__:stats_after"
stats
echo "__CABLE_RC__:stats_after:0"
echo "__CABLE_END__:stats_after"
echo "__CABLE_BEGIN__:ethtool_stats"
ethtool -S "`$IFACE" 2>&1
rc=`$?
echo "__CABLE_RC__:ethtool_stats:`$rc"
echo "__CABLE_END__:ethtool_stats"
"@
    if ($RunCableTest) {
        $script += @"
echo "__CABLE_BEGIN__:cable_test"
ethtool --cable-test "`$IFACE" 2>&1
rc=`$?
echo "__CABLE_RC__:cable_test:`$rc"
echo "__CABLE_END__:cable_test"
"@
    }
    return $script
}

function Invoke-RemoteSample {
    param(
        [string]$RawDir
    )
    $remoteScript = New-RemoteScript `
        -Iface $Iface `
        -GatewayIp $GatewayIp `
        -IperfServer $IperfServer `
        -PingCount $PingCount `
        -PingTimeout $PingTimeout `
        -TcpSeconds $TcpSeconds `
        -TcpParallel $TcpParallel `
        -UdpSeconds $UdpSeconds `
        -UdpBandwidth $UdpBandwidth `
        -SkipIperf ([bool]$SkipIperf) `
        -SkipUdp ([bool]$SkipUdp) `
        -RunCableTest ([bool]$RunCableTest)

    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remoteScript))
    Set-Content -Path (Join-Path $RawDir "remote_script.sh") -Value $remoteScript -Encoding UTF8
    $remoteCmd = "printf '%s' '$encoded' | base64 -d | sh"
    $output = & ssh -o ConnectTimeout=8 -o ServerAliveInterval=5 -o StrictHostKeyChecking=accept-new $SshTarget $remoteCmd 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | ForEach-Object { [string]$_ }) -join "`n"
    Set-Content -Path (Join-Path $RawDir "ssh_output.txt") -Value $text -Encoding UTF8
    return @{
        ExitCode = $exitCode
        Lines = @($text -split "`r?`n")
    }
}

function Read-WithDefault([string]$Prompt, [string]$Default = "") {
    if ($Default) {
        $value = Read-Host "$Prompt [$Default]"
        if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
        return $value.Trim()
    }
    $value = Read-Host $Prompt
    return $value.Trim()
}

$OutDir = Join-Path (Get-Location) $Out
$RawRoot = Join-Path $OutDir "raw"
$CsvPath = Join-Path $OutDir "samples.csv"
$JsonlPath = Join-Path $OutDir "samples.jsonl"
New-Item -ItemType Directory -Force -Path $OutDir, $RawRoot | Out-Null

$SessionId = (Get-Date).ToString("yyyyMMdd_HHmmss") + "_" + (Get-Slug $env:COMPUTERNAME)

Write-Host "Session: $SessionId" -ForegroundColor Cyan
Write-Host "SSH target: $SshTarget"
Write-Host "Gateway: $GatewayIp"
Write-Host "Interface: $Iface"
Write-Host "Summary CSV: $CsvPath"
Write-Host ""

while ($true) {
    $cableId = Read-WithDefault "Cable ID, blank to finish"
    if ([string]::IsNullOrWhiteSpace($cableId)) {
        break
    }
    $label = Read-WithDefault "Label (good/open/short/cross/split_pair/poor/unknown)" "unknown"
    $faultType = Read-WithDefault "Fault type" $label
    $category = Read-WithDefault "Category, for example Cat5e/Cat6"
    $lengthM = Read-WithDefault "Length in meters"
    $notes = Read-WithDefault "Notes"
    Read-Host "Connect this cable between Phytium Pi eth0 and router, then press Enter"

    Write-Host ""
    Write-Host "Sampling cable=$cableId label=$label" -ForegroundColor Yellow

    for ($repeat = 1; $repeat -le $SamplesPerCable; $repeat++) {
        $stamp = (Get-Date).ToString("yyyyMMdd_HHmmss_fff")
        $sampleId = "$stamp`_$(Get-Slug $cableId)_r$($repeat.ToString("000"))"
        $rawDir = Join-Path (Join-Path $RawRoot $SessionId) $sampleId
        New-Item -ItemType Directory -Force -Path $rawDir | Out-Null

        $row = @{
            session_id = $SessionId
            sample_id = $sampleId
            repeat_index = [string]$repeat
            timestamp_start = Get-IsoNow
            pc_host = $env:COMPUTERNAME
            ssh_target = $SshTarget
            gateway_ip = $GatewayIp
            ping_target = $GatewayIp
            iperf_server = $IperfServer
            operator = $Operator
            topology = $Topology
            iface = $Iface
            cable_id = $cableId
            label = $label
            fault_type = $faultType
            category = $category
            length_m = $lengthM
            notes = $notes
            raw_dir = $rawDir
        }
        $errors = New-Object System.Collections.Generic.List[string]

        Start-Sleep -Seconds 2
        Write-Host "  sample $repeat/$SamplesPerCable ..." -NoNewline
        $result = Invoke-RemoteSample -RawDir $rawDir
        $row["ssh_ok"] = if ($result.ExitCode -eq 0) { "1" } else { "0" }
        if ($result.ExitCode -ne 0) { $errors.Add("ssh failed rc=$($result.ExitCode)") }

        $lines = $result.Lines
        $ipAddr = Get-Section -Lines $lines -Name "ip_addr"
        $carrier = Get-Section -Lines $lines -Name "carrier"
        $ethtool = Get-Section -Lines $lines -Name "ethtool"
        $statsBefore = Get-Section -Lines $lines -Name "stats_before"
        $statsAfter = Get-Section -Lines $lines -Name "stats_after"
        $ping = Get-Section -Lines $lines -Name "ping"
        $iperfTcp = Get-Section -Lines $lines -Name "iperf_tcp"
        $iperfUdp = Get-Section -Lines $lines -Name "iperf_udp"
        $cableTest = Get-Section -Lines $lines -Name "cable_test"

        Set-Content -Path (Join-Path $rawDir "ip_addr.json") -Value $ipAddr -Encoding UTF8
        Set-Content -Path (Join-Path $rawDir "ethtool.txt") -Value $ethtool -Encoding UTF8
        Set-Content -Path (Join-Path $rawDir "ping.txt") -Value $ping -Encoding UTF8
        Set-Content -Path (Join-Path $rawDir "iperf_tcp.json") -Value $iperfTcp -Encoding UTF8
        Set-Content -Path (Join-Path $rawDir "iperf_udp.json") -Value $iperfUdp -Encoding UTF8

        $row["pi_ipv4"] = Parse-IpJson $ipAddr
        $row["carrier"] = ($carrier -split "`r?`n" | Select-Object -First 1).Trim()
        Parse-Ethtool -Text $ethtool -Row $row
        if (-not $row.ContainsKey("link_detected") -and $row["carrier"]) {
            $row["link_detected"] = if ($row["carrier"] -eq "1") { "yes" } else { "no" }
        }
        Add-StatsDelta -BeforeText $statsBefore -AfterText $statsAfter -Row $row
        Parse-Ping -Text $ping -Row $row
        Parse-IperfTcp -Text $iperfTcp -Row $row
        Parse-IperfUdp -Text $iperfUdp -Row $row
        if ($cableTest) {
            if ($cableTest.ToLower().Contains("not supported")) { $row["cable_test_status"] = "unsupported" }
            elseif ($cableTest.ToLower().Contains("open")) { $row["cable_test_status"] = "open" }
            elseif ($cableTest.ToLower().Contains("short")) { $row["cable_test_status"] = "short" }
            else { $row["cable_test_status"] = "done" }
        }

        foreach ($name in @("ip_addr", "carrier", "ethtool", "ping", "iperf_tcp", "iperf_udp", "cable_test")) {
            $rc = Get-SectionRc -Lines $lines -Name $name
            if ($rc -and $rc -ne "0") {
                $errors.Add("$name rc=$rc")
            }
        }

        $row["timestamp_end"] = Get-IsoNow
        $row["errors"] = ($errors -join "; ")
        Add-Row -Path $CsvPath -Row $row
        Add-Jsonl -Path $JsonlPath -Row $row

        Write-Host " link=$($row["link_detected"]) speed=$($row["speed_mbps"]) ping_loss=$($row["ping_loss_percent"]) errors=$($row["errors"])"
    }
}

Write-Host ""
Write-Host "Done. CSV saved to: $CsvPath" -ForegroundColor Green
