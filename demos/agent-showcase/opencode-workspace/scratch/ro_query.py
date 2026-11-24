import sqlite3
uri = 'file:D:/defence_agent/demos/agent-showcase/opencode-workspace/output/metrics.sqlite3?mode=ro'
conn = sqlite3.connect(uri, uri=True)
try:
    for row in conn.execute('SELECT region, count FROM region_counts ORDER BY region'):
        print(row)
    print('total', conn.execute('SELECT SUM(count) FROM region_counts').fetchone()[0])
finally:
    conn.close()
