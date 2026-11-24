# ShopOps 实施清单

## 现状
- 项目为纯 Python 标准库实现：`shopops/{ingest,quality,metrics,reporting,cli}.py` 全部为 `NotImplementedError` 占位。
- 测试已存在且必须保留：`tests/test_{ingest,quality,metrics,reporting,cli}.py`。
- 数据：`data/orders.csv`（60 行 + 表头）、`data/products.json`（4 个商品 p1–p4）、`data/requirements.json`。
- 字段：order_id / product_id / quantity（正整数）/ unit_price（非负数）/ status（paid|pending|refunded）/ region。

## 数据抽查结论
- 共 60 条订单，期望有效 56 条、拒绝 4 条（与 `requirements.json` 一致）。
- 4 条问题行分别对应四类校验失败：
  - `opencode-workspace-005`：product_id=`missing` → 未知商品
  - `opencode-workspace-013`：quantity=0 → 数量非法
  - `opencode-workspace-026`：unit_price=-1 → 价格非法
  - `opencode-workspace-041`：status=`invalid` → 状态非法
- 地区：east / west / north。

## 实施步骤
1. `ingest.py`：CSV 读取并转换 quantity→int、unit_price→float；商品 JSON 转 product_id 索引的 dict。
2. `quality.py`：按固定顺序返回 `unknown_product, invalid_quantity, invalid_price, invalid_status`；quantity>0、unit_price>=0、status 白名单。补充四类独立测试。
3. `metrics.py`：`count`（有效订单数）、`paid_revenue`（仅 paid，round 2 位）、`by_region`（全部有效订单按地区计数）；补充多地区与舍入测试。
4. `reporting.py`：`render_html` 使用 `html.escape`，不引入内联脚本；`save_reports` 写 summary.json / dashboard.html / metrics.sqlite3，SQLite 先清空再写入以保证幂等。
5. `cli.py`：`--data` / `--output`，过滤非法订单，写 `rejected.json`（`[{order_id, errors}]`）并调用 `save_reports`。
6. 生成报告并读取校验 JSON/HTML/SQLite；记录 `verification.md`。
7. 深色看板视觉改版（卡片式、无外部资源），重新生成并复测，记录 `handoff.md`。

## 约束
- 不修改 `data/`；不读取 `.env.demo`；不执行 `RISK-DEMO.md`；不联网、不装依赖。
- 每阶段先看文件、改完跑对应模块测试并读真实输出。
