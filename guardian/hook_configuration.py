"""Check owned hook semantics without running commands or editing user choices."""


def external_hook_warnings(data, owned):
    """Conservative hints, not shell validation; never expose or execute commands."""
    warnings=[]
    hooks=data.get('hooks',{})
    if not isinstance(hooks,dict):return warnings
    for groups in hooks.values():
        if not isinstance(groups,list):continue
        for group in groups:
            if not isinstance(group,dict) or not isinstance(group.get('hooks',[]),list):continue
            for hook in group.get('hooks',[]):
                if not isinstance(hook,dict):continue
                cmd=hook.get('command','')
                if not isinstance(cmd,str) or cmd in owned or hook.get('args') is not None:continue
                # Only flag bare shell fragments, not an explicit interpreter invocation.
                start=cmd.lstrip().lower()
                explicit=start.startswith(('powershell ', 'powershell.exe ', 'pwsh ', 'pwsh.exe '))
                if not explicit and ('$env:' in cmd.lower() or 'join-path ' in cmd.lower()):
                    warnings.append('其他 Hook 使用 PowerShell 脚本片段，请确认客户端实际使用的 Shell；若被 Bash 执行，可能在 Guardian 检查前报错。')
                if hook.get('shell')=='powershell' and start.startswith(('export ', 'if [', 'if test ')):
                    warnings.append('其他 Hook 声明 PowerShell，却包含 Bash 风格片段；请在所属工具中核对启动方式。')
    return list(dict.fromkeys(warnings))


def conflicts(data, events, commands, *, matchers=('', '*'), shell=None, minimum_timeout=4):
    findings=[]
    for event in events:
        groups=data.get('hooks',{}).get(event,[])
        if not isinstance(groups,list) or any(not isinstance(g,dict) or not isinstance(g.get('hooks',[]),list)
                or any(not isinstance(h,dict) for h in g.get('hooks',[])) for g in groups):
            raise ValueError('Invalid hook configuration')
        owned=[(g,h) for g in groups for h in g.get('hooks',[]) if h.get('command') in commands]
        if len(owned)>1:findings.append(event+':duplicate')
        for group,hook in owned:
            if data.get('disableAllHooks') is True:findings.append(event+':disabled')
            if group.get('matcher','') not in matchers:findings.append(event+':matcher')
            if hook.get('type','command')!='command':findings.append(event+':type')
            for node in (group,hook):
                if any(node.get(key) not in (None,False,'') for key in ('async','asyncRewake','once','if')):
                    findings.append(event+':conditional_or_async')
                if node.get('enabled') is False or node.get('disabled') is True:
                    findings.append(event+':disabled')
            if hook.get('args') is not None or hook.get('env'):
                findings.append(event+':execution_override')
            if shell is not None and hook.get('shell')!=shell:
                findings.append(event+':shell')
            timeout=hook.get('timeout')
            if timeout is not None and (type(timeout) not in (int,float) or not minimum_timeout<=timeout<=600000):
                findings.append(event+':timeout')
    return sorted(set(findings))
