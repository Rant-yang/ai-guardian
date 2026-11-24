"""Bounded local post-tool lexical signals; never persist or return source text."""
import re
from itertools import islice

LIMIT=32768
PATTERN=re.compile(r'ignore\s+(?:(?:all|previous|prior)\s+){0,2}instructions|忽略.{0,8}(?:指令|规则)|system\s+prompt',re.I)


def scan_output(value):
    result={'version':'output-1','status':'missing' if value is None else 'unsupported',
            'characters_scanned':0,'truncated':False,'findings':[]}
    if value is None:return result
    stack=[value];parts=[];remaining=LIMIT;nodes=0
    while stack and remaining>0 and nodes<128:
        item=stack.pop();nodes+=1
        if isinstance(item,str):
            part=item[:remaining];parts.append(part);remaining-=len(part)
            if len(part)<len(item):result['truncated']=True
        elif isinstance(item,dict):
            values=list(islice(item.values(),128));stack.extend(reversed(values))
            if len(item)>128:result['truncated']=True
        elif isinstance(item,list):
            stack.extend(reversed(item[:128]))
            if len(item)>128:result['truncated']=True
    result['truncated']=result['truncated'] or bool(stack)
    if parts:
        result.update(status='scanned',characters_scanned=LIMIT-remaining,
                      findings=['instruction_override'] if any(PATTERN.search(part) for part in parts) else [])
    return result


def validate_scan(value):
    if not isinstance(value,dict) or set(value)!={'version','status','characters_scanned','truncated','findings'}:raise ValueError('Invalid output scan')
    if value['version']!='output-1' or value['status'] not in ('scanned','missing','unsupported'):raise ValueError('Invalid output scan')
    if type(value['characters_scanned']) is not int or not 0<=value['characters_scanned']<=LIMIT or type(value['truncated']) is not bool:raise ValueError('Invalid output scan')
    if value['findings'] not in ([],['instruction_override']):raise ValueError('Invalid output findings')
    if value['status']!='scanned' and (value['characters_scanned'] or value['findings']):raise ValueError('Invalid output coverage')
    return {**value,'findings':list(value['findings'])}
