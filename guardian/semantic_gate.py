"""Opt-in, process-local pre-tool experiment; never an implicit model upload."""
import threading
import uuid
import time
from .semantic import analyze, PROMPT_VERSION
from .policy import CLIENTS
from .reviewer import PORTS, Cancellation
from .rules import assess, rule_input


class SemanticGate:
    def __init__(self,slot=None):
        self.lock=threading.Lock()
        self.slot=slot if slot is not None else threading.BoundedSemaphore(1)
        self.revision=uuid.uuid4().hex
        self.config=None
        self.preparation={'status':'not_prepared'}
        self.prepared_until=0
        self.worker=None
        self.cancel=None

    def snapshot(self):
        with self.lock:
            return {'enabled':self.config is not None,'configuration':dict(self.config) if self.config else None,
                    'experimental':True,'persistent':False,'timeout_seconds':1.5,
                    'task_context_available':False,'prompt_version':PROMPT_VERSION,
                    'preparation':{**self.preparation,'ready':self.preparation['status']=='ready' and time.monotonic()<self.prepared_until}}

    def configure(self,data,before_change=None):
        if data.get('enabled') is False:
            config=None
        else:
            if data.get('enabled') is not True or data.get('confirmed_raw_local_processing') is not True:
                raise ValueError('Explicit local parameter processing consent required')
            clients=data.get('clients')
            if not isinstance(clients,list) or not clients or any(c not in CLIENTS for c in clients):
                raise ValueError('Select supported adapters')
            port=data.get('port');model=data.get('model')
            if type(port) is not int or port not in PORTS or not isinstance(model,str) or not 0<len(model)<=160 or 'cloud' in model.lower():
                raise ValueError('Select local model')
            runtime=data.get('runtime','cpu')
            if runtime not in ('cpu','auto'):raise ValueError('Invalid runtime')
            config={'clients':sorted(set(clients)),'port':port,'model':model,'runtime':runtime}
        with self.lock:
            if before_change:before_change()
            if self.cancel:self.cancel.cancel()
            self.config=config
            self.revision=uuid.uuid4().hex
            self.preparation={'status':'not_prepared'}
            self.prepared_until=0
        return self.snapshot()

    def prepare(self,confirmed):
        if confirmed is not True:raise ValueError('Confirm local synthetic warmup')
        with self.lock:
            if not self.config:raise ValueError('Configure the experiment first')
            if self.worker and self.worker.is_alive():raise ValueError('Preparation still running')
            if not self.slot.acquire(blocking=False):raise ValueError('Model is busy')
            config=dict(self.config);revision=self.revision
            cancel=Cancellation();self.cancel=cancel
            self.preparation={'status':'preparing'};self.prepared_until=0
            self.worker=threading.Thread(target=self._prepare,args=(config,revision,cancel),daemon=True)
            try:self.worker.start()
            except Exception:
                self.preparation={'status':'failed'};self.slot.release();raise
        return self.snapshot()

    def invalidate_preparation(self):
        # Another Guardian model consumer may change resident model/device.
        with self.lock:
            self.prepared_until=0
            self.preparation={'status':'not_prepared','reason':'other_model_work'}

    def _prepare(self,config,revision,cancel):
        try:
            result=analyze('Write',{'file_path':'synthetic/report.txt','content':'Synthetic preparation only.'},
                           '保存合成测试文字到本地报告，不执行任何真实工具。',port=config['port'],model=config['model'],
                           runtime=config['runtime'],timeout=60,cancel=cancel)
            with self.lock:
                if revision==self.revision and not cancel.cancelled:
                    ready=result.get('status')=='completed'
                    self.preparation={'status':'ready' if ready else 'failed','check_status':result.get('status','unavailable_or_invalid'),
                                      'latency_ms':result.get('latency_ms',0)}
                    self.prepared_until=time.monotonic()+240 if ready else 0
        except Exception:
            with self.lock:
                if revision==self.revision:self.preparation={'status':'failed'}
        finally:self.slot.release()

    def close(self):
        with self.lock:
            if self.cancel:self.cancel.cancel()
            self.revision=uuid.uuid4().hex
            worker=self.worker
        if worker:worker.join(timeout=2)

    def evaluate(self,payload,adapter,*,demo=False):
        with self.lock:
            config=dict(self.config) if self.config else None
            revision=self.revision
            prepared=self.preparation['status']=='ready' and time.monotonic()<self.prepared_until
        result={'status':'disabled','policy_key':revision,'prompt_version':PROMPT_VERSION,
                'scope':'tool_parameters_without_user_task','task_context_available':False}
        if not config or adapter not in config['clients'] or demo:return result
        tool,args=payload.get('tool_name'),payload.get('tool_input')
        if not isinstance(tool,str) or not isinstance(args,dict):raise ValueError('Invalid tool payload')
        if any(r['action'] in ('deny','review') for r in assess(tool,args)):
            return {**result,'status':'skipped_rule_decision'}
        canonical,_=rule_input(tool,args)
        if canonical=='Read':return {**result,'status':'skipped_read_only'}
        if not prepared:return {**result,'status':'model_not_prepared','requires_review':True}
        if not self.slot.acquire(blocking=False):return {**result,'status':'busy','requires_review':True}
        try:
            candidate=analyze(tool,args,'用户任务未提供；仅根据工具参数检查动作风险，不推定用户授权。',
                              port=config['port'],model=config['model'],runtime=config['runtime'],timeout=1.5)
            # Whitelist model-derived evidence; no raw arguments, text, URL or model name persisted.
            for key in ('status','assessment','categories','latency_ms','model_digest'):
                if key in candidate:result[key]=candidate[key]
            # This experiment has no trusted user task/authorization input. A
            # model's absence of additional signals cannot supply that authority.
            # Native confirmation or an exact one-use grant remains necessary.
            result['requires_review']=True
            if candidate.get('status')=='completed' and candidate.get('assessment')=='no_additional_signal':
                result['review_reason']='missing_task_authorization'
            if candidate.get('status')=='completed':
                with self.lock:
                    if self.revision==revision:self.prepared_until=time.monotonic()+240
            return result
        except Exception:
            return {**result,'status':'unavailable_or_invalid','requires_review':True}
        finally:self.slot.release()

    def finalize(self,result):
        # Called under the server history lock, shared with config mutations.
        with self.lock:
            if result['policy_key']!=self.revision:
                return {**result,'policy_key':self.revision,'status':'configuration_changed',
                        'requires_review':True,'assessment':'uncertain','categories':['insufficient_context']}
        return result
