# 飞腾派网线质量采样与数据集工具

本项目面向电赛网络/网线测试场景，用电脑控制飞腾派采集以太网线缆样本。脚本会自动记录链路状态、协商速率、ping、iperf3、网卡错误计数和原始命令输出，方便后续做规则判断、模型训练或报告展示。

项目目标是把采样流程做成可交接、可复测、可上传 GitHub 的工程：

- 坏线、断线、短路也能采样，不依赖待测线作为控制通道
- 每根实体线有稳定编号和真实标签
- 汇总表和原始输出同时保存，便于后续重新解析
- 用 Python 脚本和 CSV 清单管理采样流程

---

## 1. 项目能力概览

- 电脑端通过 SSH 控制飞腾派执行采样命令
- 支持交互式采样、单根线采样、CSV 清单批量采样
- 采集 `ip`、`ethtool`、`ping`、`iperf3`、网卡统计计数
- 输出 `samples.csv`、`samples.jsonl` 和每次采样的 `raw/` 原始文件
- 支持 `good/open/short/cross/split_pair/poor/long/unknown` 标签体系
- 适合上传 GitHub 给队友共享脚本、清单和说明文档

---

## 2. 目录结构

### 2.1 顶层结构

```text
FTP/
├── data/
│   ├── plans/                    # 采样清单 CSV，建议提交到 GitHub
│   └── raw/                      # 本地采样输出，默认不提交
├── tools/                        # Python/PowerShell 采样脚本
├── docs/                         # 采样方案、拓扑、流程说明
│   └── notes/                    # 学习路线和分工建议
├── references/                   # 资料链接索引和少量关键本地 PDF
├── artifacts/                    # 后续模型、报告、部署产物
├── results/                      # 后续图表、分析结果、汇总报告
├── start_sampling.cmd            # Windows 一键采样入口
├── setup_ssh_key.cmd             # SSH 密钥配置辅助脚本
├── requirements.txt
└── README.md
```

### 2.2 代码文件说明

- `tools/pc_collect_cable_dataset.py`：主采样脚本，推荐使用。
- `tools/pc_collect_cable_dataset.ps1`：PowerShell 旧版采样脚本，保留作备用。
- `tools/collect_cable_dataset.py`：在飞腾派本机运行的采样脚本。
- `tools/pc_router_cable_dataset.py`：仅电脑侧接路由器的采样方案。
- `start_sampling.cmd`：Windows 下最方便的入口，内部调用 Python 主脚本。

### 2.3 数据和资料目录

- `data/plans/sampling_plan_template.csv`：采样清单模板，每一行是一根实体线。
- `data/raw/`：本地采样数据，默认被 `.gitignore` 忽略。
- `references/source_index.md`：飞腾派资料、RFC、TDR 论文等下载来源。
- `references/local_docs/`：已下载的飞腾派手册和电赛 D 题参考 PDF。
- `docs/sampling_decisions.md`：当前采样决策记录，回答标签、数量、坏线采样等问题。

---

## 3. 环境准备

### 3.1 电脑端

需要：

- Windows 电脑
- Python 3.10+
- OpenSSH 客户端，也就是命令行能运行 `ssh`
- 可选：`iperf3`，如果要让电脑作为吞吐测试服务端

安装 Python 时勾选：

```text
Add python.exe to PATH，也就是把 Python 加入环境变量
```

验证：

```bash
python --version
ssh -V
```

当前脚本核心部分只用 Python 标准库，通常不需要额外安装依赖。

### 3.2 飞腾派端

在飞腾派上安装工具：

```bash
sudo apt update
sudo apt install -y iperf3 ethtool iproute2 iputils-ping openssh-server
sudo systemctl enable --now ssh
```

查看待测网口名：

```bash
ip -br link
```

通常是 `eth0`，如果不是，修改脚本参数里的 `--iface`。

---

## 4. 硬件拓扑

最关键原则：SSH 控制通道不要走待测网线。

推荐拓扑：

```text
电脑  <-- Wi-Fi / USB 网卡 / 固定好线 SSH 控制 -->  飞腾派
飞腾派 eth0  <-- 待测网线 -->  路由器
```

这样坏线、断线、短路时，电脑仍然能控制飞腾派采集 `eth0` 的链路状态。

不推荐：

```text
电脑  <-- 待测网线，同时负责 SSH 和采样 -->  飞腾派
```

这种接法只能稳定采好线，坏线会直接让 SSH 断开。

---

## 5. 数据准备

### 5.1 给实体线编号

每根真实网线贴一个编号，例如：

```text
G001 正常线
O001 断路线
S001 短路线
P001 接触不良线
```

