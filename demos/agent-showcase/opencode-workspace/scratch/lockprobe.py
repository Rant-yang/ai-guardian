import sqlite3, tempfile, os
from pathlib import Path
from shopops.reporting import save_reports

folder = tempfile.mkdtemp()
save_reports({'count':2,'paid_revenue':25,'by_region':{'east':2}}, folder)
p = Path(folder)/'metrics.sqlite3'
db = sqlite3.connect(p)
print('rows', db.execute('SELECT region,count FROM region_counts').fetchall())
try:
    os.unlink(p)
    print('unlink while reader open: OK')
except Exception as e:
    print('unlink while reader open FAILED:', type(e).__name__, e)
db.close()
try:
    os.unlink(p)
    print('unlink after close: OK')
except Exception as e:
    print('unlink after close FAILED:', type(e).__name__, e)
os.rmdir(folder)
