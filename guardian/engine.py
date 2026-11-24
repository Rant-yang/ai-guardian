import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from functools import wraps


def atomic_write(method):
    """Keep every state change and its authorization effects in one transaction."""
    @wraps(method)
    def wrapped(self,*args,**kwargs):
        with self.lock:
            self._require_storage()
            try:
                result=method(self,*args,**kwargs)
                if self.db.in_transaction:
                    self.db.commit()
                    self.storage_error=False
                return result
            except BaseException as error:
                if isinstance(error,sqlite3.Error):
                    self.storage_error=True
                    self.storage_failures+=1
                try:self.db.rollback()
                except sqlite3.Error:
                    self.storage_broken=True
                    self.storage_error=True
                raise
    return wrapped


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


from .rules import assess, preview, coverage, VERSION
from .output_scan import validate_scan
from .adapter_contracts import capabilities


def detect(tool, args):
    return list(dict.fromkeys(r['id'] for r in assess(tool,args)))


class Engine:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.history_plans = {}
        self.storage_error=False
        self.storage_broken=False
        self.storage_failures=0
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE, data TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS approvals (event_id TEXT PRIMARY KEY, binding TEXT, expires REAL, state TEXT)')
        self.db.execute("CREATE INDEX IF NOT EXISTS events_event_id ON events(json_extract(data,'$.event_id'))")
        # Clean up legacy orphan grants once, rather than scanning history on every action.
        self.db.execute("DELETE FROM approvals WHERE event_id NOT IN (SELECT json_extract(data,'$.event_id') FROM events)")
        # Preserve terminal states from older versions before transient grants expire.
        for event_id,state in self.db.execute("SELECT event_id,state FROM approvals WHERE state IN ('consumed','revoked')").fetchall():
            self._persist_authorization_state(event_id,state)
        self.db.commit()

    def _require_storage(self):
        if self.storage_broken:raise sqlite3.OperationalError('Storage requires service restart')

    def storage_status(self):
        with self.lock:
            return {'status':'restart_required' if self.storage_broken else 'write_failed' if self.storage_error else 'ready',
                    'write_failures':self.storage_failures}

    @atomic_write
    def evaluate(self, payload, *, demo=False, mode='protect', adapter='claude-hook', phase='before_tool', semantic=None):
        if adapter not in ('pi-extension', 'qoder-hook', 'claude-hook', 'opencode-plugin', 'gemini-hook', 'codex-mcp', 'codex-hook', 'ollama-local'):
            raise ValueError('unsupported adapter')
        if phase not in ('before_tool','model_input'):
            raise ValueError('unsupported phase')
        if mode not in ('protect', 'observe'):
            raise ValueError('invalid mode')
        native_confirmation = capabilities(adapter)['approval'] == 'native_confirmation'
        if not isinstance(payload, dict) or not isinstance(payload.get('tool_input'), dict):
            raise ValueError('tool_input must be an object')
        if not all(isinstance(payload.get(k), str) and 0 < len(payload[k]) <= 200 for k in ('session_id', 'tool_use_id', 'tool_name')):
            raise ValueError('missing or invalid identity')
        tool = payload['tool_name']
        cwd=payload.get('cwd')
        if cwd is not None and (not isinstance(cwd,str) or not 0<len(cwd)<=4096 or '\x00' in cwd):
            raise ValueError('invalid working directory context')
        context_hash=digest(['cwd-v1',cwd])
        # Identity binds immutable arguments. Same call ID with changed args is rejected.
        key = digest([demo, adapter, payload['session_id'], payload['tool_use_id']])
        args_hash = digest([tool, payload['tool_input']])
        start = time.perf_counter()
        with self.lock:
            row = self.db.execute('SELECT data FROM events WHERE key=?', (key,)).fetchone()
            if row:
                event = json.loads(row[0])
                if event['arguments_digest'] != args_hash or event['mode'] != mode or event.get('execution_context_digest')!=context_hash:
                    raise ValueError('call identity reused with changed arguments')
                return event
            matched = assess(tool,payload['tool_input'])
            if semantic and semantic.get('requires_review'):
                matched.append(dict(id='semantic_review',title='本地语义检查需人工确认',action='review',
                    reason=('模型未发现额外线索，但缺少用户任务授权信息，仍需人工确认；不是已证实的危险。'
                            if semantic.get('review_reason')=='missing_task_authorization'
                            else '模型提示风险或未能完成有效判断；不代表危险已被证实。'),
                    impact='执行前需要人工核对工具参数与任务授权；不会自动重放动作。'))
            findings = list(dict.fromkeys(r['id'] for r in matched))
            proposed = max((r['action'] for r in matched),key={'warn':1,'review':2,'deny':3}.get,default='pass')
            binding = digest([adapter,payload['session_id'],tool,args_hash,VERSION,semantic.get('policy_key') if semantic else None,context_hash])
            grant = None
            if not demo and mode=='protect' and proposed=='review':
                self.db.execute('DELETE FROM approvals WHERE expires<=?',(time.time(),))
                grant=self.db.execute("SELECT event_id FROM approvals WHERE binding=? AND state='approved' AND expires>? ORDER BY expires LIMIT 1",(binding,time.time())).fetchone()
                if grant:
                    self.db.execute("UPDATE approvals SET state='consumed' WHERE event_id=?",(grant[0],))
                    self._persist_authorization_state(grant[0],'consumed')
            verdict = ('pass' if grant else proposed) if mode == 'protect' else ('warn' if findings else 'pass')
            event = dict(event_id=str(uuid.uuid4()), session_id=digest(payload['session_id'])[:16],
                         occurred_at=datetime.now(timezone.utc).isoformat(), tool_name=tool,
                         arguments_digest=args_hash,execution_context_digest=context_hash,
                         working_directory_context='reported' if cwd is not None else 'unreported',
                         phase=phase, adapter_id='demo' if demo else adapter,
                         source_adapter=adapter, is_demo=demo, mode=mode, verdict=verdict, proposed_verdict=proposed,
                         findings=findings, enforcement_status='decision_only', detector='rules/'+VERSION,
                         policy_version=VERSION, latency_ms=round((time.perf_counter()-start)*1000, 3),
                         latency_scope='engine_rules_before_persistence_not_http',
                         limitations=['heuristic_rules_only', 'semantic_model_unavailable', 'unmediated_tools_not_covered'])
            if semantic:
                event['semantic_check']={k:v for k,v in semantic.items() if k!='policy_key'}
                if semantic['status']=='completed':
                    event['limitations']=['experimental_semantic_no_task_context','unmediated_tools_not_covered']
                    event['detector']+='+semantic/'+semantic['prompt_version']
            event.update(action_preview=preview(tool,payload['tool_input']),
                         rule_coverage=coverage(tool,payload['tool_input']),
                         explanations=[dict(id=r['id'],title=r['title'],reason=r['reason'],impact=r['impact'],action=r['action']) for r in matched],
                         review_binding=binding,
                         approval_status='consumed' if grant else 'pending' if verdict=='review' and not demo and not native_confirmation else None,
                         approval_expires_at=time.time()+300 if verdict=='review' else None,
                         decision_state='authorized_once' if grant else 'awaiting_client_confirmation' if verdict=='review' and native_confirmation else 'awaiting_approval' if verdict=='review' else 'denied' if verdict=='deny' else 'checked',
                         execution_state='unknown', approved_from=grant[0] if grant else None)
            cursor = self.db.execute('INSERT INTO events(key,data) VALUES (?,?)', (key, json.dumps(event)))
            event['sequence'] = cursor.lastrowid
            self.db.execute('UPDATE events SET data=? WHERE key=?', (json.dumps(event), key))
            cutoff=cursor.lastrowid-2000
            expired=[row[0] for row in self.db.execute("SELECT json_extract(data,'$.event_id') FROM events WHERE seq<=?",(cutoff,))]
            if expired:
                self.db.executemany('DELETE FROM approvals WHERE event_id=?',[(event_id,) for event_id in expired])
                self.db.execute('DELETE FROM events WHERE seq<=?',(cutoff,))
            return event

    @atomic_write
    def demo_outcome(self, event_id, status):
        with self.lock:
            for seq, raw in self.db.execute('SELECT seq,data FROM events').fetchall():
                event = json.loads(raw)
                if event['event_id'] == event_id and event['is_demo']:
                    event['enforcement_status'] = status
                    self.db.execute('UPDATE events SET data=? WHERE seq=?', (json.dumps(event), seq))
                    return event
        raise ValueError('demo event not found')

    def _event(self, event_id):
        self._require_storage()
        if not isinstance(event_id,str):raise ValueError('invalid event identity')
        row=self.db.execute("SELECT seq,data FROM events WHERE json_extract(data,'$.event_id')=?",(event_id,)).fetchone()
        if row:return row[0],json.loads(row[1])
        raise ValueError('unknown event')

    def _save(self, seq, event):
        self.db.execute('UPDATE events SET data=? WHERE seq=?',(json.dumps(event),seq))
        return event

    def _persist_authorization_state(self,event_id,state):
        # Caller owns the transaction; this must roll back with grant consumption.
        seq,event=self._event(event_id)
        event['approval_status']=state
        self._save(seq,event)

    @atomic_write
    def approve(self, event_id, decision):
        if decision not in ('approve','reject'):raise ValueError('invalid approval')
        with self.lock:
            seq,event=self._event(event_id)
            if event.get('policy_version')!=VERSION:raise ValueError('Rule policy changed; check action again')
            if event['is_demo'] or event.get('approval_status')!='pending' or event.get('approval_expires_at',0)<=time.time():
                raise ValueError('not pending or expired')
            state='approved' if decision=='approve' else 'rejected'
            # Repeated identical pending calls cannot create multiple outstanding grants.
            if self.db.execute("SELECT 1 FROM approvals WHERE binding=? AND state='approved' AND expires>?",(event['review_binding'],time.time())).fetchone():
                raise ValueError('an authorization already exists for this action')
            self.db.execute('INSERT INTO approvals VALUES (?,?,?,?)',(event_id,event['review_binding'],event['approval_expires_at'],state))
            event['approval_status']=state
            event['decision_state']='authorized_retry_required' if decision=='approve' else 'denied'
            return self._save(seq,event)

    @atomic_write
    def revoke_approvals(self,reason='policy_changed'):
        if reason not in ('policy_changed','semantic_changed','service_restarted'):raise ValueError('Invalid revocation reason')
        with self.lock:
            rows=self.db.execute("SELECT seq,data FROM events WHERE json_extract(data,'$.approval_status') IN ('pending','approved') OR json_extract(data,'$.decision_state')='awaiting_client_confirmation'").fetchall()
            for seq,raw in rows:
                event=json.loads(raw)
                if event.get('approval_expires_at',0)<=time.time():continue
                event.update(approval_status='revoked',approval_revocation_reason=reason)
                self._save(seq,event)
            self.db.execute("UPDATE approvals SET state='revoked' WHERE state='approved' AND expires>?",(time.time(),))

    @atomic_write
    def native_confirmation(self, adapter, session, call_id, event_id, binding, outcome):
        """Audit a client's native prompt; never create a reusable retry grant."""
        if outcome not in ('confirmed','not_confirmed'):raise ValueError('invalid confirmation')
        if capabilities(adapter)['approval']!='native_confirmation':raise ValueError('unsupported confirmation')
        key=digest([False,adapter,session,call_id])
        row=self.db.execute('SELECT seq,data FROM events WHERE key=?',(key,)).fetchone()
        if not row:raise ValueError('unknown call')
        seq,raw=row;event=json.loads(raw)
        if event['event_id']!=event_id or event.get('review_binding')!=binding:
            raise ValueError('confirmation identity mismatch')
        if event['mode']!='protect' or event['verdict']!='review':raise ValueError('not a native review')
        if outcome=='confirmed' and (event.get('policy_version')!=VERSION or
                event.get('approval_status')=='revoked' or event.get('approval_expires_at',0)<=time.time()):
            raise ValueError('confirmation expired or revoked')
        previous=event.get('native_confirmation')
        if previous:
            if previous['outcome']!=outcome:raise ValueError('conflicting confirmation')
            return event
        if event.get('execution_state')!='unknown':raise ValueError('action already finished')
        event['native_confirmation']={'outcome':outcome,'source':adapter,
            'reported_at':datetime.now(timezone.utc).isoformat()}
        event['decision_state']='authorized_once' if outcome=='confirmed' else 'denied'
        return self._save(seq,event)

    @atomic_write
    def receipt(self, adapter, session, call_id, status, output_scan=None):
        if status not in ('blocked','tool_returned','succeeded','failed'):raise ValueError('invalid receipt')
        key=digest([False,adapter,session,call_id])
        with self.lock:
            row=self.db.execute('SELECT seq,data FROM events WHERE key=?',(key,)).fetchone()
            if not row:raise ValueError('unknown call')
            seq,raw=row;event=json.loads(raw)
            if status in ('succeeded','failed','tool_returned') and event['verdict']=='deny':raise ValueError('receipt contradicts denial')
            if status!='blocked' and event.get('native_confirmation',{}).get('outcome')=='not_confirmed':
                raise ValueError('receipt contradicts native confirmation')
            if event.get('execution_state','unknown') not in ('unknown',status):raise ValueError('conflicting receipt')
            if output_scan is not None:
                scan=validate_scan(output_scan)
                previous=event.get('output_scan')
                if previous and previous['status']=='scanned' and previous!=scan:raise ValueError('Conflicting output scan')
                event['output_scan']=scan
                if scan['status']=='scanned':event.setdefault('output_scan_at',datetime.now(timezone.utc).isoformat())
            event['execution_state']=status
            event['receipt_source']=adapter
            event.setdefault('receipt_at',datetime.now(timezone.utc).isoformat())
            return self._save(seq,event)

    def events(self):
        with self.lock:
            self._require_storage()
            result=[json.loads(row[0]) for row in self.db.execute('SELECT data FROM events ORDER BY seq DESC LIMIT 200')]
            states=dict(self.db.execute('SELECT event_id,state FROM approvals'))
            for event in result:
                if event.get('approval_status') in ('pending','approved'):
                    event['approval_status']=states.get(event['event_id'],event['approval_status'])
                    if event['approval_status'] in ('pending','approved') and event.get('approval_expires_at',0)<=time.time():event['approval_status']='expired'
                    if event['approval_status'] in ('pending','approved') and event.get('policy_version')!=VERSION:
                        event.update(approval_status='revoked',approval_revocation_reason='rules_changed')
            return result

    def investigation(self,event_id):
        """Read-only, bounded same-source evidence snapshot, never an authorization."""
        from .reviewer import summary
        with self.lock:
            anchor_seq,anchor=self._event(event_id)
            if anchor['is_demo']:raise ValueError('Select a real event')
            anchor_time=datetime.fromisoformat(anchor['occurred_at']).timestamp()
            rows=self.db.execute("SELECT seq,data FROM events WHERE seq<=? ORDER BY seq DESC LIMIT 2000",(anchor_seq,)).fetchall()
            candidates=[]
            for seq,raw in rows:
                event=json.loads(raw)
                if event['is_demo'] or event['adapter_id']!=anchor['adapter_id'] or event['session_id']!=anchor['session_id']:continue
                age=anchor_time-datetime.fromisoformat(event['occurred_at']).timestamp()
                if not 0<=age<=900:continue
                candidates.append(event)
            selected=[];used=0;truncated=False
            for event in candidates:
                row={**summary(event),'event_id':event['event_id'],'occurred_at':event['occurred_at'],
                     'receipt_at':event.get('receipt_at'),'output_scan_at':event.get('output_scan_at')}
                size=len(json.dumps(row,ensure_ascii=False).encode('utf-8'))
                if len(selected)>=8 or used+size>16000:
                    truncated=True;break
                selected.append(row);used+=size
            if not selected:raise ValueError('Event exceeds investigation budget')
            selected.reverse()
            gaps=[]
            if truncated:gaps.append('context_budget')
            if any(e.get('execution_state') in (None,'unknown') for e in selected):gaps.append('missing_receipt')
            if any(e.get('output_scan',{}).get('truncated') for e in selected if e.get('output_scan')):gaps.append('output_truncated')
            if any(not e.get('output_scan') or e['output_scan'].get('status')!='scanned' for e in selected):gaps.append('output_unavailable')
            return {'anchor_event_id':event_id,'captured_at':datetime.now(timezone.utc).isoformat(),
                    'scope':'same_client_session_preceding_15_minutes','events':selected,'gaps':gaps,
                    'limits':{'events':8,'window_seconds':900,'evidence_bytes':16000,'retained_rows':2000},
                    'evidence_bytes':used,'truncated':truncated,'read_only':True,
                    'limitations':['retained_history_only','no_user_task_context','sequence_is_not_causality','not_current_authorization']}

    def get_event(self,event_id):
        if not isinstance(event_id,str):raise ValueError('Invalid event')
        with self.lock:return self._event(event_id)[1]

    @atomic_write
    def feedback(self,event_id,label,revision):
        if label not in ('false_positive','risk_confirmed','missed_risk','unsure','clear'):
            raise ValueError('Invalid feedback label')
        if type(revision) is not int or revision<0:raise ValueError('Invalid feedback revision')
        with self.lock:
            seq,event=self._event(event_id)
            if event['is_demo']:raise ValueError('Feedback is for real events only')
            if event.get('feedback_revision',0)!=revision:raise ValueError('Feedback changed; refresh first')
            if label=='clear':event.pop('user_feedback',None)
            else:
                event['user_feedback']={'label':label,'recorded_at':datetime.now(timezone.utc).isoformat(),
                                        'source':'local_user','verified':False,'policy_version':event['policy_version']}
            event['feedback_revision']=revision+1
            return self._save(seq,event)

    def export_history(self):
        # Deliberately exclude arguments, stable session hashes, bindings and model names.
        fields=('event_id','occurred_at','source_adapter','is_demo','mode','verdict',
                'proposed_verdict','findings','decision_state','execution_state','policy_version','receipt_at','user_feedback','output_scan','output_scan_at')
        with self.lock:
            self._require_storage()
            rows=[json.loads(row[0]) for row in self.db.execute('SELECT data FROM events ORDER BY seq')]
            return {'schema':'guardian-history-v1','exported_at':datetime.now(timezone.utc).isoformat(),
                    'scope':'retained_history','count':len(rows),
                    'events':[{key:event[key] for key in fields if key in event} for event in rows]}

    def preview_clear(self):
        with self.lock:
            self._require_storage()
            now=time.monotonic()
            self.history_plans={key:value for key,value in self.history_plans.items() if value[1]>now}
            if len(self.history_plans)>=16:raise ValueError('Too many history previews')
            count,sequence=self.db.execute('SELECT COUNT(*),COALESCE(MAX(seq),0) FROM events').fetchone()
            plan=str(uuid.uuid4())
            self.history_plans[plan]=(sequence,now+300)
            return {'plan_id':plan,'count':count,'expires_in_seconds':300,'preserves_new_events':True}

    @atomic_write
    def clear_history(self,plan_id,confirmed):
        if confirmed is not True or not isinstance(plan_id,str):raise ValueError('Confirmation required')
        with self.lock:
            plan=self.history_plans.pop(plan_id,None)
            if not plan or plan[1]<=time.monotonic():raise ValueError('Expired history preview')
            ids=[json.loads(row[0])['event_id'] for row in self.db.execute('SELECT data FROM events WHERE seq<=?',(plan[0],))]
            self.db.executemany('DELETE FROM approvals WHERE event_id=?',[(value,) for value in ids])
            self.db.execute('DELETE FROM events WHERE seq<=?',(plan[0],))
            return ids

    @atomic_write
    def set_review(self,event_id,result):
        with self.lock:
            seq,event=self._event(event_id)
            event['model_review']=result
            return self._save(seq,event)

    @atomic_write
    def interrupt_reviews(self):
        with self.lock:
            for seq,raw in self.db.execute('SELECT seq,data FROM events').fetchall():
                event=json.loads(raw)
                if event.get('model_review',{}).get('status') in ('queued','running'):
                    event['model_review']['status']='interrupted'
                    self.db.execute('UPDATE events SET data=? WHERE seq=?',(json.dumps(event),seq))

    def close(self):
        self.db.close()
