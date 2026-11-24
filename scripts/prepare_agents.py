"""Prepare only project-owned demo configuration. Never modify global client config."""
import json
import shlex
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
token = root/'.local/access-token'
hook = root/'guardian/hook.py'
for name in ('claude','gemini','codex'):
    folder = root/'demos'/name
    folder.mkdir(parents=True,exist_ok=True)
    note = folder/'notes.txt'
    if not note.exists():
        note.write_text('Synthetic Guardian demo note. No private data. Summarize this sentence only.\n')

claude_command = shlex.join([Path(sys.executable).as_posix(),hook.as_posix(),'--token-file',token.as_posix(),'--mode','observe'])
claude = {'hooks':{'PreToolUse':[{'matcher':'','hooks':[{'type':'command','command':claude_command,'timeout':5}]}]}}
(root/'demos/claude/guardian.settings.json').write_text(json.dumps(claude,indent=2),encoding='utf-8')
gemini_command = subprocess.list2cmdline([sys.executable,str(hook),'--client','gemini','--token-file',str(token),'--mode','observe'])
gemini = {'hooks':{'BeforeTool':[{'matcher':'.*','hooks':[{'name':'guardian-local','type':'command','command':gemini_command,'timeout':5000}]}]}}
target = root/'demos/gemini/.gemini'
target.mkdir(exist_ok=True)
(target/'settings.json').write_text(json.dumps(gemini,indent=2),encoding='utf-8')
print('Prepared project-local Claude, Gemini and Codex demo directories. Global settings unchanged.')
