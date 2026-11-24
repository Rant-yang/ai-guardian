"""User-level adapters, with narrowly owned configuration and reversible changes."""
import copy
import base64
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time
import tomllib
import uuid
from .config_files import check_path
from .adapter_contracts import JSON_HOOK_PROTOCOLS
from .hook_configuration import conflicts as hook_conflicts, external_hook_warnings
from scripts.install_opencode import manage as opencode_manage

ROOT = Path(__file__).resolve().parent.parent
LOCK = threading.RLock()
CLIENTS = {'pi':'Pi（实验接入）', 'qoder':'Qoder CLI（实验接入）', 'claude':'Claude Code', 'gemini':'Gemini CLI', 'opencode':'OpenCode', 'codex':'Codex MCP 演示'}


def powershell_launcher(script):
    """Literal executable invocation accepted by both Bash and PowerShell.

    Encoding transports our fixed script through the outer shell without
    expansion; it is not a security decision or a bypass of client permissions.
    """
    encoded=base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return 'powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand '+encoded


def command(client, *, legacy=False):
    protocol=JSON_HOOK_PROTOCOLS[client]
    args=[sys.executable,str(ROOT/'guardian/hook.py'),'--client',client,'--token-file',str(ROOT/'.local/access-token'),'--mode','observe']
    if protocol.explicit_shell and os.name=='nt':
        base='& '+ ' '.join("'"+v.replace("'","''")+"'" for v in args)
        script=base+'; exit 0'
        return script if legacy else powershell_launcher(script)
    base=shlex.join([v.replace('\\','/') for v in args]) if protocol.posix_command else subprocess.list2cmdline(args)
    # Observe-only hooks must not become a denial if Python cannot open the script.
    return base if legacy else base+(' || exit 0' if protocol.posix_command or os.name!='nt' else ' || exit /b 0')


def paths(home, client):
    from .adapter_registry import target
    path=target(client,home)
    return path.with_name('config.toml') if client=='codex' else path


def codex_block():
    args=[str(ROOT/'guardian/mcp_demo.py'),'--token-file',str(ROOT/'.local/access-token')]
    return '\n# Guardian managed MCP demo begin\n[mcp_servers.guardian_demo]\ncommand = '+json.dumps(sys.executable)+'\nargs = '+json.dumps(args)+'\n# Guardian managed MCP demo end\n'


