"""Versioned heuristic rules. No command execution or raw parameter persistence."""
import hashlib
import ast
import json
import ntpath
import os
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit

PACK=json.loads((Path(__file__).with_name('rules.json')).read_text(encoding='utf-8'))
VERSION=PACK['version']+'-'+hashlib.sha256(json.dumps(PACK,sort_keys=True).encode()).hexdigest()[:12]
ALIASES={'powershell':'Bash','bash':'Bash','exec_command':'Bash','shell_command':'Bash','shell':'Bash','run_shell_command':'Bash',
         'read':'Read','read_file':'Read','write':'Write','write_file':'Write','edit':'Edit','replace':'Edit'}
# Bind grants to normalization and bounded command interpretation as well as the pack.
VERSION+='-tools11'
for rule in PACK['rules']:
    if rule['action'] not in ('warn','review','deny'):raise ValueError('Invalid rule action')
    rule['_compiled']=[re.compile(pattern,re.I) for pattern in rule['patterns']]

PATCH_RULES=[dict(id=identity,title=title,action='review',tools=['apply_patch'],field='patch_structure',
    patterns=[],reason=reason,impact='允许后客户端可能修改或删除文件；守卫不执行或重放补丁。') for identity,title,reason in (
    ('patch_unparsed_review','补丁需要核对','补丁格式或大小超出有界解析范围。'),
    ('patch_delete_review','补丁删除文件','补丁声明删除文件，需要确认任务范围。'))]


def catalog():
    return {'version':VERSION,'rules':[{k:v for k,v in r.items() if k!='_compiled'} for r in [*PACK['rules'],*PATCH_RULES]]}


def rule_input(tool,args):
    canonical=ALIASES.get(tool,tool)
    normalized=dict(args)
    if canonical=='Bash':
        command=args.get('command',args.get('cmd'))
        if isinstance(command,str):normalized['command']=command
        elif isinstance(command,list) and command and all(isinstance(part,str) for part in command):
            # Lexical risk hints only: joining argv is not a faithful shell parse.
            normalized['command']=' '.join(command)
            normalized['_argv_command']=True
    if tool=='apply_patch':
        patch=parse_patch(args)
        if patch is not None:
            canonical='Edit'
            normalized['_patch_targets']=tuple(patch['targets'])
    return canonical,normalized


def parse_patch(args):
    """Bounded header extraction, not a patch applicability or content validator."""
    values=[args[key] for key in ('patchText','command','patch','input') if key in args]
    if len(values)!=1 or not isinstance(values[0],str) or len(values[0].encode('utf-8'))>65536:return None
    lines=values[0].splitlines()
    if len(lines)<3 or lines[0]!='*** Begin Patch' or lines[-1]!='*** End Patch':return None
    targets=[];deleted=False;kind=None;body=False;moved=False
    for line in lines[1:-1]:
        match=re.fullmatch(r'\*\*\* (Add|Update|Delete) File: (.+)',line)
        if match:
            if kind in ('Add','Update') and not body:return None
            kind=match[1];target=match[2];body=False;moved=False
            if not target.strip() or any(ord(c)<32 for c in target):return None
            targets.append(target.replace('\\','/'));deleted|=kind=='Delete'
            if len(targets)>64:return None
        elif line.startswith('*** Move to: '):
            target=line[len('*** Move to: '):]
            if kind!='Update' or moved or body or not target.strip() or any(ord(c)<32 for c in target):return None
            targets.append(target.replace('\\','/'));moved=True
            if len(targets)>64:return None
        elif kind=='Add' and line.startswith('+'):body=True
        elif kind=='Update' and (line.startswith((' ','+','-','@@')) or line=='*** End of File'):body=True
        else:return None
    if not targets or (kind in ('Add','Update') and not body):return None
    return {'targets':targets,'deletes':deleted}


def file_targets(args):
    targets=[value.replace('\\','/') for key in ('file_path','path','filePath','absolute_path')
            if isinstance((value:=args.get(key)),str) and value]
    if isinstance(args.get('_patch_targets'),tuple):targets.extend(args['_patch_targets'])
    return targets


