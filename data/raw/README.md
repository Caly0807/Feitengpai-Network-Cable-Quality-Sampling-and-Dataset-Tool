# 原始采样输出

`start_sampling.cmd` 默认把本地采样结果写到这里：

```text
data/raw/dataset_pc_pi_router/
  samples.csv
  samples.jsonl
  raw/
```

这个目录默认被 git 忽略，避免把本地临时采样、失败采样或大文件直接传到 GitHub。后面如果要给队友演示，可以只挑一小份样例数据单独整理后再上传。
