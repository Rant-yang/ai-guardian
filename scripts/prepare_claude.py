"""Generate a separate settings file; never edits existing Claude configuration."""
import argparse
import json
import shlex
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=['protect', 'observe'], default='observe')
parser.add_argument('--port', type=int, default=8765)
options = parser.parse_args()
# Claude command hooks run under the configured shell (normally Git Bash on Windows).
command = shlex.join([Path(sys.executable).as_posix(), (root/'guardian'/'hook.py').as_posix(),
    '--token-file', (root/'.local'/'access-token').as_posix(), '--port', str(options.port), '--mode', options.mode])
settings = {'hooks': {'PreToolUse': [{'matcher': '', 'hooks': [
    {'type': 'command', 'command': command, 'timeout': 5}]}]}}
target = root / '.local' / 'claude-guardian.settings.json'
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(settings, indent=2), encoding='utf-8')
print(f'Generated settings (not installed): {target}')
print(f'Mode: {options.mode}; existing Claude settings unchanged.')