不要采完以后根据结果反推标签。`label` 和 `fault_type` 应该写真实情况。

### 5.2 编辑采样清单

打开：

```text
data/plans/sampling_plan_template.csv
```

每行是一根线：

```csv
cable_id,label,fault_type,category,length_m,notes,samples_per_cable,enabled
G001,good,good,Cat6,2,正常基准线,5,1
O001,open,open_unknown,Cat6,2,已知断路故障线,5,1
```

`enabled=0` 表示暂时跳过这一行。

---

## 6. 快速开始

### 6.1 修改一键脚本参数

打开 `start_sampling.cmd`，先改这几行：

```bat
set SSH_TARGET=user@192.168.137.10
set GATEWAY_IP=192.168.10.1
set IFACE=eth0
set OPERATOR=your_name
```

`SSH_TARGET` 必须是飞腾派控制通道 IP，不要填待测网线上的 IP。

### 6.2 一键采样

在项目根目录运行：

```bat
start_sampling.cmd
```

脚本会按 `data/plans/sampling_plan_template.csv` 逐行提示你换线。每换好一根线，按回车开始采样。

### 6.3 直接运行 Python

不用 cmd 时，可以运行：

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
  --samples-per-cable 5 ^
  --plan data/plans/sampling_plan_template.csv
```

---

## 7. 完整采样流程

1. 给每根线贴纸编号，写入采样清单。
2. 确认电脑能通过控制通道 SSH 到飞腾派。
3. 确认待测线只连接飞腾派 `eth0` 和路由器。
4. 修改 `start_sampling.cmd` 里的 `SSH_TARGET`、`GATEWAY_IP`、`OPERATOR`。
5. 运行 `start_sampling.cmd`。
6. 按提示接入第一根线，按回车采样。
7. 每根线默认采 5 次，完成后按提示换下一根。
8. 采完后查看 `data/raw/dataset_pc_pi_router/samples.csv`。
9. 不要删除 `raw/` 原始输出，后续字段不够时可以重新解析。

---

## 8. 推荐采样数量

- 最小可用版：每类 5 根实体线，每根采 5 次。
- 比赛展示版：每类 10 根实体线，每根采 5 次。
- 稳一点的训练版：正常线 20 根以上，主要故障类每类 10 到 20 根，每根 5 到 10 次。

材料有限时，优先保证：

- `good`
- `open`
- `short`
- `poor`

重复采样能看稳定性，但不能替代不同实体线。

---

## 9. 输出文件说明

采样结果默认写入：

```text
data/raw/dataset_pc_pi_router/
├── samples.csv       # 表格汇总，最方便查看
├── samples.jsonl     # 后续 Python 分析更稳
└── raw/              # 每次采样的原始输出
```

重点字段：

- `cable_id`：实体线编号
- `label`：粗标签，例如 `good/open/short`
- `fault_type`：细标签，例如 `open_pin_1`
- `link_detected`：是否上链路
- `speed_mbps`：协商速率
- `ping_loss_percent`：ping 丢包率
- `rx_errors_delta` / `rx_crc_errors_delta`：错误计数变化
- `errors`：脚本执行中遇到的异常

---

## 10. 上传 GitHub 建议

建议提交：

- `README.md`
- `tools/`
- `docs/`
- `data/plans/`
- `references/source_index.md`
- `start_sampling.cmd`
- `.gitignore`
- `requirements.txt`

默认不提交：

- `data/raw/` 的完整采样输出
- 大体积 PDF、zip、图片、原理图、PCB 文件
- 本地缓存和日志

例外：`references/local_docs/` 下少量关键 PDF 可以保留，用于队友查阅。

---

## 11. 常见问题

### Q1: 为什么坏线一接上就采不了？

大概率是 SSH 控制通道走了待测线。把 SSH 改到 Wi-Fi、USB 网卡或另一条固定好线上。

### Q2: `start_sampling.cmd` 提示找不到 Python 怎么办？

安装 Python 3，并勾选 `Add python.exe to PATH`，也就是把 Python 加入环境变量。安装后重新打开命令行，再运行：

```bash
python --version
```

### Q3: 路由器不能跑 `iperf3` 怎么办？

可以先用 `--skip-iperf --skip-udp`，只采链路状态和 ping。坏线识别第一版通常已经够用。

### Q4: 原始数据能不能删？

不要删。`samples.csv` 是汇总表，`raw/` 是以后重新解析和排查问题的依据。

### Q5: 采样清单里写错了怎么办？

没开始采样前直接改 CSV。已经采完的数据不要覆盖，建议新增一行复测，比如 `G001_ret1` 或在 `notes` 里写明复测原因。
