"""Ephemeral instance-bound OpenCode navigation, no arbitrary commands or URLs."""
from collections import OrderedDict
import re
import threading
import time
import uuid


class Navigation:
    def __init__(self,store=None):
        self.store=store
        self.lock=threading.RLock()
        self.instances={}
        self.origins=OrderedDict()
        self.requests=OrderedDict()

    def remember(self,event,session,instance):
        if event.get('is_demo') or event.get('source_adapter')!='opencode-plugin':return
        if not isinstance(session,str) or not re.fullmatch(r'ses_[A-Za-z0-9]{8,128}',session):return
        try:instance=str(uuid.UUID(instance))
        except (ValueError,TypeError,AttributeError):return
        with self.lock:
            if event['event_id'] in self.origins:return
            self.origins[event['event_id']]=(instance,session,time.monotonic()+86400)
            if self.store:self.store.put('opencode',event['event_id'],[instance,session])
            self.origins.move_to_end(event['event_id'])
            while len(self.origins)>2000:self.origins.popitem(last=False)

    def expire(self):
        now=time.monotonic()
        self.instances={k:v for k,v in self.instances.items() if v>now}
        for row in self.requests.values():
            if row['expires']<=now and row['state'] in ('queued','delivered'):row['state']='expired'
        self.requests=OrderedDict((k,v) for k,v in self.requests.items() if v['expires']+300>now)

    def heartbeat(self,data):
        instance=str(uuid.UUID(data['instance_id']))
        with self.lock:
            self.expire()
            if data.get('navigation')!='session_select':
                self.instances.pop(instance,None)
                return {}
            if instance not in self.instances and len(self.instances)>=256:raise ValueError('Navigation capacity')
            self.instances[instance]=time.monotonic()+45
            for identity,row in self.requests.items():
                if row['instance']==instance and row['state']=='queued':
                    row['state']='delivered'
                    return {'navigation':{'request_id':identity,'kind':'select_session','session_id':row['session']}}
            return {}

    def request(self,event_id):
        with self.lock:
            self.expire()
            origin=self.origins.get(event_id)
            if origin is None and self.store:
                saved=self.store.get('opencode',event_id)
                if saved:
                    value,remaining=saved
                    if isinstance(value,list) and len(value)==2 and all(isinstance(v,str) for v in value):
                        instance,session=value
                        try:instance=str(uuid.UUID(instance))
                        except ValueError:return None
                        if re.fullmatch(r'ses_[A-Za-z0-9]{8,128}',session):origin=(instance,session,time.monotonic()+remaining)
            if not origin or origin[2]<=time.monotonic() or origin[0] not in self.instances:return None
            for identity,row in reversed(self.requests.items()):
                if row['event_id']==event_id and row['state'] in ('queued','delivered'):
                    return self.public(identity,row)
            # A newer click for this instance replaces old undelivered/unfinished navigation.
            # Never let a backlog switch the UI back to a previously clicked session later.
            for row in self.requests.values():
                if row['instance']==origin[0] and row['state'] in ('queued','delivered'):
                    row['state']='superseded'
            if len(self.requests)>=64:self.requests.popitem(last=False)
            identity=str(uuid.uuid4())
            row={'event_id':event_id,'instance':origin[0],'session':origin[1],'state':'queued','expires':time.monotonic()+15}
            self.requests[identity]=row
            return self.public(identity,row)

    def acknowledge(self,data):
        if data.get('status') not in ('dispatched','failed'):raise ValueError('Invalid navigation status')
        with self.lock:
            self.expire()
            row=self.requests.get(data.get('request_id'))
            if not row or row['instance']!=data.get('instance_id') or row['state']!='delivered':raise ValueError('Navigation identity mismatch or expired')
            row['state']=data['status']
            return {'accepted':True}

    def status(self,event_id):
        with self.lock:
            self.expire()
            for identity,row in reversed(self.requests.items()):
                if row['event_id']==event_id:return self.public(identity,row)
        return None

    def window_result(self,event_id,result):
        with self.lock:
            for row in reversed(self.requests.values()):
                if row['event_id']==event_id:
                    row['window']={key:result[key] for key in ('window_foreground_verified','window_reason','command','message') if key in result}
                    return

    def public(self,identity,row):
        messages={'queued':'会话定位请求已排队，等待产生该动作的 OpenCode 实例接收。',
                  'delivered':'OpenCode 插件已接收定位请求，等待接口回执。',
                  'dispatched':'OpenCode 会话选择接口已接受请求；尚未验证具体标签页显示，未发送消息。同一服务的多个 TUI 可能同时切换。',
                  'failed':'OpenCode 会话选择失败；请在原客户端手动定位。',
                  'superseded':'已由你随后点击的定位请求替代，不再等待这次请求。',
                  'expired':'会话定位请求已过期，可能实例离线；请核对原客户端后重试。'}
        result={'kind':'opencode_session','request_id':identity,'state':row['state'],
                'requested':row['state']=='dispatched','visible_session_verified':False,'message':messages[row['state']]}
        if row['state'] in ('failed','expired'):result['command']='opencode --session '+row['session']
        if row.get('window'):
            result.update({key:value for key,value in row['window'].items() if key!='message'})
            result['message']+=' '+row['window'].get('message','')
        return result

    def forget(self,event_ids):
        with self.lock:
            identities=set(event_ids)
            if self.store:self.store.forget(identities)
            for identity in identities:self.origins.pop(identity,None)
            self.requests=OrderedDict((k,v) for k,v in self.requests.items() if v['event_id'] not in identities)
