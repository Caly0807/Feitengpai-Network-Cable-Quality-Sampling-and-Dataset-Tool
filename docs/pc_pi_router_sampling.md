# 最终采样方案：电脑控制飞腾派，飞腾派测试网线到路由器

## 目标

你要实现两件事：

1. 电脑控制飞腾派采样。
2. 飞腾派通过待测网线测试网线质量。

推荐拓扑：

```text
电脑  <-- 控制通道：USB网卡 / Wi-Fi / 串口转SSH -->  飞腾派 eth0  <-- 待测网线 -->  路由器
```

关键点：**控制通道不要走待测网线**。待测网线只负责连接“飞腾派 eth0 到路由器”，这样坏线、断线、短路时，电脑仍然能控制飞腾派并保存数据。

当前脚本默认通过 **SSH** 控制飞腾派。如果你现在手里是纯串口 COM 口，建议先把飞腾派配置成 Wi-Fi SSH 或 USB 网卡 SSH；纯串口自动化也能做，但命令回显和交互解析会麻烦一些，不适合作为第一版采样主线。

## 设备角色

- 电脑：运行采样脚本，控制飞腾派，保存 `CSV/JSONL/raw` 数据。
- 飞腾派：运行 `ip/ethtool/ping/iperf3`，采集待测网口状态和网络性能。
- 路由器：提供网关 IP，例如 `192.168.10.1`；如果支持，也可以运行 `iperf3 -s`。

## 飞腾派准备

```bash
sudo apt update
sudo apt install -y iperf3 ethtool iproute2 iputils-ping openssh-server
sudo systemctl enable --now ssh
```

飞腾派待测网口接路由器，确认网口名：

```bash
ip -br link
```

一般是 `eth0`，如果不是，后面命令里的 `--iface eth0` 要改掉。

## 控制通道

电脑需要能 SSH 到飞腾派，例如：

```bash
ssh user@192.168.137.10
```

这个 IP 可以来自：

- 飞腾派 Wi-Fi
- USB 共享网络
- 另一张 USB 网卡
- 路由器 Wi-Fi

不建议用待测的 `eth0` 作为 SSH 控制通道。

## 路由器准备

确认路由器网关 IP，例如：

```text
192.168.10.1
```

先保证飞腾派能通过待测网线拿到 IP，或者手动配置同网段 IP：

```bash
sudo ip addr flush dev eth0
sudo ip addr add 192.168.10.50/24 dev eth0
sudo ip link set eth0 up
```

如果路由器能跑 `iperf3 -s`，就启动它；如果不能，也没关系，先只采链路状态和 ping。

## 电脑端采样命令

只采物理状态 + ping 路由器：

```bash
python tools/pc_collect_cable_dataset.py ^
  --ssh-target user@192.168.137.10 ^
  --gateway-ip 192.168.10.1 ^
  --iface eth0 ^
  --out data/raw/dataset_pc_pi_router ^
  --operator your_name ^
  --topology pi_router_gateway ^
  --skip-iperf ^
  --skip-udp ^
  --samples-per-cable 5
```

如果路由器已经运行 `iperf3 -s`，用这一条：

```bash
python tools/pc_collect_cable_dataset.py ^
  --ssh-target user@192.168.137.10 ^
  --gateway-ip 192.168.10.1 ^
  --iperf-server 192.168.10.1 ^
  --iface eth0 ^
  --out data/raw/dataset_pc_pi_router ^
  --operator your_name ^
  --topology pi_router_gateway ^
  --samples-per-cable 5
```

如果路由器不能跑 `iperf3`，但你想测吞吐，可以让电脑跑 `iperf3 -s`，前提是飞腾派能从待测网口所在网络访问电脑 IP：

```bash
python tools/pc_collect_cable_dataset.py ^
  --ssh-target user@192.168.137.10 ^
  --gateway-ip 192.168.10.1 ^
  --pc-ip 192.168.10.2 ^
  --start-iperf-server ^
  --iface eth0 ^
  --out data/raw/dataset_pc_pi_router ^
  --operator your_name ^
  --topology pi_router_pc_iperf ^
  --samples-per-cable 5
```

## 采样时输入

脚本会提示：

```text
Cable ID: C001
Label: good
Fault type: good
Category: Cat6
Length in meters: 2
Notes:
Connect this cable, then press Enter to start sampling...
```

建议标签：

- `good`
- `open`
- `short`
- `cross`
- `split_pair`
- `poor`
- `long`
- `unknown`

如果硬件同学知道具体故障，可以把 `fault_type` 写细，例如 `open_pin_1`、`short_pin_1_2`。

## 输出

数据保存在电脑：

```text
data/raw/dataset_pc_pi_router/
  samples.csv
  samples.jsonl
  raw/
    每次采样的 ssh 输出、ethtool、ping、iperf3 原始结果
```

主要看 `samples.csv`。原始数据不要删，后面要重新解析字段时很有用。

## 重要注意

- 一次只换一根待测网线。
- 路由器端口速度会限制结果：千兆口最高约 1Gbps，2.5G 口最高约 2.5Gbps。
- `iperf3` 服务端在哪里，`--iperf-server` 就填哪里。
- 路由器不能跑 `iperf3` 时，不影响你采链路状态和 ping 数据。
- 完全断线也是有效样本，不要删除。
