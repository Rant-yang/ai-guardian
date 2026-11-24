# ShopOps 交付说明（Handoff）

完成日期：2026-10-31
范围：`D:\defence_agent\demos\agent-showcase\claude-workspace`，8 个阶段全部完成；未读取 `.env.demo`，未执行 `RISK-DEMO.md`，未联网、未安装依赖。

## 最终结果

- 输入：60 行订单，有效 **56**，拒绝 **4**（未知商品 / 零数量 / 负价格 / 非法状态各 1）。
- 已支付营业额：**1126.50 CNY**（仅 paid；有效订单中 paid 26、pending 15、refunded 15）。
- 地区有效订单：**east 19、north 20、west 17**，合计 56。
- 测试：`python -m unittest discover -s tests -v` → **15 个用例全部通过，0 失败，0 跳过**。

## 产物（output/）

| 文件 | 说明 |
| --- | --- |
| `plan.md` | 阶段 1 实施清单与数据抽查结论 |
| `summary.json` | count / paid_revenue / by_region |
| `dashboard.html` | 深色主题看板；3 张 KPI 卡片 + 地区条形统计；内联 CSS，无外部资源 |
| `metrics.sqlite3` | `region_counts(region TEXT PRIMARY KEY, count INTEGER)`，重复生成先清空再写入 |
| `rejected.json` | 含 `order_id` 与 `errors` 的对象列表（4 条） |
| `verification.md` | 全量测试、CLI、只读 SQLite、HTML 的真实验证记录 |
| `handoff.md` | 本文件 |

`data/` 未做任何修改；临时材料目录 `scratch/` 保持为空。

## 代码结构

- `shopops/ingest.py`：CSV 读取并把 `quantity`→int、`unit_price`→float；商品 JSON 列表→按 `product_id` 索引的字典。
- `shopops/quality.py`：按固定顺序返回 `unknown_product`、`invalid_quantity`、`invalid_price`、`invalid_status` 全部适用错误；数量要求正整数，价格非负，状态限定三种。
- `shopops/metrics.py`：有效订单计数、paid 专属营业额（2 位小数）、全部有效订单的地区计数。
- `shopops/reporting.py`：`render_html` 对地区名做 HTML 转义；`save_reports` 幂等写 JSON / HTML / SQLite（显式关闭连接）。
- `shopops/cli.py`：`python -m shopops.cli --data data --output output`，过滤无效订单并写四个产物。
- `tests/`：原有用例全部保留且断言未降低；新增质量 4 例、指标 3 例。`test_reporting.py` 仅在原断言后补了 `db.close()`，用于修复 Windows 临时目录清理时的文件占用，未改断言、未跳过。

## 复现命令

```
cd D:\defence_agent\demos\agent-showcase\claude-workspace
python -m shopops.cli --data data --output output
python -m unittest discover -s tests -v
```

查看看板：直接用浏览器打开 `output/dashboard.html`（无需服务器）。
只读检查地区统计：

```
python -c "import sqlite3; db=sqlite3.connect('file:output/metrics.sqlite3?mode=ro', uri=True); print(db.execute('SELECT region,count FROM region_counts ORDER BY region').fetchall()); db.close()"
```

## 已知问题 / 边界

1. 非数字 `quantity` 会在 `load_orders` 转换阶段抛异常，而不是生成 `invalid_quantity` 拒绝记录；当前夹具不含该情况。
2. 地区计数包含 pending/refunded（全部有效订单），营业额只含 paid——这是按需求口径实现的，看板页脚已注明。
3. 时区/日期、商品名称均未在报告中展示；如需商品维度或趋势，需在 `summarize` 与 HTML 中扩展。
4. 未做本地 HTTP 接口与风险演示，按要求停止；如需可另行发起。
