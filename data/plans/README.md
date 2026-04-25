# 采样清单

CSV 里每一行对应一根实体网线。建议给真实网线贴纸编号，编号要和 `cable_id` 保持一致。

固定列名：

```csv
cable_id,label,fault_type,category,length_m,notes,samples_per_cable,enabled
```

`enabled=0` 表示暂时跳过这一根线，不用把它从清单里删掉。
