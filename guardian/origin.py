"""Action-bound source locators. Never accepts a URL or command from clients."""
from collections import OrderedDict
import os
import re
import threading
import time
import uuid
from .source_window import SourceWindows
from .adapter_contracts import capabilities


def pi_session_id(value):
    # Pi treats a .jsonl suffix as a path before attempting exact ID lookup.
    return isinstance(value,str) and not value.endswith('.jsonl') and bool(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?',value))


class Origins:
    def __init__(self,store=None):
        self.store=store
        self.rows=OrderedDict()
        self.windows=SourceWindows()
        self.window_rows={}
        self.resume_rows={}
        self.lock=threading.Lock()

    def remember(self,event,session,source_pid=None,*,resume_available=False):
        if event.get('is_demo'):return
        adapter=event.get('source_adapter')
        if not isinstance(session,str):return
        if adapter in ('codex-hook','claude-hook'):
            try:
                if str(uuid.UUID(session))!=session.lower():return
            except ValueError:return
        elif adapter=='opencode-plugin':
            if not re.fullmatch(r'ses_[A-Za-z0-9]{8,128}',session):return
        elif adapter=='pi-extension':
            if not pi_session_id(session):return
        else:return
        with self.lock:
            if event['event_id'] in self.rows:return
            self.rows[event['event_id']]=(adapter,session,time.monotonic()+86400)
            target=(self.windows.capture(source_pid,source_names=('opencode.exe','node.exe','bun.exe'))
                    if adapter=='opencode-plugin' else self.windows.capture(source_pid,source_names=('node.exe','bun.exe','pi.exe'))
                    if adapter=='pi-extension' else self.windows.capture(source_pid))
            if target:self.window_rows[event['event_id']]=target
            if adapter=='pi-extension':self.resume_rows[event['event_id']]=resume_available is True
            stored={'window':target,'resume_available':resume_available is True} if adapter=='pi-extension' else target
            if self.store:self.store.put('origin',event['event_id'],[adapter,session,stored])
            self.rows.move_to_end(event['event_id'])
            while len(self.rows)>2000:
                identity,_=self.rows.popitem(last=False);self.window_rows.pop(identity,None);self.resume_rows.pop(identity,None)

    def forget(self,event_ids):
        with self.lock:
            for event_id in event_ids:self.rows.pop(event_id,None);self.window_rows.pop(event_id,None);self.resume_rows.pop(event_id,None)
            if self.store:self.store.forget(event_ids)

    def locate(self,event):
        if not event.get('is_demo') and capabilities(event.get('source_adapter'))['navigation']=='unsupported':
            return {'kind':'unsupported','visible_session_verified':False,
                'message':'该客户端适配器暂未实现原窗口或会话导航；请按事件时间和工具在原客户端核对。这不代表动作检查未接入。'}
        with self.lock:
            row=self.rows.get(event['event_id'])
            if row is None and self.store:
                saved=self.store.get('origin',event['event_id'])
                if saved:
                    value,remaining=saved
                    if isinstance(value,list) and len(value)==3:
                        adapter,session,window=value
                        valid=(isinstance(session,str) and (
                            adapter in ('claude-hook','codex-hook') and re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',session)
                            or adapter=='opencode-plugin' and re.fullmatch(r'ses_[A-Za-z0-9]{8,128}',session)
                            or adapter=='pi-extension' and pi_session_id(session)))
                        if valid:
                            row=(adapter,session,time.monotonic()+remaining)
                            self.rows[event['event_id']]=row
                            if adapter=='pi-extension':
                                metadata=window if isinstance(window,dict) else {}
                                self.resume_rows[event['event_id']]=metadata.get('resume_available') is True
                                window=metadata.get('window')
                            if isinstance(window,dict) and set(window) in ({'pid','created','hwnd'},{'pid','created','hwnd','console_hwnd','console_pid','console_created'}) and all(type(v) is int and v>0 for v in window.values()):
                                self.window_rows[event['event_id']]=window
                            while len(self.rows)>2000:
                                identity,_=self.rows.popitem(last=False);self.window_rows.pop(identity,None);self.resume_rows.pop(identity,None)
            if not row or row[2]<=time.monotonic():
                self.rows.pop(event['event_id'],None)
                self.window_rows.pop(event['event_id'],None)
                self.resume_rows.pop(event['event_id'],None)
                return {'kind':'unavailable','message':'该事件没有有效的原会话定位信息（旧版事件或超过 24 小时）。请依据事件时间与工具在原客户端核对；新版本记录的定位信息可跨守卫重启保留。'}
            adapter,session,_=row
            if event.get('is_demo') or event.get('source_adapter')!=adapter:raise ValueError('Source mismatch')
            if adapter=='pi-extension':
                result={'kind':'manual_resume','visible_session_verified':False,
                    'message':'可尝试前置已识别的 Pi 关联终端，标签页仍需核对。该动作没有已确认的持久会话，不能提供可靠恢复命令。'}
                if self.resume_rows.get(event['event_id']):
                    result.update(command='pi --session '+session,
                        message='可尝试前置 Pi 关联终端。恢复命令绑定完整会话 ID，仅供在原项目目录及相同 Pi 配置/会话存储环境中手动运行；不同目录可能提示分叉，不能当成返回原会话。不会自动运行或发送消息。')
                return result
            if adapter=='codex-hook':
                if event['event_id'] in self.window_rows:
                    return {'kind':'manual_resume','command':'codex resume '+session,
                        'message':'已识别关联终端，尝试返回原终端窗口；具体标签页仍需核对。恢复命令仅供手动使用。'}
                return {'kind':'codex_thread','uri':'codex://threads/'+session,'command':'codex resume '+session,
                    'message':'使用 Codex 桌面会话链接。客户端是否显示该会话仍需你核对；不会发送提示词或恢复执行。'}
            command=('claude --resume ' if adapter=='claude-hook' else 'opencode --session ')+session
            return {'kind':'manual_resume','command':command,
                'message':'当前客户端没有已验证的原窗口激活接口。可先在原客户端的会话列表定位；以下命令仅供你手动恢复会话，不会自动执行，也不表示原窗口已激活。'}

    def open(self,event):
        target=self.locate(event)
        if target['kind']=='manual_resume' and event.get('source_adapter') in ('claude-hook','codex-hook','opencode-plugin','pi-extension'):
            with self.lock:window=self.window_rows.get(event['event_id'])
            if window:
                result=self.windows.activate(window)
                reasons={'console_binding_changed':'原控制台关联已变化，未尝试切换其他窗口。',
                         'closed_or_ambiguous':'原窗口已关闭或身份不再匹配，未尝试切换其他窗口。',
                         'os_not_confirmed':'Windows 未确认窗口前置；请再次点击定位，或手动切回原终端。',
                         'unavailable':'无法读取原窗口状态，请手动切回原终端。'}
                message='已返回关联终端窗口；多标签终端仍需核对当前标签页。未发送消息或恢复执行。' if result['window_foreground_verified'] else reasons.get(result.get('window_reason'),'未确认原窗口前置，请手动核对。')
                if event.get('source_adapter')=='pi-extension':message+=' '+target['message']
                return {**target,**result,'visible_session_verified':False,'message':message}
        if target['kind']!='codex_thread':return target
        if os.name!='nt':return {**target,'requested':False,'message':'此版本只在 Windows 提供桌面会话链接启动。'}
        try:os.startfile(target['uri'])
        except OSError:return {**target,'requested':False,'message':'系统未能打开 Codex 会话链接。可在桌面会话列表手动定位，或在已安装 Codex CLI 的终端手动使用下方恢复命令；不会自动执行。'}
        return {**target,'requested':True,'visible_session_verified':False,
            'message':'已向 Codex 发出打开原会话的请求；未自动发送消息或恢复动作。请核对客户端显示的会话。'}
