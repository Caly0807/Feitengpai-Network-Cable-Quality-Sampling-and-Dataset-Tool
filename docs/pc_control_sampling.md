# 电脑控制飞腾派的网线数据集采样

## 你的当前拓扑

```text
电脑网口  <---- 待测网线 ---->  飞腾派 eth0
```

主要操作在电脑上时，推荐用电脑做控制台和 `iperf3` 服务端，飞腾派做采样探针。电脑端脚本是：

```text
tools/pc_collect_cable_dataset.py
```

## 最推荐的控制方式

如果条件允许，让 SSH 控制通道不要走待测网线：

```text
电脑 Wi-Fi/USB网卡/局域网  <---- SSH 控制 ---->  飞腾派
电脑有线网口              <---- 待测网线 ---->  飞腾派 eth0
```

这样即使待测网线是断线、短路、接触不良，电脑仍然能控制飞腾派采集 `eth0` 的链路状态。否则如果 SSH 也走待测线，坏线会导致 SSH 直接断，脚本只能记录 `ssh failed`，拿不到飞腾派侧的完整指标。

## IP 建议

直连时可以固定成：

```text
电脑有线网口：192.168.10.2/24
飞腾派 eth0：192.168.10.3/24
```

飞腾派临时配置：

```bash
sudo ip addr flush dev eth0
sudo ip addr add 192.168.10.3/24 dev eth0
sudo ip link set eth0 up
```

电脑端把有线网卡 IPv4 手动设为：

```text
IP: 192.168.10.2
Mask: 255.255.255.0
Gateway: 留空
DNS: 留空
```

## 飞腾派准备

在飞腾派上安装工具：

```bash
sudo apt update
sudo apt install -y iperf3 ethtool iproute2 iputils-ping openssh-server
sudo systemctl enable --now ssh
```

在电脑上先确认能 SSH：

```bash
ssh user@192.168.10.3
```

如果你能配 SSH 密钥，采样会顺很多；否则每次 SSH 调用都可能要求输入密码。

## 电脑准备

电脑需要：

- Python 3
- OpenSSH 客户端，也就是能运行 `ssh`
- `iperf3`，如果要让脚本自动启动服务端，需要把 `iperf3` 放进 PATH

也可以手动在电脑开一个终端运行：

```bash
iperf3 -s
```

## 电脑端交互式采样

在电脑项目目录运行：

```bash
python tools/pc_collect_cable_dataset.py \
  --ssh-target user@192.168.10.3 \
  --pc-ip 192.168.10.2 \
  --iface eth0 \
  --out data/raw/dataset_pc \
  --operator your_name \
  --topology pc_direct \
  --start-iperf-server \
  --samples-per-cable 5
```

如果你已经手动运行了 `iperf3 -s`，可以去掉 `--start-iperf-server`。

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

采完一根线后继续输入下一根线编号。`Cable ID` 直接回车就结束。

## 单根线复测

```bash
python tools/pc_collect_cable_dataset.py \
  --ssh-target user@192.168.10.3 \
  --pc-ip 192.168.10.2 \
  --iface eth0 \
  --out data/raw/dataset_pc \
  --cable-id C001 \
  --label good \
  --fault-type good \
  --category Cat6 \
  --length-m 2 \
  --samples-per-cable 5
```

## 输出

数据会保存在电脑上：

```text
data/raw/dataset_pc/
  samples.csv
  samples.jsonl
  raw/
    20260424_223000_PCNAME/
      20260424_223010_123_C001_r001/
        remote_script.sh
        ssh_stdout.txt
        ssh_stderr.txt
        ethtool.txt
        ping.txt
        iperf_tcp.txt
        iperf_udp.txt
```

主要分析 `data/raw/dataset_pc/samples.csv`。`raw/` 里保留了每次命令原始输出，方便后期重新解析。

## 采样提醒

- 每根实体线贴一个稳定编号，例如 `C001`。
- 每根线先采 5 次，重点类别补到 10 次。
- 坏线导致 SSH 失败也不要删，失败本身就是一条可追溯记录。
- 如果要采“完全断线/严重短路”这类样本，务必让 SSH 走 Wi-Fi、USB 网卡或其他控制通道。
- 同一次数据集里尽量固定电脑、飞腾派、网口、IP、拓扑，不要边采边换环境。
