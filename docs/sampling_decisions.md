# 采样决策记录

这份文档回答当前采样阶段的几个关键问题，后续交接或上传 GitHub 时可以直接作为说明。

## 1. 为什么现在只能跑好线，跑不了坏线

原因通常不是脚本问题，而是控制通道问题：如果电脑 SSH 飞腾派也走待测网线，那么坏线一插上，SSH 就断了，脚本拿不到飞腾派侧的 `eth0` 状态。

正确拓扑是：

```text
电脑  <-- Wi-Fi / USB 网卡 / 另一条固定好线 SSH 控制 -->  飞腾派
飞腾派 eth0  <-- 待测网线 -->  路由器或电脑有线网口
```

坏线样本本来就可能表现为 `carrier=0`、`link_detected=no`、`ping_loss_percent=100`，这些都是有效数据，不要删。

## 2. 现在这几种标签够不够

第一版够用，建议先固定这些主标签：

- `good`：正常线
- `open`：断路
- `short`：短路
- `cross`：线序交叉
- `split_pair`：绞对错误
- `poor`：接触不良或压接不稳定
- `long`：过长或衰减明显
- `unknown`：暂时不确定，尽量少用

如果能知道具体故障脚位，把 `fault_type` 写细，比如 `open_pin_1`、`short_pin_1_2`。模型训练时可以先用粗标签 `label`，展示和分析时再看细标签 `fault_type`。

## 3. 采样后要不要保留原线并标记

要保留。每根实体线贴一个稳定编号，例如：

```text
G001 正常线
O001 断路线
S001 短路线
P001 接触不良线
```

编号写入 `cable_id`，真实情况写入 `label` 和 `fault_type`。采样后不要根据测试结果反过来改标签，因为训练数据需要的是“真实标签”，不是脚本猜测结果。

## 4. 不同的线采多少合适

先按实体线数量算，不要只按重复次数算。推荐：

- 最小可用版：每类 5 根实体线，每根采 5 次。
- 比赛展示版：每类 10 根实体线，每根采 5 次。
- 稳一点的训练版：正常线 20 根以上，主要故障类每类 10 到 20 根，每根 5 到 10 次。

如果材料有限，优先保证 `good/open/short/poor`，因为这几类最容易展示出差异。重复采样能看稳定性，但不能替代不同实体线。

## 5. Python 脚本采样方式

主脚本使用：

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

`--ssh-target` 必须填飞腾派的控制通道 IP，不要填待测网线上的 IP。`data/plans/sampling_plan_template.csv` 是采样清单，每一行是一根实体线；脚本会按清单提示你换线并采样。

Windows 上也可以直接双击或运行 `start_sampling.cmd`。如果提示找不到 Python，先安装 Python 3，并勾选 Add python.exe to PATH。

输出保留三份：

- `samples.csv`：表格汇总，最方便看。
- `samples.jsonl`：后续 Python 分析更稳。
- `raw/`：每次命令的原始输出，后面字段不够时可以重新解析。
