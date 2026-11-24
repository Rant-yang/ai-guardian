"""Codex hook protocol adapter. Contains no installation or client configuration code."""
def normalize(payload):
    if not isinstance(payload,dict):raise ValueError('object required')
    if payload.get('hook_event_name') not in ('PreToolUse','PostToolUse'):
        raise ValueError('unsupported hook phase')
    args=payload.get('tool_input')
    if not isinstance(args,dict):raise ValueError('tool_input must be an object')
    result={key:payload.get(key) for key in ('session_id','tool_use_id','tool_name')}
    if any(not isinstance(v,str) or not 0<len(v)<=200 for v in result.values()):
        raise ValueError('missing hook identity')
    args=dict(args)
    if result['tool_name'] in ('exec_command','shell_command','shell','Bash'):
        command=args.get('command',args.get('cmd'))
        if not (isinstance(command,str) or
                (isinstance(command,list) and command and all(isinstance(part,str) for part in command))):
            raise ValueError('missing or invalid command')
        # Keep exact input keys, types and argv boundaries for one-use grants.
        # Rule-only normalization belongs in rules.rule_input, never here.
    result['tool_input']=args
    if 'cwd' in payload:result['cwd']=payload['cwd']
    return result


def decision_output(event):
    # Do not return allow: preserve the client's own permission checks.
    # Review is stopped for an explicitly authorized retry; never pretend to resume.
    if event['mode']=='protect' and event['verdict'] in ('deny','review'):
        reason='Guardian: '+', '.join(event['findings'])
        if event['verdict']=='review':reason+='; 待守卫审批，批准后需重新发起完全相同的动作。'
        return {'hookSpecificOutput':{'hookEventName':'PreToolUse',
            'permissionDecision':'deny','permissionDecisionReason':reason}}
    return {}
