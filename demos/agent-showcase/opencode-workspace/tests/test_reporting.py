import json,sqlite3,tempfile,unittest
from pathlib import Path
from shopops.reporting import render_html,save_reports
class ReportTests(unittest.TestCase):
 def test_escape(self):
  result=render_html({'count':1,'paid_revenue':12.5,'by_region':{'<script>':1}})
  self.assertNotIn('<script>',result);self.assertIn('&lt;script&gt;',result)
 def test_idempotent_save(self):
  with tempfile.TemporaryDirectory() as folder:
   summary={'count':2,'paid_revenue':25,'by_region':{'east':2}}
   save_reports(summary,folder);save_reports(summary,folder)
   self.assertEqual(json.loads((Path(folder)/'summary.json').read_text()),summary)
   with sqlite3.connect(Path(folder)/'metrics.sqlite3') as db:
    self.assertEqual(db.execute('SELECT region,count FROM region_counts').fetchall(),[('east',2)])
   db.close()
