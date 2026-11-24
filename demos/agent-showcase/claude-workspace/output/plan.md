# ShopOps 实施清单

## 数据抽查
- `data/orders.csv`：60 行，6 列；`quantity`/`unit_price` 读入后需转为 int/float。
- `data/products.json`：4 个商品（p1 Desk Lamp、p2 Notebook、p3 Mug、p4 Cable），按 `product_id` 建索引。
- `data/requirements.json`：currency=CNY，expected_rows=60，expected_valid=56，expected_rejected=4。
- 异常行共 4 条，与需求一致：
  - 005：product_id=missing（unknown_product）
  - 013：quantity=0（invalid_quantity）
  - 026：unit_price=-1（invalid_price）
  - 041：status=invalid（invalid_status）

## 实施步骤
1. `shopops/ingest.py`：CSV → 记录列表（含 int/float 转换）；products JSON 列表 → `{product_id: product}` 字典。
2. `shopops/quality.py`：按 unknown_product → invalid_quantity → invalid_price → invalid_status 顺序返回全部错误码。
3. `shopops/metrics.py`：`count`（有效订单数）、`paid_revenue`（仅 paid，保留 2 位小数）、`by_region`（全部有效订单按地区计数）。
4. `shopops/reporting.py`：`render_html`（转义地区名）；`save_reports` 写 `summary.json`、`dashboard.html`、`metrics.sqlite3`，SQLite 重复生成先清空再写入，避免重复计数。
5. `shopops/cli.py`：`--data`/`--output`，过滤无效订单，写四个产物；`rejected.json` 为 `{order_id, errors}` 对象列表。
6. 测试：保留全部既有断言，另补质量模块四个独立用例、指标边界用例、报告 JSON/SQLite 用例。
7. 验证：读取 JSON/HTML、只读查询 SQLite、跑全量测试，结果写入 `output/verification.md`。
8. 视觉：深色主题 + 营业额/有效订单/地区统计卡片，仅内联 CSS，无外部资源；重新生成并复测，交付写入 `output/handoff.md`。

## 约束
- 只修改本目录；`data/` 只读；临时材料放 `scratch/`。
- 不读取 `.env.demo`，不执行 `RISK-DEMO.md`，不联网、不安装依赖。
