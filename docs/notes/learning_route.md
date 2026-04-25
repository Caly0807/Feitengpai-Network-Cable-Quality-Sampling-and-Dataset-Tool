# 学习路线与分工建议

## 你的定位

优先做软件测试与数据闭环负责人：让飞腾派能被稳定控制，网口状态能查，测速能自动执行，结果能保存，表格和报告能说明问题。

## 最小可交付目标

1. 飞腾派运行 Linux，网口能识别。
2. 一端运行 `iperf3 -s`，另一端一键运行 TCP/UDP/ping/ethtool 采样。
3. 每次采样自动生成 `samples.csv`、`samples.jsonl` 和原始命令输出。
4. 能说明每根线的吞吐、延迟、抖动、丢包、协商速率和错误计数是否异常。

## 4 周路线

### 第 1 周：Linux 和飞腾派能跑起来

会 SSH 登录、看 IP、看网口名、安装软件。

```bash
ip -br addr
ip route
ping -c 5 192.168.1.1
sudo apt update
sudo apt install -y iperf3 ethtool iproute2 iputils-ping openssh-server
```

### 第 2 周：网络测速工具链

会用 `iperf3`、`ping`、`ethtool` 判断链路质量。

```bash
iperf3 -s
iperf3 -c <server-ip> -t 10 -P 4 -J
iperf3 -c <server-ip> -u -b 100M -t 10 -J
ethtool eth0
ethtool -S eth0
```

### 第 3 周：自动化脚本和数据整理

目标是让队友只改采样清单就能跑完整测试。

```bash
python tools/pc_collect_cable_dataset.py --plan data/plans/sampling_plan_template.csv
```

### 第 4 周：展示、对比和项目汇报

把数据变成结论：

- 各线缆吞吐对比
- UDP 丢包率和抖动对比
- 协商速率、双工模式、错误计数变化
- 好线和坏线的复测记录

## 和硬件同学配合

硬件同学提供：

- 线缆编号、长度、类型、真实故障
- 拓扑和网口
- 如果有 TDR/频域采集，提供原始 CSV 和标签

你提供：

- 每根线的网络指标汇总
- 异常线缆复测记录
- 可训练的数据表和标签格式
