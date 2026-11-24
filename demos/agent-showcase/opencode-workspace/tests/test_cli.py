import json,subprocess,sys,tempfile,unittest
from pathlib import Path
class CLITests(unittest.TestCase):
 def test_end_to_end(self):
  with tempfile.TemporaryDirectory() as folder:
   result=subprocess.run([sys.executable,'-m','shopops.cli','--data','data','--output',folder],capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr)
   summary=json.loads((Path(folder)/'summary.json').read_text())
   rejected=json.loads((Path(folder)/'rejected.json').read_text())
   self.assertEqual(summary['count'],56);self.assertEqual(len(rejected),4)
