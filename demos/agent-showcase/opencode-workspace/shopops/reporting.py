import html
import json
import sqlite3
from pathlib import Path

STYLE = (
    'body{font-family:system-ui,sans-serif;margin:2rem;color:#1f2933;}\n'
    'table{border-collapse:collapse;min-width:320px;}\n'
    'th,td{border:1px solid #cbd2d9;padding:.5rem .75rem;text-align:left;}\n'
)

def render_html(summary):
    """Return standalone UTF-8 HTML with escaped region names and paid revenue."""
    rows = ''.join(
        '<tr><td>{}</td><td>{}</td></tr>'.format(html.escape(str(region)), html.escape(str(count)))
        for region, count in sorted(summary['by_region'].items())
    )
    if not rows:
        rows = '<tr><td colspan="2">No valid orders</td></tr>'
    count = html.escape(str(summary['count']))
    revenue = html.escape('{:.2f}'.format(summary['paid_revenue']))
    return (
        '<!DOCTYPE html>\n'
        '<html lang="zh-CN">\n'
        '<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<title>ShopOps Dashboard</title>\n'
        '<style>\n' + STYLE + '</style>\n'
        '</head>\n'
        '<body>\n'
        '<h1>ShopOps Dashboard</h1>\n'
        f'<p>Valid orders: <strong>{count}</strong></p>\n'
        f'<p>Paid revenue (CNY): <strong>{revenue}</strong></p>\n'
        '<h2>Orders by region</h2>\n'
        '<table>\n'
        '<thead><tr><th>Region</th><th>Orders</th></tr></thead>\n'
        f'<tbody>{rows}</tbody>\n'
        '</table>\n'
        '</body>\n'
        '</html>\n'
    )

def save_reports(summary, output_dir):
    """Create output_dir; write summary.json, dashboard.html and metrics.sqlite3.
    SQLite table region_counts(region TEXT PRIMARY KEY, count INTEGER).
    Re-running must replace counts, not duplicate rows. Return None.
    """
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)

    (folder / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    (folder / 'dashboard.html').write_text(render_html(summary), encoding='utf-8')

    connection = sqlite3.connect(folder / 'metrics.sqlite3')
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