def path_match_variants(value):
    """Add Windows lexical review hints; never resolve links or rewrite actions."""
    variants=[value]
    if os.name!='nt' and not re.match(r'^[a-z]:',value,re.I) and not value.startswith('//'):return variants
    drive,tail=ntpath.splitdrive(value)
    parts=tail.split('/')
    # Keep dot/parent components: collapsing them would assume link semantics.
    clean=[part if part in ('.','..') else part.rstrip(' .') for part in parts]
    if clean:clean[-1]=clean[-1].split(':',1)[0].rstrip(' .')
    cleaned='/'.join(clean)
    candidate=drive+('/' if drive and not cleaned.startswith('/') else '')+cleaned
    if candidate!=value:variants.append(candidate)
    return variants


def shell_read_targets(args):
    """Literal targets of a leading read utility; never evaluate shell expansion.

    This adds review signals only. It does not parse full shell syntax or suppress
    any existing findings. Keep backslashes for Windows paths (posix=False).
    """
    command=args.get('command')
    if not isinstance(command,str):return []
    head=re.match(r'^\s*(?:cat|Get-Content|gc|type|head|tail)(?:\.exe)?\s+',command,re.I)
    if not head:return []
    try:
        lexer=shlex.shlex(command[head.end():],posix=False,punctuation_chars=';&|<>')
        lexer.whitespace_split=True
        lexer.commenters=''
        targets=[]
        for token in lexer:
            if token and token[0] in ';&|<>':break
            if token.startswith('-'):continue
            if len(token)>=2 and token[0] in ('"',"'") and token[-1]==token[0]:token=token[1:-1]
            if any(character in token for character in ('$','`','*','?','\n','\r')):continue
            targets.append(token.replace('\\','/'))
        return targets
    except ValueError:return []


def literal_python_calls(args):
    """Recognize a bounded, unexpanded python -c subset without executing code.

    Only direct top-level calls after imports are classified. Unknown statements
    invalidate bindings; function bodies and string examples are never walked.
    This is not a general Python or shell execution analyzer.
    """
    command=args.get('command')
    if not isinstance(command,str) or len(command)>8192:return []
    match=re.fullmatch(r'\s*(?:python(?:3(?:\.\d+)?)?|py)(?:\.exe)?\s+-c\s+"([^"\r\n]*)"\s*',command,re.I)
    if not match or any(c in match[1] for c in ('$', '`', '\\')):return []
    try:tree=ast.parse(match[1])
    except (SyntaxError,ValueError,RecursionError):return []
    bindings={};calls=[]
    for node in tree.body:
        if isinstance(node,ast.Import):
            for alias in node.names:
                name=alias.asname or alias.name.split('.')[0]
                bindings.pop(name,None)
                if alias.name=='shutil':bindings[name]='shutil'
        elif isinstance(node,ast.ImportFrom):
            for alias in node.names:
                if alias.name=='*':bindings.clear();continue
                name=alias.asname or alias.name;bindings.pop(name,None)
                if node.module=='shutil' and not node.level and alias.name=='rmtree':bindings[name]='shutil.rmtree'
        elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Call):
            call=node.value;function=call.func;resolved=None
            if isinstance(function,ast.Name):resolved=bindings.get(function.id)
            elif isinstance(function,ast.Attribute) and isinstance(function.value,ast.Name):
                parent=bindings.get(function.value.id)
                if parent:resolved=parent+'.'+function.attr
            target=call.args[0] if call.args else next((kw.value for kw in call.keywords if kw.arg=='path'),None)
            if resolved=='shutil.rmtree' and isinstance(target,ast.Constant) and isinstance(target.value,str) and target.value:
                calls.append(resolved)
            bindings.clear()
        else:bindings.clear()
    return calls


def literal_shell_form(args):
    """Recognize only an entire simple command under standard utility semantics.

    No expansion, separators, redirects, script blocks, formatting escapes,
    wrappers or runtime name-resolution assumptions are evaluated here.
    Unknown forms retain all existing findings.
    """
    if args.get('_argv_command'):return None
    command=args.get('command')
    if not isinstance(command,str) or len(command)>8192:return None
    if re.fullmatch(r"[ \t]*printf[ \t]+'[\w ./:=-]*'[ \t]*",command):
        return 'literal_printf'
    match=re.fullmatch(r'[ \t]*Remove-Item[ \t]+([^\r\n]+?)[ \t]*',command,re.I)
    if not match:return None
    # Positive token alphabet; special syntax even inside quotes is unsupported.
    word=r'''(?:'[\w ./\\:-]+'|"[\w ./\\:-]+"|[\w./\\:-]+)'''
    if not re.fullmatch(word+r'(?:[ \t]+'+word+r')*',match[1]):return None
    tokens=re.findall(word,match[1]);flags=set();paths=[];expect_path=False
    for token in tokens:
        quoted=token[0] in ('"',"'")
        value=token[1:-1] if quoted else token
        if not quoted and value.startswith('-'):
            flag=value.lower()
            if expect_path or flag not in ('-whatif','-recurse','-force','-path','-literalpath') or flag in flags:return None
            if flag in ('-path','-literalpath'):
                if paths or flags.intersection(('-path','-literalpath')):return None
                expect_path=True
            flags.add(flag)
        else:
            if not value or value.startswith('-') or paths:return None
            paths.append(value);expect_path=False
    if '-whatif' in flags and len(paths)==1 and not expect_path:return 'literal_remove_whatif'
    return None


