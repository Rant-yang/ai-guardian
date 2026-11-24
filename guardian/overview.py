"""Read-only diagnostic projection. Configured, observed and online are separate facts."""
from datetime import datetime, timezone
from .adapter_contracts import INTEGRATION_ADAPTERS, capabilities, lifecycle

ADAPTERS=INTEGRATION_ADAPTERS


def compact_event(event):
    """Only fields consumed by compact lists, filters, alerts and event navigation."""
    keys=('event_id','session_id','is_demo','source_adapter','adapter_id','occurred_at','tool_name',
          'mode','verdict','findings','execution_state','enforcement_status','approval_status',
          'approval_revocation_reason','decision_state','native_confirmation','output_scan_at','output_scan',
          'source_navigation','user_feedback')
    result={key:event[key] for key in keys if key in event}
    if 'rule_coverage' in event:
        result['rule_coverage']={key:event['rule_coverage'][key] for key in ('level','canonical_tool') if key in event['rule_coverage']}
    if event.get('explanations'):result['explanations']=[{'title':event['explanations'][0].get('title','')}]
    return result


def build(events,connections,integrations,*,started_at=None,now=None,modes=None):
    now=now or datetime.now(timezone.utc)
    def timestamp(value):
        try:
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (ValueError,TypeError,AttributeError):return None
    sessions={}
    for event in events:
        adapter=event.get('source_adapter',event['adapter_id'])
        key=f"{int(event['is_demo'])}:{adapter}:{event['session_id']}"
        row=sessions.setdefault(key,dict(key=key,adapter=adapter,session_id=event['session_id'],
            is_demo=event['is_demo'],last_event=event['occurred_at'],events=0,risks=0))
        row['events']+=1
        row['risks']+=bool(event['findings'] or event.get('output_scan',{}).get('findings'))
        row['last_event']=max(row['last_event'],event['occurred_at'])
    diagnostics=[]
    for item in integrations:
        adapter=ADAPTERS.get(item['id'])
        if not adapter:continue
        real=sorted((e for e in events if e.get('source_adapter',e.get('adapter_id'))==adapter and not e['is_demo']),
                    key=lambda e:e['occurred_at'],reverse=True)
        observed=real[0] if real else None
        current=[e for e in real if timestamp(e['occurred_at']) and
                 (started_at is None or timestamp(e['occurred_at'])>=started_at)]
        receipts=[e for e in real if e.get('execution_state') in ('blocked','tool_returned','succeeded','failed')]
        # A successful old receipt must not hide a different action/session whose
        # result is unknown. Thirty seconds is a diagnostic grace period, not an
        # execution timeout: long-running tools can legitimately remain pending.
        waiting_decision=[e for e in current if e.get('verdict')=='review' and
                          (e.get('approval_status')=='pending' or
                           (e.get('decision_state')=='awaiting_client_confirmation' and
                            e.get('approval_status')!='revoked' and
                            (e.get('approval_expires_at') or 0)>now.timestamp() and
                            e.get('execution_state','unknown')=='unknown'))]
        waiting_retry=[e for e in current if e.get('approval_status')=='approved']
        outstanding=[e for e in current if e.get('execution_state','unknown')=='unknown' and
                     e not in waiting_decision and e not in waiting_retry]
        overdue=[e for e in outstanding if (now-timestamp(e['occurred_at'])).total_seconds()>=30]
        gap_sessions=len({e['session_id'] for e in overdue})
        contract=capabilities(adapter)
        receipt_supported=contract['receipt']
        if not receipt_supported:
            outstanding=[];overdue=[];gap_sessions=0
        heartbeat=contract['heartbeat']
        online=sum(c['online'] and c['adapter']==adapter for c in connections)
        matching_installations=sum(c['online'] and c['adapter']==adapter and c.get('installation_binding')=='matched_local_configuration' for c in connections)
        unbound_installations=sum(c['online'] and c['adapter']==adapter and c.get('installation_binding')!='matched_local_configuration' for c in connections)
        stale_revision=sum(c['online'] and c['adapter']==adapter and not c.get('revision_current',False) for c in connections) if heartbeat else 0
        if item.get('error') or item.get('conflict'):state='config_error'
        elif item.get('outdated'):state='upgrade_required'
        elif not item['installed']:state='disabled'
        elif online:state='online'
        elif observed:state='observed'
        else:state='awaiting_event'
        if state in ('config_error','upgrade_required'):readiness=state
        elif item.get('partial'):readiness='partial_config'
        elif state=='disabled':readiness=state
        elif adapter=='codex-mcp':readiness='demo_only'
        elif heartbeat and any(c['adapter']==adapter for c in connections) and not online:readiness='heartbeat_lost'
        elif stale_revision:readiness='adapter_refresh_required'
        elif not current:readiness='awaiting_event' if not observed else 'history_only'
        elif overdue:readiness='receipt_gaps'
        elif (modes or {}).get(adapter) and observed.get('mode')!=(modes or {})[adapter]:readiness='mode_unverified'
        elif not receipt_supported:readiness='checks_only'
        elif not online and observed and timestamp(observed['occurred_at']) and (now-timestamp(observed['occurred_at'])).total_seconds()>300:readiness='idle_unverified'
        else:readiness='receiving' if any(e in receipts for e in current) else 'awaiting_receipt'
        age=max(0,int((now-timestamp(observed['occurred_at'])).total_seconds())) if observed and timestamp(observed['occurred_at']) else None
        next_steps={
            'disabled':'在扫描向导中预览并启用接入。',
            'partial_config':'接入缺少部分检查、回执或加载关联配置；在扫描向导预览接入，可仅补齐缺失项。',
            'config_error':'核对配置冲突；当前不能确认接入有效。',
            'upgrade_required':'核对旧版接入与当前安装位置，避免重复钩子。',
            'demo_only':'合成 MCP 演示不证明原生工具已受监督；请检查 Codex 原生 Hooks。',
            'heartbeat_lost':'OpenCode 心跳超时；可能已关闭或断连，请核对客户端。',
            'adapter_refresh_required':'有在线 OpenCode 实例未确认加载当前适配器；完成手头任务后重启对应客户端，再验证新动作。无需覆盖模型配置。',
            'history_only':'只有本次服务启动前的记录，请在客户端做一次无害读取验证。',
            'awaiting_event':'重启客户端并核对原生信任提示，再做一次无害读取。',
            'awaiting_receipt':'已收到检查，尚无本次启动后的执行回执；请在客户端核对动作结果。',
            'receipt_gaps':'有动作超过 30 秒未收到回执；可能仍在执行或客户端未上报，请核对对应会话。此状态不代表执行失败。',
            'checks_only':'本适配目前只验证执行前检查，不支持精确关联的执行回执；请在原客户端确认结果。',
            'mode_unverified':'设置模式与最近检查模式不同；请在原客户端重新发起一次无害读取验证新模式。',
            'idle_unverified':'超过五分钟没有新动作，无法据此确认当前在线；空闲不等于断线，需要时可发起读取验证。',
            'receiving':'检查与回执均已收到；仍仅覆盖适配器支持的工具。'}
        diagnostics.append(dict(client=item['id'],adapter=adapter,state=state,readiness=readiness,online_instances=online,
            configuration_matched_instances=matching_installations,configuration_unmatched_instances=unbound_installations,
            capabilities=contract,lifecycle=lifecycle(configured=item['installed'],readiness=readiness,online=online,capabilities=contract),
            outdated_online_instances=stale_revision,
            last_event=observed['occurred_at'] if observed else None,
            last_event_age_seconds=age,events_in_window=len(real),events_since_start=len(current),
            receipts_in_window=len(receipts),receipts_since_start=sum(e in receipts for e in current),
            outstanding_actions_since_start=len(outstanding),receipt_gaps_since_start=len(overdue),
            receipt_gap_sessions=gap_sessions,waiting_decisions_since_start=len(waiting_decision),
            authorized_retries_since_start=len(waiting_retry),
            receipt_gap_event_ids=[e['event_id'] for e in overdue[:10]],
            generic_only_in_window=sum(e.get('rule_coverage',{}).get('level')=='generic_only' for e in real),
            heartbeat_supported=heartbeat,receipt_supported=receipt_supported,trust_status='unknown',
            configured_mode=(modes or {}).get(adapter),last_observed_mode=observed.get('mode') if observed else None,
            next_step=next_steps[readiness],
            configuration_issues=item.get('configuration_issues',[]),
            coverage=item.get('coverage','配置不可用'),enforcement_verified=False))
    return dict(events=events,connections=connections,integrations=integrations,
        sessions=list(sessions.values()),diagnostics=diagnostics,event_window=200,
        generated_at=now.isoformat(),service_started_at=started_at.isoformat() if started_at else None)
