# 网线测试仪数据集采样说明

## 采样目标

先做一个可重复的数据集，不急着上复杂模型。每条样本至少要能追溯到：

- 哪一根线：`cable_id`
- 真实标签：`label` / `fault_type`
- 测试环境：飞腾派网口、服务端 IP、拓扑
- 链路结果：是否上链路、协商速率、双工、自协商
- 传输质量：ping 延迟/丢包、TCP 吞吐、UDP 抖动/丢包、网卡错误计数

## 推荐标签

给每根实体网线贴纸编号，例如 `C001`、`C002`。标签建议这样分层：

- `label=good`：正常线
- `label=open`，`fault_type=open_pin_1`：某芯断路
- `label=short`，`fault_type=short_pin_1_2`：短路
- `label=cross`：线序交叉
- `label=split_pair`：绞对错误
- `label=poor`：接触不良、压接不稳定
- `label=long`：超长或衰减明显
- `label=unknown`：暂时不确定

如果你们的硬件同学能确认具体故障脚位，优先把 `fault_type` 写细；以后训练/分析会更有用。

## 推荐采样数量

- 每类至少 10 根不同实体线。
- 每根线先采 5 次，比赛/论文展示前再把重点类别补到每根 10 次。
- 正常线要多准备一点，作为基准和抗误判样本。
- 每采 10 根线，插一根已知正常线复测一次，防止环境漂移。
- 同一根线不要连续只采一次就换线，至少重复 5 次，脚本默认就是 5 次。

## 硬件拓扑

推荐先用两端直连，变量最少：

```text
飞腾派 eth0  <---- 待测网线 ---->  电脑/另一块板子
```

另一端运行 `iperf3 -s`。如果必须经过交换机，也可以，但 `topology` 要写成 `switch`，不要和直连数据混在一起比较。

如果你的主要操作都在电脑上，优先看 `docs/pc_control_sampling.md`，用电脑端脚本统一控制飞腾派采样。

## 飞腾派准备

安装依赖：

```bash
sudo apt update
sudo apt install -y python3 iperf3 ethtool iproute2 iputils-ping
```

查看网口名：

```bash
ip -br link
```

电脑或另一块板子作为服务端：

```bash
iperf3 -s
```

确认服务端 IP，例如 `192.168.10.2`。

## 交互式批量采样

在飞腾派上进入项目目录，运行：

```bash
python3 tools/collect_cable_dataset.py \
  --server 192.168.10.2 \
  --iface eth0 \
  --out data/raw/dataset_pi \
  --operator your_name \
  --topology direct \
  --samples-per-cable 5
```

之后按提示输入：

```text
Cable ID: C001
Label: good
Fault type: good
Category: Cat6
Length in meters: 2
Notes:
Connect this cable, then press Enter to start sampling...
```

采完一根线后脚本会继续问下一根线。`Cable ID` 直接回车即可结束。

## 单根线非交互采样

适合脚本化或复测：

```bash
python3 tools/collect_cable_dataset.py \
  --server 192.168.10.2 \
  --iface eth0 \
  --out data/raw/dataset_pi \
  --cable-id C001 \
  --label good \
  --fault-type good \
  --category Cat6 \
  --length-m 2 \
  --samples-per-cable 5
```

## 只采链路状态

如果另一端暂时没有 `iperf3` 服务端，可以不传 `--server`，脚本会只记录链路、协商速率、网卡状态：

```bash
python3 tools/collect_cable_dataset.py --iface eth0 --out data/raw/dataset_pi
```

这种数据能用于区分“能否上链路/协商速率是否异常”，但不能反映吞吐、抖动和丢包。

## 可选：驱动线缆诊断

如果网卡驱动支持，可以加：

```bash
sudo python3 tools/collect_cable_dataset.py \
  --server 192.168.10.2 \
  --iface eth0 \
  --run-cable-test
```

注意：`ethtool --cable-test` 可能需要 root，也可能被网卡驱动标记为不支持；它还可能短暂影响链路，所以默认关闭。

## 输出文件

脚本会生成：

```text
dataset/
  samples.csv
  samples.jsonl
  raw/
    20260424_153000_hostname/
      20260424_153005_123_C001_r001/
        ip_addr.json
        ethtool.txt
        ethtool_stats.txt
        ping.txt
        iperf_tcp.json
        iperf_udp.json
```

主要看 `dataset/samples.csv`。原始命令输出都保存在 `raw/`，后面发现解析字段不够时还能重新解析。

## 采样纪律

- 每次只改变一根网线，不要同时换网口、交换机、服务端。
- 插线后等 2 秒再采，脚本默认 `--stabilize 2`。
- 坏线不上链路也是有效样本，不要删掉。
- 采样时记录真实标签，不要用测试结果反推标签。
- 同类样本尽量均衡，否则模型容易只会判断多数类。
