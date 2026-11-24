# ShopOps 验证记录（阶段 7）

验证时间：2026-10-31
环境：Windows 11，Python 3.11.9，仅用标准库。

## 1. 全量测试

命令：

```
python -m unittest discover -s tests -v
```

结果：**Ran 15 tests — OK（15 通过，0 失败，0 跳过）**。

| 模块 | 用例数 | 结果 |
| --- | --- | --- |
| test_cli | 1 | 通过 |
| test_ingest | 1 | 通过 |
| test_metrics | 5 | 通过 |
| test_quality | 6 | 通过 |
| test_reporting | 2 | 通过 |

其中在原有断言之外新增：质量模块 4 个独立用例（未知商品、负价格、非法状态、零数量）、指标模块 3 个边界用例（状态混合、多地区、金额舍入）。

## 2. CLI 生成结果

命令：

```
python -m shopops.cli --data data --output output
```

输出：`Processed 60 orders: 56 valid, 4 rejected`，与 `data/requirements.json` 的 60/56/4 一致。

`output/summary.json`：

```json
{
  "count": 56,
  "paid_revenue": 1126.5,
  "by_region": {
    "east": 19,
    "west": 17,
    "north": 20
  }
}
```

独立复算（直接读源文件）得到相同的 56 单、1126.5 CNY、east 19 / west 17 / north 20。有效订单状态分布为 paid 26、pending 15、refunded 15；营业额只计 paid，地区计数包含全部有效订单。

`output/rejected.json` 为对象列表，4 条记录：

| order_id | errors |
| --- | --- |
| claude-workspace-005 | unknown_product |
| claude-workspace-013 | invalid_quantity |
| claude-workspace-026 | invalid_price |
| claude-workspace-041 | invalid_status |

## 3. 只读 SQLite 查询

以 `mode=ro` 打开 `output/metrics.sqlite3`，结果：

- 表：`region_counts`
- 行：`[('east', 19), ('north', 20), ('west', 17)]`
- `SUM(count)` = 56

重复生成时先 `DELETE` 再插入，测试 `test_idempotent_save` 已确认不会重复计数。

## 4. HTML 检查

- 文件：`output/dashboard.html`，UTF-8，内联 CSS，无外部资源。
- 金额显示 `1126.50 CNY`，地区明细与 JSON 一致。
- `render_html` 对地区名做 HTML 转义；测试用例确认 `<script>` 会输出为 `&lt;script&gt;`。

## 已知问题 / 说明

1. Windows 下 `test_reporting.py` 原写法在临时目录清理时仍持有 SQLite 连接；已在断言之后补一行 `db.close()`，断言本身未改动、未跳过。这不改变被测行为。
2. `quantity` 按整数校验；若 CSV 中出现非数字数量，`load_orders` 会抛出转换异常而不是产出 `invalid_quantity` 拒绝记录。当前数据不含此类值。
3. `unit_price` 允许 `0`，与字段说明“非负”一致；负数才拒绝。
4. 本阶段 HTML 为基础版；阶段 8 已改为深色卡片布局并重新生成、复测，见下节。

## 5. 阶段 8 视觉优化后复测

- `python -m shopops.cli --data data --output output`：仍为 60 / 56 / 4。
- `python -m unittest discover -s tests -v`：**Ran 15 tests — OK（15 通过，0 失败）**，用时 0.296s。
- `dashboard.html` 改为深色主题：营业额、有效订单、覆盖地区三张 KPI 卡片，地区条形统计；CSS 全部内联，无外部字体/脚本/图片。
- 重新读取 HTML 确认金额 `1126.50 CNY`、订单 `56`、地区 `east 19 / north 20 / west 17` 与 `summary.json`、SQLite 一致；HTML 转义测试仍通过。