def atomic_change(path, before, after):
    check_path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    check_path(path)
    if path.is_symlink(): raise ValueError('拒绝修改符号链接配置')
    current=path.read_bytes() if path.exists() else None
    if current != before: raise ValueError('配置已被其他程序修改，请重试')
    if before is not None:
        backup=path.with_name(path.name+'.guardian-backup-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        backup.write_bytes(before)
    temp=path.with_name(path.name+'.guardian-'+uuid.uuid4().hex+'.tmp')
    try:
        temp.write_bytes(after)
        check_path(path)
        if (path.read_bytes() if path.exists() else None) != before: raise ValueError('配置发生并发变更')
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()


def manage(client, action, home=None, *, target_path=None):
    if client not in CLIENTS or action not in ('status','install','uninstall'):raise ValueError('不支持的接入操作')
    home=Path(home) if home else Path.home()
    with LOCK:
        if client=='pi':
            from .adapter_registry import target
            from scripts.install_pi import manage as pi_manage
            return pi_manage(target_path if target_path is not None else target(client,home),action)
        if client=='opencode':
            from .adapter_registry import target
            config=(target_path if target_path is not None else target(client,home)).parent.parent
            return opencode_manage(config,action)
        path=Path(target_path) if target_path is not None else paths(home,client)
        check_path(path)
        if path.is_symlink():raise ValueError('拒绝修改符号链接配置')
        before=path.read_bytes() if path.exists() else None
        raw=before.decode('utf-8-sig') if before else ''
        if client=='codex':
            data=tomllib.loads(raw)
            block=codex_block()
            installed=block in raw
            if action=='status':return {'installed':installed,'limited':True}
            if action=='install' and not installed:
                if 'guardian_demo' in data.get('mcp_servers',{}):raise ValueError('已有同名 MCP 配置，未覆盖')
                output=raw+block
            elif action=='uninstall' and installed:output=raw.replace(block,'',1)
            else:return {'installed':installed,'restart_required':True}
            tomllib.loads(output)
        else:
            data=json.loads(raw) if raw.strip() else {}
            original=copy.deepcopy(data)
            if not isinstance(data,dict) or not isinstance(data.get('hooks',{}),dict):raise ValueError('钩子配置必须为对象')
            protocol=JSON_HOOK_PROTOCOLS[client]
            event=protocol.before
            entries=data.get('hooks',{}).get(event,[])
            if not isinstance(entries,list) or any(not isinstance(e,dict) or not isinstance(e.get('hooks',[]),list) or any(not isinstance(h,dict) for h in e.get('hooks',[])) for e in entries):raise ValueError('现有钩子结构无效')
            cmd=command(client)
            owned={cmd,command(client,legacy=True)}
            conflicts=hook_conflicts(data,(event,*protocol.receipts),owned,
                matchers=('', '*', '.*') if client=='gemini' else ('','*'),
                minimum_timeout=4000 if client=='gemini' else 4,
                shell=('powershell' if os.name=='nt' else 'bash') if protocol.explicit_shell else None)
            if action=='install' and conflicts:
                raise ValueError('Guardian 钩子匹配范围或执行方式已改变，请先核对配置')
            installed=any(h.get('command')==cmd for e in entries for h in e.get('hooks',[]))
            outdated=command(client,legacy=True)!=cmd and any(h.get('command')==command(client,legacy=True) for e in entries for h in e.get('hooks',[]))
            if action=='status':
                receipt_hooks=[]
                if protocol.receipts:
                    for post_event in protocol.receipts:
                        groups=data.get('hooks',{}).get(post_event,[])
                        if not isinstance(groups,list) or any(not isinstance(g,dict) or not isinstance(g.get('hooks',[]),list) or any(not isinstance(h,dict) for h in g.get('hooks',[])) for g in groups):raise ValueError('回执钩子结构无效')
                        receipt_hooks.append(any(h.get('command')==cmd for g in groups for h in g.get('hooks',[])))
                return {'installed':installed,'limited':False,'outdated':outdated,'conflict':bool(conflicts),'configuration_issues':conflicts,
                    'upgrade_available':client=='qoder' and outdated and not conflicts,
                    'warnings':external_hook_warnings(data,owned),
                    'partial':bool(protocol.receipts) and (installed or any(receipt_hooks)) and not (installed and all(receipt_hooks))}
            if action=='install' and not installed:
                for entry in entries:
                    for handler in entry.get('hooks',[]):
                        if handler.get('command') in owned:handler['command']=cmd
                hook={'type':'command','command':cmd,'timeout':protocol.timeout}
                if protocol.explicit_shell:hook['shell']='powershell' if os.name=='nt' else 'bash'
                if protocol.hook_name:hook['name']=protocol.hook_name
                if not outdated:data.setdefault('hooks',{}).setdefault(event,[]).append({'matcher':protocol.matcher,'hooks':[hook]})
            elif action=='uninstall' and (installed or outdated):
                kept=[]
                for entry in entries:
                    updated=copy.deepcopy(entry)
                    updated['hooks']=[h for h in updated.get('hooks',[]) if h.get('command') not in owned]
                    if updated['hooks'] or not entry.get('hooks'):kept.append(updated)
                if kept:data['hooks'][event]=kept
                else:data['hooks'].pop(event,None)
            if protocol.receipts:
                for post_event in protocol.receipts:
                    groups=data.get('hooks',{}).get(post_event,[])
                    if not isinstance(groups,list) or any(not isinstance(g,dict) or not isinstance(g.get('hooks',[]),list) or any(not isinstance(h,dict) for h in g.get('hooks',[])) for g in groups):raise ValueError('回执钩子结构无效')
                    if action=='install' and not any(h.get('command')==cmd for g in groups for h in g.get('hooks',[])):
                        migrated=False
                        for group in groups:
                            for handler in group.get('hooks',[]):
                                if handler.get('command') in owned:
                                    handler['command']=cmd
                                    migrated=True
                        if not migrated:
                            data.setdefault('hooks',{}).setdefault(post_event,[]).append({'matcher':protocol.matcher,'hooks':[{'type':'command','command':cmd,'timeout':protocol.timeout,**({'shell':'powershell' if os.name=='nt' else 'bash'} if protocol.explicit_shell else {})}]})
                    elif action=='uninstall':
                        kept=[]
                        for group in groups:
                            updated=copy.deepcopy(group)
                            updated['hooks']=[h for h in group.get('hooks',[]) if h.get('command') not in owned]
                            if updated['hooks'] or not group.get('hooks'):kept.append(updated)
                        if kept:data['hooks'][post_event]=kept
                        elif groups:data['hooks'].pop(post_event,None)
            if action=='uninstall' and data!=original and data.get('hooks')=={}:data.pop('hooks')
            if data==original:return {'installed':installed,'restart_required':True}
            output=json.dumps(data,ensure_ascii=False,indent=2)+'\n'
        atomic_change(path,before,output.encode('utf-8'))
        return {'installed':action=='install','restart_required':True}


def snapshot():
    rows=[]
    for client,name in CLIENTS.items():
        try:
            result=manage(client,'status')
            rows.append({'id':client,'name':name,'installed':bool(result.get('installed')),
                'read_only':True,
                'conflict':bool(result.get('conflict')),'outdated':bool(result.get('outdated')),
                'configuration_issues':result.get('configuration_issues',[]),
                'partial':bool(result.get('partial')),
                'coverage':'仅合成 MCP 工具；原生工具未覆盖' if client=='codex' else '执行前检查 · 默认观察'})
        except Exception:
            rows.append({'id':client,'name':name,'installed':False,'read_only':True,'error':'配置不可读取或格式冲突'})
    try:
        from scripts.install_codex_hooks import manage as codex_hooks_status
        native=codex_hooks_status(Path.home(),'status')
        rows.append({'id':'codex-native','name':'Codex 原生 Hooks','installed':native['installed'],
            'conflict':bool(native.get('conflict')),'configuration_issues':native.get('configuration_issues',[]),
            'partial':native.get('partial',False),
            'read_only':True,'coverage':'钩子已配置；需 Codex 信任后新建会话验证，尚未证明原生拦截。' if native['installed'] else '原生钩子未配置'})
    except Exception:
        rows.append({'id':'codex-native','name':'Codex 原生 Hooks','installed':False,'read_only':True,'error':'钩子配置不可读取'})
    return rows
