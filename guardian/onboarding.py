"""Explicit configuration preview and single-use confirmation; no automatic discovery writes."""
import hashlib
import re
from pathlib import Path
import secrets
import threading
import time
from .integrations import LOCK
from .config_files import check_path
from . import adapter_registry
from .installation_identity import configuration_scope
from .adapter_contracts import capabilities, native_adapter

SUPPORTED=adapter_registry.supported()


class Onboarding:
    def __init__(self,home=None):
        self.home=Path(home) if home else Path.home()
        self.plans={}
        self.lock=threading.RLock()

    def target(self,client):
        return adapter_registry.target(client,self.home)

    def fingerprint(self,client):
        target=self.target(client)
        # Refuse redirects in any existing parent, not only in the leaf file.
        check_path(target)
        return (str(target.absolute()),hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None)

    def operation(self,client,action):
        return adapter_registry.operate(client,action,self.home,bound_target=self.target(client))

    def preview(self,clients,action='install'):
        if not isinstance(clients,list) or not clients or len(clients)>len(SUPPORTED) or any(not isinstance(c,str) or c not in SUPPORTED for c in clients) or len(set(clients))!=len(clients):
            raise ValueError('请选择受支持的客户端')
        if action not in ('install','uninstall'):raise ValueError('不支持的操作')
        with self.lock,LOCK:
            rows=[];baseline={}
            for client in clients:
                baseline[client]=self.fingerprint(client)
                state=self.operation(client,'status')
                removable_semantic_conflict=(action=='uninstall' and bool(state.get('configuration_issues')) and not state.get('outdated'))
                if (state.get('conflict') or (state.get('outdated') and not state.get('upgrade_available'))) and not removable_semantic_conflict:
                    raise ValueError('已有冲突或旧版配置，请先单独处理；范围或执行方式改变的 Hook 可预览移除后重新接入')
                installed=bool(state.get('installed'))
                preflight=adapter_registry.preflight(client,state)
                target=self.target(client)
                if not installed and not state.get('partial') and not state.get('upgrade_available') and client!='opencode' and target.exists() and re.search(r'guardian[\\/]+(?:codex_)?hook\.py',target.read_text(encoding='utf-8-sig')):
                    raise ValueError('发现其他安装位置的 Guardian 入口，请先核对迁移，未追加重复钩子')
                rows.append(dict(id=client,name=SUPPORTED[client],path=str(self.target(client)),
                    change=('备份并升级兼容启动入口' if state.get('upgrade_available') else '备份并补齐接入配置' if state.get('partial') else '保留现有接入' if installed else '备份并追加接入') if action=='install' else ('仅移除 Guardian 接入' if installed or state.get('partial') or state.get('outdated') else '无须更改'),
                    warnings=preflight['warnings'],preflight=preflight,
                    installed=installed,requires_trust=adapter_registry.descriptor(client).requires_trust,restart_required=True,
                    adapter=adapter_registry.descriptor(client).adapter,
                    configuration_scope=configuration_scope(client,target),
                    capabilities=capabilities(native_adapter(client))))
            now=time.monotonic()
            self.plans={key:p for key,p in self.plans.items() if p['expiry']>now}
            if len(self.plans)>=16:raise ValueError('待确认计划过多，请稍后重试')
            token=secrets.token_urlsafe(24)
            self.plans[token]=dict(clients=clients[:],action=action,baseline=baseline,expiry=now+300)
            return dict(plan_id=token,expires_in=300,action=action,clients=rows,
                note='只修改列出的接入文件；保留模型、API 与权限设置。已有模式不变；新客户端默认观察。Codex 信任需在客户端完成。')

    def apply(self,plan_id,confirmed):
        if confirmed is not True or not isinstance(plan_id,str):raise ValueError('需要明确确认预览计划')
        with self.lock,LOCK:
            plan=self.plans.pop(plan_id,None)
            if not plan or plan['expiry']<=time.monotonic():raise ValueError('计划已过期或已使用，请重新预览')
            # Verify ALL files before changing ANY file.
            if any(self.fingerprint(c)!=plan['baseline'][c] for c in plan['clients']):
                raise ValueError('配置已发生变化，请重新预览')
            results=[]
            for client in plan['clients']:
                try:
                    if self.fingerprint(client)!=plan['baseline'][client]:
                        results.append(dict(id=client,state='failed',message='此配置在执行期间发生变化，未修改；请重新预览'));continue
                    state=self.operation(client,'status')
                    if plan['action']=='install' and state.get('installed') and not state.get('partial'):
                        results.append(dict(id=client,state='preserved',message='已有接入保留；仍需真实动作验证',preflight=adapter_registry.preflight(client,state)));continue
                    if plan['action']=='uninstall' and not state.get('installed') and not state.get('partial') and not state.get('outdated'):
                        results.append(dict(id=client,state='preserved',message='未发现 Guardian 接入，无须更改'));continue
                    self.operation(client,plan['action'])
                    checked=self.operation(client,'status')
                    complete=(bool(checked.get('installed')) and not checked.get('partial')) if plan['action']=='install' else not checked.get('installed') and not checked.get('partial')
                    if checked.get('conflict') or checked.get('outdated') or not complete:
                        results.append(dict(id=client,state='uncertain',message='写入后未确认达到预期接入状态；请重新预览核对，不自动回滚其他配置'));continue
                    results.append(dict(id=client,state='configured' if plan['action']=='install' else 'removed',
                        preflight=adapter_registry.preflight(client,checked),
                        message='配置完成；等待客户端信任/重启及真实事件验证' if plan['action']=='install' else '已移除 Guardian 项；其他配置保留'))
                except Exception:
                    try:changed=self.fingerprint(client)!=plan['baseline'][client]
                    except Exception:changed=True
                    results.append(dict(id=client,state='uncertain' if changed else 'failed',
                        message='操作中断且文件可能已变更；请重新预览核对，其他结果独立保留' if changed else '该客户端配置失败，文件未变更；请检查冲突，其他结果独立保留'))
            incomplete=[row['id'] for row in results if row['state'] in ('failed','uncertain')]
            return dict(results=results,execution_verified=False,incomplete_clients=incomplete,
                        status='partial' if incomplete and len(incomplete)<len(results) else 'incomplete' if incomplete else 'completed',
                        automatic_rollback=False)
