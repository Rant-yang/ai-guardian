"""Explicit, reversible user-level Guardian hooks; never edits config.toml."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from guardian.integrations import atomic_change
from guardian.config_files import check_path
from guardian.hook_configuration import conflicts as hook_conflicts, external_hook_warnings


def hook_command():
    return subprocess.list2cmdline([sys.executable,str(ROOT/'guardian/codex_hook.py'),
                                   '--token-file',str(ROOT/'.local/access-token')])


def manage(home,action,*,target_path=None):
    if action not in ('status','install','uninstall'):raise ValueError('Unsupported operation')
    from guardian.adapter_registry import target
    path=Path(target_path) if target_path is not None else target('codex',home)
    check_path(path)
    if path.is_symlink():raise ValueError('Refusing linked hooks file')
    before=path.read_bytes() if path.exists() else None
    data=json.loads(before.decode('utf-8-sig')) if before else {}
    if not isinstance(data,dict) or not isinstance(data.get('hooks',{}),dict):raise ValueError('Invalid hooks file')
    original=copy.deepcopy(data)
    command=hook_command()
    conflicts=hook_conflicts(data,('PreToolUse','PostToolUse'),{command})
    if action=='install' and conflicts:raise ValueError('Guardian hook execution settings changed; review configuration')
    installed=[]
    for event in ('PreToolUse','PostToolUse'):
        groups=data.get('hooks',{}).get(event,[])
        if not isinstance(groups,list) or any(not isinstance(g,dict) or not isinstance(g.get('hooks',[]),list)
                or any(not isinstance(h,dict) for h in g.get('hooks',[])) for g in groups):
            raise ValueError('Invalid existing hook groups')
        found=any(h.get('command')==command for g in groups for h in g.get('hooks',[]))
        installed.append(found)
        if action=='install' and not found:
            data.setdefault('hooks',{}).setdefault(event,[]).append({'matcher':'',
                'hooks':[{'type':'command','command':command,'timeout':4}]})
        elif action=='uninstall':
            kept=[]
            for group in groups:
                clone=copy.deepcopy(group)
                clone['hooks']=[h for h in group.get('hooks',[]) if h.get('command')!=command]
                if clone['hooks'] or not group.get('hooks'):kept.append(clone)
            if groups:
                if kept:data['hooks'][event]=kept
                else:data['hooks'].pop(event,None)
    if action=='uninstall' and data!=original and data.get('hooks')=={}:data.pop('hooks')
    if action in ('install','uninstall') and data!=original:
        atomic_change(path,before,(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
    return {'installed':all(installed) if action=='status' else action=='install',
            'warnings':external_hook_warnings(data,{command}),
            'conflict':bool(conflicts),'configuration_issues':conflicts,
            'partial':any(installed) and not all(installed) if action=='status' else False,
            'changed':data!=original,'path':str(path),'command':command,
            'config_toml_modified':False,'trust':'client review may be required'}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['status','install','uninstall'])
    args=parser.parse_args()
    print(json.dumps(manage(Path.home(),args.action),ensure_ascii=False))