def coverage(tool,args):
    canonical,normalized=rule_input(tool,args)
    supported=canonical in {name for rule in PACK['rules'] for name in rule['tools']}
    if canonical=='Bash' and (not isinstance(normalized.get('command'),str) or normalized.get('_argv_command')):supported=False
    if canonical in ('Read','Write','Edit') and not file_targets(normalized):supported=False
    result={'level':'tool_rules' if supported else 'generic_only','canonical_tool':canonical,
            'note':'仅启发式规则，不代表完整安全结论' if supported else '尚无该工具/参数结构的专用规则，仅检查通用文本信号'}
    if normalized.get('_argv_command'):result['note']='数组命令仅生成词法风险线索；未解析参数边界与解释器语义，不适用字面量安全豁免'
    if tool=='apply_patch':result['note']='仅核对有界补丁目标路径与删除声明；未验证补丁可应用性或修改内容安全' if parse_patch(args) is not None else '补丁格式或大小超出解析范围，需要人工核对；没有执行补丁'
    form=literal_shell_form(normalized) if canonical=='Bash' else None
    if form:
        result['literal_shell_form']=form
        result['note']+='；识别为有界字面量打印或 WhatIf 预览，未验证运行时同名命令是否被重定义'
    return result


def assess(tool,args):
    patch=parse_patch(args) if tool=='apply_patch' else None
    patch_tool=tool=='apply_patch'
    tool,args=rule_input(tool,args)
    matches=[]
    if patch_tool and (patch is None or patch['deletes']):
        matches.append(PATCH_RULES[0 if patch is None else 1])
    form=literal_shell_form(args) if tool=='Bash' else None
    for rule in PACK['rules']:
        if rule['tools'] and tool not in rule['tools']:continue
        # Suppress only this lexical false positive, never other risk signals.
        if rule['id']=='destructive_command' and form:continue
        if rule['id']=='encoded_execution' and form=='literal_printf':continue
        texts=(literal_python_calls(args) if rule['field']=='python_calls' else file_targets(args) if rule['field']=='paths' else shell_read_targets(args)
               if rule['field']=='shell_read_paths' else [json.dumps(args,ensure_ascii=False) if rule['field']=='*' else str(args.get(rule['field'],''))])
        if rule['field'] in ('paths','shell_read_paths'):texts=[variant for text in texts for variant in path_match_variants(text)]
        for text in texts:
            hits=[bool(p.search(text)) for p in rule['_compiled']]
            if (all(hits) if rule.get('all') else any(hits)):
                matches.append(rule)
                break
    return matches


def preview(tool,args):
    """Only bounded basenames and URL hosts; never command bodies, credentials or queries."""
    targets=[]
    canonical,args=rule_input(tool,args)
    for value in file_targets(args):
        targets.append(value.replace('\\','/').rstrip('/').split('/')[-1][:80])
    if canonical=='Bash':
        # Show only recognized credential targets, not arbitrary command tokens
        # (which can be option values, quoted examples or private text).
        patterns=[p for rule in PACK['rules'] if rule['field']=='shell_read_paths' for p in rule['_compiled']]
        for value in shell_read_targets(args):
            if any(p.search(variant) for variant in path_match_variants(value) for p in patterns):
                targets.append(value.rstrip('/').split('/')[-1][:80])
    for url in re.findall(r'https?://[^\s\"\'<>]+',('' if tool=='apply_patch' else str(args.get('command','')))+' '+str(args.get('destination',''))):
        try:
            host=urlsplit(url).hostname
            if host:targets.append(host[:120])
        except ValueError:pass
    return {'tool':tool,'targets':list(dict.fromkeys(targets))[:6],
            'redaction':'仅显示文件名/目标主机；完整参数留在客户端，审批绑定完整参数摘要'}
