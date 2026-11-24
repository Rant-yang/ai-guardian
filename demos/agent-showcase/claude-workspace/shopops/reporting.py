import html
import json
import sqlite3
from pathlib import Path

_TEMPLATE_HEAD = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ShopOps 运营看板</title>
<style>
:root {
  --bg: #070b14;
  --panel: #101827;
  --panel-2: #162134;
  --line: #24324a;
  --text: #e8eefb;
  --muted: #93a4c0;
  --accent: #4cc9f0;
  --accent-2: #7cf5c4;
  --warn: #f6c177;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: radial-gradient(1200px 600px at 15% -10%, #14233d 0%, var(--bg) 55%);
  color: var(--text);
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  padding: 32px 24px 48px;
}
.wrap { max-width: 1080px; margin: 0 auto; }
.eyebrow {
  color: var(--accent);
  font-size: 12px;
  letter-spacing: .18em;
  text-transform: uppercase;
  margin: 0 0 10px;
}
h1 { font-size: clamp(26px, 4vw, 38px); margin: 0 0 8px; letter-spacing: -.02em; }
.sub { color: var(--muted); margin: 0 0 28px; font-size: 14px; }
.kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 28px;
}
.card {
  background: linear-gradient(180deg, var(--panel-2), var(--panel));
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 20px 22px;
  box-shadow: 0 18px 40px rgba(0, 0, 0, .28);
}
.card .label { color: var(--muted); font-size: 13px; margin-bottom: 10px; }
.card .value { font-size: 30px; font-weight: 650; letter-spacing: -.02em; }
.card .value .unit { font-size: 14px; font-weight: 500; color: var(--muted); margin-left: 6px; }
.card.revenue .value { color: var(--accent-2); }
.card.orders .value { color: var(--accent); }
.card.regions .value { color: var(--warn); }
.panel {
  background: linear-gradient(180deg, var(--panel-2), var(--panel));
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 22px;
  box-shadow: 0 18px 40px rgba(0, 0, 0, .28);
}
.panel-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 18px; }
.panel-head h2 { font-size: 17px; margin: 0; }
.panel-head span { color: var(--muted); font-size: 12px; }
.region { display: grid; grid-template-columns: 110px 1fr 56px; align-items: center; gap: 14px; padding: 10px 0; }
.region + .region { border-top: 1px solid rgba(36, 50, 74, .65); }
.region .name { font-size: 14px; color: var(--text); overflow-wrap: anywhere; }
.region .count { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
.track { height: 10px; border-radius: 999px; background: #0a111d; border: 1px solid var(--line); overflow: hidden; }
.bar { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #1d6fa5, var(--accent)); }
.empty { color: var(--muted); font-size: 14px; padding: 12px 0; }
footer { color: var(--muted); font-size: 12px; margin-top: 22px; line-height: 1.7; }
</style>
</head>
<body>
<div class="wrap">
<p class="eyebrow">Guardian Showcase · Synthetic Data</p>
<h1>ShopOps 运营看板</h1>
<p class="sub">有效订单质量与地区分布 · 数据源 data/orders.csv</p>
<div class="kpis">
'''

_TEMPLATE_FOOTER = '''<footer>
营业额仅统计 paid 状态订单；地区计数覆盖全部有效订单（paid / pending / refunded）。<br>
本页由 Python 标准库本地生成，无外部资源，所有数据均为合成数据。
</footer>
</div>
</body>
</html>
'''

def render_html(summary):
    """Return standalone UTF-8 HTML with escaped region names and paid revenue."""
    by_region = summary['by_region']
    region_total = len(by_region)
    peak = max(by_region.values(), default=0) or 1
    region_rows = ''.join(
        '<div class="region">'
        '<span class="name">{name}</span>'
        '<div class="track"><div class="bar" style="width:{width:.0f}%"></div></div>'
        '<span class="count">{count}</span>'
        '</div>'.format(
            name=html.escape(str(region)),
            width=count / peak * 100,
            count=html.escape(str(count)),
        )
        for region, count in sorted(by_region.items())
    )
    if not region_rows:
        region_rows = '<p class="empty">暂无地区数据</p>'

    kpis = '''<div class="card revenue">
<div class="label">已支付营业额</div>
<div class="value">{revenue:.2f}<span class="unit">CNY</span></div>
</div>
<div class="card orders">
<div class="label">有效订单</div>
<div class="value">{count}<span class="unit">单</span></div>
</div>
<div class="card regions">
<div class="label">覆盖地区</div>
<div class="value">{region_total}<span class="unit">个</span></div>
</div>
'''.format(revenue=summary['paid_revenue'], count=summary['count'], region_total=region_total)

    body = '''<div class="panel">
<div class="panel-head"><h2>地区有效订单</h2><span>合计 {count} 单</span></div>
{rows}
</div>
'''.format(count=summary['count'], rows=region_rows)

    return _TEMPLATE_HEAD + kpis + '</div>\n' + body + _TEMPLATE_FOOTER

def save_reports(summary, output_dir):
    """Create output_dir; write summary.json, dashboard.html and metrics.sqlite3.
    SQLite table region_counts(region TEXT PRIMARY KEY, count INTEGER).
    Re-running must replace counts, not duplicate rows. Return None.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    (output_dir / 'dashboard.html').write_text(render_html(summary), encoding='utf-8')

    connection = sqlite3.connect(output_dir / 'metrics.sqlite3')
    try:
        connection.execute(
            'CREATE TABLE IF NOT EXISTS region_counts (region TEXT PRIMARY KEY, count INTEGER)'
        )
        connection.execute('DELETE FROM region_counts')
        connection.executemany(
            'INSERT INTO region_counts (region, count) VALUES (?, ?)',
            sorted(summary['by_region'].items()),
        )
        connection.commit()
    finally:
        connection.close()
