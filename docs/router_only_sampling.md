# 不用飞腾派：电脑 + Cudy TR3000 路由器采样方案

## 结论

可以不用飞腾派，但数据能力分三档：

1. **电脑 + 路由器一根线**：最简单，只能采电脑网卡协商速率、是否连通、ping 延迟/丢包。适合先做粗分类数据集。
2. **两台电脑 + 路由器**：推荐。两台电脑都接路由器，其中一根线作为待测线，另一根固定用好线；可以跑 `iperf3`，数据更像真正网线测试。
3. **OpenWrt 路由器 + 电脑**：路由器自己跑 `iperf3 -s`，电脑一根线接路由器采样。效果好，但需要路由器能 SSH/装包；刷机有风险。

Cudy TR3000 官方规格是 1 个 2.5G RJ45 + 1 个千兆 RJ45，所以如果你用两台有线设备同时插它，吞吐很可能被千兆口限制。做故障分类够用；如果要证明 2.5G 能力，需要电脑网卡和被测链路都支持 2.5G。

## 方案 A：只有电脑 + 路由器

连接：

```text
电脑有线网口  <---- 待测网线 ---->  TR3000 路由器
```

这个方案不需要飞腾派，不需要第二台电脑。脚本会采：

- 电脑网卡状态
- 协商速率，例如 100 Mbps / 1 Gbps / 2.5 Gbps
- ping 路由器的延迟和丢包
- 原始网卡信息

运行：

```bash
python tools/pc_router_cable_dataset.py ^
  --router-ip 192.168.10.1 ^
  --adapter Ethernet ^
  --out data/raw/dataset_router ^
  --operator your_name ^
  --topology pc_router ^
  --samples-per-cable 5
```

`--adapter Ethernet` 要换成你电脑上的有线网卡名。Windows 可用下面命令查看：

```powershell
Get-NetAdapter
```

如果只是先跑起来，也可以不填 `--adapter`：

```bash
python tools/pc_router_cable_dataset.py --router-ip 192.168.10.1
```

## 方案 B：两台电脑 + 路由器

连接：

```text
电脑 A  <---- 待测网线 ---->  TR3000
电脑 B  <---- 固定好线 ---->  TR3000
```

电脑 B 运行：

```bash
iperf3 -s
```

电脑 A 运行：

```bash
python tools/pc_router_cable_dataset.py ^
  --router-ip 192.168.10.1 ^
  --adapter Ethernet ^
  --iperf-server 192.168.10.20 ^
  --out data/raw/dataset_router ^
  --operator your_name ^
  --topology pc_router_second_pc ^
  --samples-per-cable 5
```

其中 `192.168.10.20` 是电脑 B 的 IP。这个方案比单电脑强很多，因为能采 TCP/UDP 吞吐、UDP 抖动、UDP 丢包。

注意：电脑 B 那根线必须一直用同一根已知好线，否则你测到的是“两根线 + 路由器”的混合结果。

## 方案 C：TR3000 刷 OpenWrt 后当 iperf3 服务端

如果 TR3000 已经是 OpenWrt，并且能 SSH：

```bash
opkg update
opkg install iperf3
iperf3 -s
```

电脑运行：

```bash
python tools/pc_router_cable_dataset.py ^
  --router-ip 192.168.10.1 ^
  --adapter Ethernet ^
  --iperf-server 192.168.10.1 ^
  --out data/raw/dataset_router ^
  --operator your_name ^
  --topology pc_openwrt_router ^
  --samples-per-cable 5
```

不建议为了采样一开始就刷机。Cudy 官方提示 2025 年 11 月以后生产的部分 AX3000 机型换了新 Flash，旧 OpenWrt 中间固件/旧版本可能导致无法启动。确实要刷机时，先核对机器 SN 和官方/OpenWrt 对应版本。

## 输出

脚本会在电脑上生成：

```text
data/raw/dataset_router/
  samples.csv
  samples.jsonl
  raw/
    20260424_231500_PCNAME/
      20260424_231510_123_C001_r001/
        pc_netadapter.json
        pc_netadapter_statistics.json
        ping_router.txt
        iperf_tcp.json
        iperf_udp.json
```

主要看 `data/raw/dataset_router/samples.csv`。

## 我的建议

你现在先用 **方案 A** 跑 10 根线，确认采样流程顺手；然后如果能借到第二台电脑，就切到 **方案 B** 做正式数据集。飞腾派可以暂时不用，但后面如果要采“完全断路/严重短路”这类样本，飞腾派或其他独立探针仍然更稳。
