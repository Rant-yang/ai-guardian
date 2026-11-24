"""Local service discovery shared by command hooks; no URLs or secrets in the file."""
import json
import os
from pathlib import Path
import uuid

NAME='service-endpoint.json'


def valid_port(value):
    if type(value) is not int or not 1<=value<=65535:raise ValueError('invalid Guardian port')
    return value


def resolve_port(token_file, explicit=None):
    if explicit is not None:return valid_port(explicit)
    path=Path(token_file).parent/NAME
    try:
        with path.open('rb') as stream:raw=stream.read(4097)
    except FileNotFoundError:return 8765
    if len(raw)>4096:raise ValueError('invalid endpoint descriptor')
    data=json.loads(raw)
    if not isinstance(data,dict) or type(data.get('version')) is not int or data.get('version')!=1 or data.get('host')!='127.0.0.1':
        raise ValueError('invalid endpoint descriptor')
    return valid_port(data.get('port'))


def publish(data_dir,port):
    """Publish only after successful bind. Readers see the old or new complete file."""
    path=Path(data_dir)/NAME
    temp=path.with_name(NAME+'.'+uuid.uuid4().hex+'.tmp')
    data={'version':1,'host':'127.0.0.1','port':valid_port(port)}
    try:
        with temp.open('x',encoding='utf-8') as stream:
            json.dump(data,stream);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()
