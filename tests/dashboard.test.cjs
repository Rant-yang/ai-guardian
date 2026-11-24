const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');

test('first connection explains automatic launch and keeps manual credentials optional',()=>{
  const html=fs.readFileSync('web/index.html','utf8');
  assert.ok(html.includes('Guardian.vbs 自动连接'));
  assert.ok(html.includes('<details id="manual-connection">'));
  assert.ok(!html.includes('<details id="manual-connection" open'));
  assert.ok(html.includes('首次使用请双击 Install.cmd'));
});

test('console keeps management and technical detail collapsed with explanations first',()=>{
  const html=fs.readFileSync('web/index.html','utf8');
  for(const id of ['connection-manager','coverage-details','engine-details','technical-details','local-review']){
    const tag=html.match(new RegExp('<details[^>]*id="'+id+'"[^>]*>'))?.[0];
    assert.ok(tag,id);assert.doesNotMatch(tag,/\sopen(?:\s|>)/);
  }
  assert.ok(html.indexOf('id="action-explanation"')<html.indexOf('id="source-controls"'));
  assert.ok(html.indexOf('id="source-controls"')<html.indexOf('id="technical-details"'));
  assert.ok(!html.includes('本轮升级后请重启'));
});

test('client overview is mode-aware and stale detail clears when switching views',async()=>{
  const t=setup();
  vm.runInContext("renderDiagnostics([{client:'claude',adapter:'claude-hook',state:'observed',readiness:'history_only',configured_mode:'observe'}])",t.context);
  const card=t.document.getElementById('client-overview').children[0];
  assert.equal(card.children[1].textContent,'陪伴观察');assert.equal(card.children[2].textContent,'仅有历史记录');
  t.document.getElementById('action-explanation').append({textContent:'old event'});
  vm.runInContext("setView('demo')",t.context);
  assert.equal(t.document.getElementById('action-explanation').children.length,0);
  t.offline(true);await vm.runInContext("token='fixture';refresh()",t.context);
  assert.match(t.document.getElementById('client-overview').children[0].textContent,/状态未确认/);
});

test('native reconnection exchanges only a one-use ticket and restores the live view',async()=>{
  const t=setup('/overlay');let tickets=0;
  const original=t.context.fetch;
  t.context.window.pywebview={api:{connection_ticket:async()=>{tickets++;return {ticket:'temporary-ticket'};}}};
  t.context.fetch=async(path,options)=>{
    if(path==='/api/connect'){
      assert.deepEqual(JSON.parse(options.body),{ticket:'temporary-ticket'});
      assert.ok(!options.headers.Authorization);
      return {ok:true,json:async()=>({token:'fixture-admin'})};
    }
    return original(path,options);
  };
  await t.document.getElementById('native-reconnect').onclick();
  assert.equal(tickets,1);
  assert.equal(vm.runInContext('connected',t.context),true);
  assert.equal(t.document.getElementById('login').hidden,true);
  assert.equal(t.document.getElementById('token').value,'');
});

test('native reconnection failure gives recovery instructions without exposing a credential',async()=>{
  const t=setup('/overlay');
  t.context.window.pywebview={api:{connection_ticket:async()=>{throw Error('fixture');}}};
  await t.document.getElementById('native-reconnect').onclick();
  assert.ok(t.document.getElementById('connection-help').textContent.includes('无需粘贴令牌'));
  assert.equal(t.document.getElementById('native-reconnect').disabled,false);
  assert.equal(t.requests.length,0);
});

test('console starts with real actions and scanning an empty stream never installs or runs demo',async()=>{
  const t=setup();assert.equal(vm.runInContext('view',t.context),'live');
  vm.runInContext('connected=true;events=[];render()',t.context);
  let scanned=0;t.document.getElementById('scan-agents').onclick=async()=>{scanned++;};
  const empty=t.document.getElementById('stream').children[0];
  await empty.children.find(c=>c.textContent==='扫描本地客户端').onclick();
  assert.equal(scanned,1);assert.equal(t.requests.length,0);
  vm.runInContext('privacyMode=true',t.context);
  await empty.children.find(c=>c.textContent==='扫描本地客户端').onclick();
  assert.equal(scanned,1);
  t.document.getElementById('demo-view').onclick();assert.equal(vm.runInContext('view',t.context),'demo');
  assert.equal(t.requests.length,0);
  const html=fs.readFileSync('web/index.html','utf8');
  assert.match(html,/<button id="live-view" class="active" aria-pressed="true">/);
});

test('one-time task context requires a send click, clears after submit and never becomes approval',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  vm.runInContext("discoveredReviewModels=[{port:11434,name:'fixture:local'}];renderModelReview(events[0])",t.context);
  t.document.getElementById('review-model').value='0';
  let host=t.document.getElementById('review-controls');
  const input=host.children.find(c=>c.className==='review-task');
  input.value='PRIVATE_TASK_FIXTURE';input.oninput();
  t.document.activeElement=input;vm.runInContext('renderModelReview(events[0])',t.context);
  assert.equal(host.children.find(c=>c.className==='review-task'),input);
  t.document.activeElement=null;
  assert.ok(!t.requests.some(r=>r.path==='/api/reviews/local'));
  assert.match(host.children.at(-1).textContent,/任务说明/);
  await host.children.at(-1).onclick();
  const sent=t.requests.find(r=>r.path==='/api/reviews/local').body;
  assert.equal(sent.task_context,'PRIVATE_TASK_FIXTURE');assert.equal(sent.task_context_confirmed,true);
  assert.equal(vm.runInContext('reviewTaskDraft',t.context),'');
  assert.ok(!t.requests.some(r=>r.path==='/api/approvals'));
});

test('task context does not follow another event, replay or recording privacy',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  vm.runInContext("renderModelReview(events[0]);reviewTaskDraft='PRIVATE';renderModelReview(events[1])",t.context);
  assert.equal(vm.runInContext('reviewTaskDraft',t.context),'');
  vm.runInContext("reviewTaskDraft='PRIVATE';applyPrivacy(true)",t.context);
  assert.equal(vm.runInContext('reviewTaskDraft',t.context),'');
  vm.runInContext("reviewTaskDraft='PRIVATE';replay={};renderModelReview(events[0])",t.context);
  assert.equal(vm.runInContext('reviewTaskDraft',t.context),'');
});

test('model references distinguish quote matching from verified risk and render text only',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  vm.runInContext(`events[0].model_review={status:'completed',model:'fixture',assessment:'concern',categories:['data_transfer'],evidence_check:'snapshot_quote_v1',evidence_status:'references_matched',evidence:[{event_index:0,field:'action_preview',category:'data_transfer',quote:'<script>fixture</script>'}]};renderModelReview(events[0])`,t.context);
  let notes=t.document.getElementById('review-controls').children.map(c=>c.textContent||'').join(' ');
  assert.match(notes,/不证明风险推断/);assert.match(notes,/<script>fixture<\/script>/);
  assert.ok(t.document.getElementById('review-controls').children.every(c=>c.innerHTML===undefined));
  vm.runInContext("events[0].model_review.evidence_status='insufficient';events[0].model_review.evidence=[];renderModelReview(events[0])",t.context);
  notes=t.document.getElementById('review-controls').children.map(c=>c.textContent||'').join(' ');
  assert.match(notes,/已降为上下文不足/);
  assert.ok(!t.requests.some(r=>r.path==='/api/approvals'));
});

test('source recovery copy is explicit, reports clipboard failure and rejects stale or private actions',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  const copied=[];t.context.navigator={clipboard:{writeText:async text=>{copied.push(text);}}};
  vm.runInContext("selected='one';events[0].source_navigation={command:'codex resume fixture',message:'手动恢复'};renderSource(events[0])",t.context);
  let host=t.document.getElementById('source-controls');
  const copy=host.children.find(c=>c.textContent==='复制恢复命令');
  assert.equal(copy.hidden,false);assert.equal(copied.length,0);
  const requests=t.requests.length;
  await copy.onclick();assert.deepEqual(copied,['codex resume fixture']);
  assert.match(host.children[1].textContent,/没有启动客户端/);
  t.context.navigator.clipboard.writeText=async()=>{throw Error('denied');};
  await copy.onclick();assert.match(host.children[1].textContent,/剪贴板不可用/);
  t.context.navigator.clipboard.writeText=async text=>copied.push(text);
  vm.runInContext("selected='two'",t.context);await copy.onclick();
  vm.runInContext("selected='one';privacyMode=true",t.context);await copy.onclick();await host.children[0].onclick();
  assert.equal(copied.length,1);assert.equal(t.requests.length,requests);
  vm.runInContext('renderSource(events[0])',t.context);assert.equal(host.children.length,0);
  vm.runInContext("privacyMode=false;events[0].source_navigation={message:'无有效来源'};renderSource(events[0])",t.context);
  assert.equal(host.children.find(c=>c.textContent==='复制恢复命令').hidden,true);
});

function setup(pathname='/') {
  class Element {
    constructor(){this.value='';this.children=[];this.dataset={};this.classList={add(){},remove(){},toggle(){}};this.hidden=false;this.scrollTop=0;}
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=items;}
    setAttribute(){}
    querySelectorAll(){return [];}
  }
  const elements=new Map();
  const listeners={};
  const document={addEventListener(name,fn){listeners[name]=fn;},body:new Element(),hidden:false,getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement(){return new Element();},querySelector(){return new Element();},querySelectorAll(){return [];}};
  let calls=0,offline=false;const requests=[];
  const event=(id,session)=>({event_id:id,session_id:session,is_demo:false,adapter_id:'claude-hook',source_adapter:'claude-hook',occurred_at:new Date().toISOString(),findings:[],tool_name:'Read',verdict:'pass',mode:'observe',enforcement_status:'decision_only'});
  const events=[event('one','s1'),event('two','s2')];
  const overview={modes:{'claude-hook':'observe','gemini-hook':'observe','opencode-plugin':'observe'},events,connections:[],integrations:[],diagnostics:[],sessions:events.map(e=>({key:`0:claude-hook:${e.session_id}`,adapter:'claude-hook',session_id:e.session_id,is_demo:false,events:1}))};
  const context=vm.createContext({document,window:{addEventListener(name,fn){listeners[name]=fn;}},location:{hash:'',pathname},history:{replaceState(){}},URLSearchParams,AbortSignal,setInterval(){},Date,console,fetch:async(path,options)=>{calls++;requests.push({path,body:options.body?JSON.parse(options.body):null});if(offline)throw Error('offline');return {ok:true,json:async()=>path==='/api/launch-ticket'?{ticket:'single-use-fixture'}:overview};}});
  vm.runInContext(fs.readFileSync('web/app.js','utf8'),context);
  return {context,elements,document,listeners,requests,calls:()=>calls,offline(value){offline=value;}};
}

test('online old plugin remains visibly pending until a current revision heartbeat',()=>{
  const t=setup();
  t.context.connectionRows=[{instance_id:'fixture-one',mode:'observe',online:true,revision_current:false}];
  vm.runInContext('renderConnections(connectionRows)',t.context);
  assert.match(t.document.getElementById('opencode-instances').children[0].textContent,/需重启加载新版/);
  vm.runInContext("renderDiagnostics([{client:'opencode',adapter:'opencode-plugin',state:'online',readiness:'adapter_refresh_required',events_since_start:1,next_step:'重启客户端'}])",t.context);
  assert.equal(t.document.getElementById('overlay-health').textContent,'接入待核对');
  t.context.connectionRows[0].revision_current=true;
  vm.runInContext('renderConnections(connectionRows)',t.context);
  assert.doesNotMatch(t.document.getElementById('opencode-instances').children[0].textContent,/需重启加载新版/);
  assert.equal(t.requests.length,0);
});

test('a full nonoverlapping refresh warns about display continuity without inventing missed checks',()=>{
  const t=setup('/overlay');
  t.context.windowFixture={service_started_at:'boot',event_window:200,events:Array.from({length:200},(_,i)=>({event_id:'old-'+i}))};
  vm.runInContext('trackDisplayContinuity(windowFixture)',t.context);
  assert.equal(vm.runInContext('displayContinuityGap',t.context),false);
  t.context.windowFixture.events[0]={event_id:'new-0'};
  vm.runInContext('trackDisplayContinuity(windowFixture)',t.context);
  assert.equal(vm.runInContext('displayContinuityGap',t.context),false);
  t.context.windowFixture.events=Array.from({length:200},(_,i)=>({event_id:'next-'+i}));
  vm.runInContext('trackDisplayContinuity(windowFixture)',t.context);
  assert.equal(vm.runInContext('displayContinuityGap',t.context),true);
  assert.match(t.document.getElementById('overlay-health').title,/不表示后台漏检/);
  vm.runInContext('trackDisplayContinuity(windowFixture)',t.context);
  assert.equal(t.document.getElementById('overlay-health').textContent,'显示缺口待核对');
  vm.runInContext("renderStorage({status:'write_failed'})",t.context);
  assert.equal(t.document.getElementById('overlay-health').textContent,'存储异常');
  assert.equal(t.requests.length,0);
});

test('first load, service change and short history replacement do not assert a continuity gap',()=>{
  const t=setup('/overlay');
  t.context.windowFixture={service_started_at:'one',event_window:200,events:[{event_id:'a'}]};
  vm.runInContext('trackDisplayContinuity(windowFixture)',t.context);
  t.context.windowFixture.events=[{event_id:'b'}];vm.runInContext('trackDisplayContinuity(windowFixture)',t.context);
  t.context.windowFixture.service_started_at='two';
  t.context.windowFixture.events=Array.from({length:200},(_,i)=>({event_id:String(i)}));
  vm.runInContext('trackDisplayContinuity(windowFixture)',t.context);
  assert.equal(vm.runInContext('displayContinuityGap',t.context),false);
});

test('one overview request per refresh; session filtering clears unrelated detail',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  assert.equal(t.calls(),1);
  vm.runInContext("setView('live')",t.context);
  t.document.getElementById('session-filter').value='0:claude-hook:s2';
  vm.runInContext('render()',t.context);
  assert.equal(t.document.getElementById('evtCount').textContent,1);
  assert.equal(vm.runInContext('selected',t.context),'two');
  t.document.getElementById('filter').value='risk';vm.runInContext('render()',t.context);
  assert.equal(vm.runInContext('selected',t.context),null);
});

test('connection failure backs off and automatic recovery hides login',async()=>{
  const t=setup();t.offline(true);
  await vm.runInContext("token='fixture';refresh()",t.context);
  assert.ok(vm.runInContext('nextRefreshAt>Date.now()',t.context));
  t.offline(false);await vm.runInContext('refresh()',t.context);
  assert.equal(t.document.getElementById('login').hidden,true);
  assert.equal(vm.runInContext('failureCount',t.context),0);
});

test('real mode control submits per-client policy rather than demo mode',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  const row=t.document.getElementById('mode-controls').children[0];
  row.children[1].value='protect';row.children[1].onchange();row.children[3].children[0].checked=true;await row.children[2].onclick();
  assert.deepEqual(t.requests.find(r=>r.path==='/api/policy').body,{adapter:'claude-hook',mode:'protect'});
  assert.ok(!t.requests.some(r=>r.path==='/api/demo'));
});

test('strict protection requires explicit offline acknowledgement while observation does not',async()=>{
  const t=setup();vm.runInContext("renderModes({'claude-hook':'observe'})",t.context);
  const row=t.document.getElementById('mode-controls').children[0];
  const select=row.children[1],save=row.children[2],consent=row.children[3];
  assert.equal(consent.hidden,true);
  select.value='protect';select.onchange();await save.onclick();
  assert.equal(consent.hidden,false);
  assert.ok(!t.requests.some(r=>r.path==='/api/policy'));
  assert.match(t.document.getElementById('result').textContent,/离线影响/);
  consent.children[0].checked=true;
  select.value='observe';select.onchange();
  assert.equal(consent.children[0].checked,false);
  await save.onclick();
  assert.deepEqual(t.requests.find(r=>r.path==='/api/policy').body,{adapter:'claude-hook',mode:'observe'});
  assert.match(t.document.getElementById('result').textContent,/只提示/);
});

test('risk explanations distinguish a signal from harm and preserve decision boundaries',()=>{
  const t=setup();
  t.context.explainFixture={tool_name:'Bash',mode:'observe',verdict:'warn',findings:['destructive_command'],action_preview:{targets:['fixture']}};
  let result=vm.runInContext('explainAction(explainFixture)',t.context);
  assert.match(result.why,/特征/);assert.match(result.impact,/无法撤销/);
  assert.match(result.next,/手动中止/);assert.match(result.targets,/不是完整路径/);
  vm.runInContext("explainFixture.mode='protect';explainFixture.verdict='review';explainFixture.decision_state='awaiting_client_confirmation'",t.context);
  assert.match(vm.runInContext('explainAction(explainFixture).next',t.context),/原客户端的确认/);
  vm.runInContext("explainFixture.execution_state='succeeded'",t.context);
  assert.match(vm.runInContext('explainAction(explainFixture).next',t.context),/不能撤销/);
});

test('unknown findings do not become no-match explanations or expose raw command data',()=>{
  const t=setup();
  t.context.explainFixture={event_id:'explain',occurred_at:new Date().toISOString(),tool_name:'Bash',mode:'observe',verdict:'warn',findings:['new_rule'],tool_input:{command:'PRIVATE_COMMAND'}};
  vm.runInContext('details(explainFixture)',t.context);
  const cards=[...t.document.getElementById('action-explanation').children,...t.document.getElementById('evidence').children];
  const text=cards.map(c=>c.children.map(e=>e.textContent).join(' ')).join(' ');
  for(const label of ['发生了什么','为什么提醒','建议核对','现在怎么办'])assert.ok(text.includes(label));
  assert.match(text,/缺少可读说明/);assert.doesNotMatch(text,/本次没有命中|PRIVATE_COMMAND/);
  assert.equal(t.requests.length,0);
});

test('overlay explains observation and deletion risk without claiming a block',()=>{
  const t=setup('/overlay');
  vm.runInContext("desktopRisks.push({event_id:'risk',tool_name:'Bash',source_adapter:'claude-hook',mode:'observe',verdict:'warn',findings:['destructive_command'],execution_state:'unknown'});renderDesktopRisk()",t.context);
  const text=t.document.getElementById('desktop-alert-body').textContent;
  assert.match(text,/未阻断/);assert.match(text,/批量删除/);assert.match(text,/手动中止/);
  assert.doesNotMatch(text,/destructive_command|已停止本次/);
  assert.equal(t.requests.length,0);
});

test('approval submits only the selected event and does not replay tools',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  vm.runInContext("selected='pending-1';renderApproval({event_id:'pending-1',is_demo:false,approval_status:'pending',execution_state:'blocked'})",t.context);
  const host=t.document.getElementById('approval-controls');
  const approve=host.children.find(el=>el.textContent==='允许一次重试');
  await approve.onclick();
  assert.deepEqual(t.requests.find(r=>r.path==='/api/approvals').body,{event_id:'pending-1',decision:'approve'});
  assert.ok(!t.requests.some(r=>r.path.includes('/check')));
});

test('monitor starts live and popout carries a one-use ticket, never the token',async()=>{
  const t=setup('/monitor');
  assert.equal(vm.runInContext('view',t.context),'live');
  assert.equal(t.document.getElementById('monitor-status').hidden,false);
  await vm.runInContext("token='SECRET';refresh()",t.context);
  let destination='';t.context.window.open=()=>({location:{replace(url){destination=url;}},focus(){},close(){}});
  await t.document.getElementById('monitor-open').onclick();
  assert.equal(destination,'/#connect=single-use-fixture');
  assert.ok(!destination.includes('SECRET'));
});

test('blocked popout is visible and does not mint an unused ticket',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  t.context.window.open=()=>null;
  await t.document.getElementById('monitor-open').onclick();
  assert.ok(t.document.getElementById('connection').textContent.includes('弹窗被拦截'));
  assert.ok(!t.requests.some(r=>r.path==='/api/launch-ticket'));
});

test('compact list caps at five while full console keeps all matching events',()=>{
  for(const [path,count] of [['/monitor',5],['/',12]]) {
    const t=setup(path);
    vm.runInContext("view='live';events=Array.from({length:12},(_,i)=>({event_id:String(i),session_id:'s',is_demo:false,adapter_id:'claude-hook',occurred_at:new Date().toISOString(),findings:[],tool_name:'Read',verdict:'pass',mode:'observe'}));render()",t.context);
    assert.equal(t.document.getElementById('stream').children.length,count);
  }
});

test('particle companion is a distinct authenticated window',async()=>{
  const t=setup('/monitor');await vm.runInContext("token='fixture';refresh()",t.context);
  let destination='',features='';t.context.window.open=(url,name,options)=>{features=options;return {location:{replace(url){destination=url;}},focus(){},close(){}};};
  await t.document.getElementById('orb-open').onclick();
  assert.equal(destination,'/orb#connect=single-use-fixture');
  assert.ok(features.includes('width=240'));
  const orb=setup('/orb');assert.equal(vm.runInContext('view',orb.context),'live');
});

test('native overlay retains live five-event mode and calls only narrow window controls',async()=>{
  const t=setup('/overlay');
  assert.equal(vm.runInContext('compactMode && desktopMode && view === "live"',t.context),true);
  let closed=false;t.context.window.pywebview={api:{close(){closed=true;},toggle_pin:async()=>false}};
  t.document.getElementById('overlay-close').onclick();assert.equal(closed,true);
  await t.document.getElementById('overlay-pin').onclick();
  assert.equal(t.document.getElementById('overlay-pin').textContent,'◇');
});

test('live refresh does not rebuild a session dropdown while it is being used',()=>{
  const t=setup('/overlay');
  const select=t.document.getElementById('session-filter');
  select.value='chosen';select.append({textContent:'keep existing options'});
  t.document.activeElement=select;
  vm.runInContext("renderSessions([{key:'new',events:1,session_id:'s',adapter:'claude-hook',is_demo:false}])",t.context);
  assert.equal(select.value,'chosen');assert.equal(select.children[0].textContent,'keep existing options');
  t.document.activeElement=null;
  vm.runInContext("renderSessions([{key:'new',events:1,session_id:'s',adapter:'claude-hook',is_demo:false}])",t.context);
  assert.equal(select.children.length,2);
});

test('orb-only overlay alerts on new risk, ignores pass/history/demo and dismiss is not approval',()=>{
  const t=setup('/overlay');
  vm.runInContext(`
    const makeRisk=(id,verdict,extra={})=>({event_id:id,verdict,findings:verdict==='pass'?[]:['test'],
      source_adapter:'opencode-plugin',tool_name:'Bash',mode:'protect',is_demo:false,
      occurred_at:new Date(overlayStartedAt+1).toISOString(),...extra});
    collectDesktopRisks([makeRisk('ok','pass'),makeRisk('old','deny',{occurred_at:'2020-01-01T00:00:00Z'}),makeRisk('demo','deny',{is_demo:true})]);
  `,t.context);
  assert.equal(t.document.getElementById('desktop-alert').hidden,true);
  vm.runInContext("collectDesktopRisks([makeRisk('new','deny')])",t.context);
  assert.equal(t.document.getElementById('desktop-alert').hidden,false);
  assert.ok(t.document.getElementById('desktop-alert-title').textContent.includes('拒绝决定'));
  assert.ok(!t.document.getElementById('desktop-alert-body').textContent.includes('已停止'));
  t.document.getElementById('desktop-alert-dismiss').onclick();
  vm.runInContext("collectDesktopRisks([makeRisk('new','deny')])",t.context);
  assert.equal(t.document.getElementById('desktop-alert').hidden,true);
  assert.equal(t.requests.length,0);
});


test('late output signal alerts once, keeps the execution result and does not approve',async()=>{
  const t=setup('/overlay');let pulses=0;t.context.window.guardianVizPush=()=>pulses++;
  await vm.runInContext("token='fixture';refresh()",t.context);
  const before=pulses;
  vm.runInContext("events[0].occurred_at=new Date(Date.now()-600000).toISOString();events[0].execution_state='succeeded';events[0].output_scan={version:'output-1',status:'scanned',characters_scanned:30,truncated:false,findings:['instruction_override']};events[0].output_scan_at=new Date(Date.now()+1).toISOString()",t.context);
  await vm.runInContext('refresh()',t.context);
  assert.equal(pulses,before+1);
  assert.equal(t.document.getElementById('desktop-alert').hidden,false);
  assert.match(t.document.getElementById('desktop-alert-title').textContent,/返回内容待核对/);
  assert.match(t.document.getElementById('desktop-alert-body').textContent,/执行后提示/);
  assert.match(t.document.getElementById('desktop-alert-body').textContent,/执行成功/);
  assert.equal(vm.runInContext('desktopRisks.length',t.context),1);
  await vm.runInContext('refresh()',t.context);assert.equal(pulses,before+1);
  t.document.getElementById('desktop-alert-dismiss').onclick();
  await vm.runInContext('refresh()',t.context);assert.equal(t.document.getElementById('desktop-alert').hidden,true);
  assert.ok(!t.requests.some(r=>r.path==='/api/approvals'));
});

test('risk detail button forwards the exact event and reports missing or rejected native bridges',async()=>{
  const t=setup('/overlay');
  vm.runInContext("desktopRisks.push({event_id:'risk-42'})",t.context);
  const button=t.document.getElementById('desktop-alert-open');button.textContent='查看详情';
  await button.onclick();
  assert.match(t.document.getElementById('desktop-alert-count').textContent,/打开失败/);
  let received;
  t.context.window.pywebview={api:{open_console:async id=>{received=id;return {opened:true};}}};
  await button.onclick();assert.equal(received,'risk-42');assert.equal(button.disabled,false);
  assert.match(t.document.getElementById('desktop-alert-count').textContent,/详情窗口已打开/);
  t.context.window.pywebview.api.open_console=async()=>{throw Error('offline');};
  await button.onclick();assert.match(t.document.getElementById('desktop-alert-count').textContent,/offline/);
  assert.equal(button.textContent,'查看详情');
  assert.ok(!t.requests.some(r=>r.path==='/api/approvals'));
});

test('target event opens in its correct view and missing IDs never select a substitute for approval',async()=>{
  const t=setup();await vm.runInContext("(async()=>{token='fixture';await refresh();requestedEvent='two';focusRequestedEvent();})()",t.context);
  assert.equal(vm.runInContext('selected',t.context),'two');assert.equal(vm.runInContext('view',t.context),'live');
  vm.runInContext("requestedEvent='missing';focusRequestedEvent()",t.context);
  assert.match(t.document.getElementById('result').textContent,/未在最近 200 条/);
  assert.ok(!t.requests.some(r=>r.path==='/api/approvals'));
});


test('read-only discovery selects a plan without installing or running clients',async()=>{
  const t=setup();
  t.context.fetch=async(path,options)=>{
    assert.equal(path,'/api/discovery');assert.equal(options.method,'GET');
    return {ok:true,json:async()=>({message:'只读扫描',clients:[{id:'codex',name:'Codex CLI',detected:true,integration_available:true,state:'found',coverage:'待验证',paths:['fixture/codex.exe']}]})};
  };
  await t.document.getElementById('scan-agents').onclick();
  const host=t.document.getElementById('discovery-results');
  const check=host.children[1].children[0].children[0];check.checked=true;check.onchange();
  assert.match(host.children[2].textContent,/未启用接入/);
  await vm.runInContext("refreshIntegrations([{id:'codex',name:'Codex',installed:false,read_only:true,coverage:'未覆盖'}])",t.context);
  assert.equal(t.document.getElementById('integration-controls').children[0].children[3].disabled,true);
  assert.equal(t.requests.length,0);
});

test('discovery capability comes from backend and unsupported candidates stay disabled',async()=>{
  const t=setup();
  t.context.fetch=async()=>({ok:true,json:async()=>({clients:[
    {id:'pi',name:'Pi',detected:true,integration_available:false,paths:[]},
    {id:'future-adapter',name:'Future',detected:true,integration_available:true,paths:[]},
    {id:'claude',name:'Legacy response',detected:true,paths:[]}
  ]})});
  await t.document.getElementById('scan-agents').onclick();
  const host=t.document.getElementById('discovery-results');
  const checks=[1,2,3].map(i=>host.children[i].children[0].children[0]);
  assert.equal(checks[0].disabled,true);
  assert.equal(checks[1].disabled,false);
  assert.equal(checks[2].disabled,true);
});

test('Codex native has its own mode control and health distinguishes config from evidence',async()=>{
  const t=setup();
  vm.runInContext("renderModes({'codex-hook':'observe'})",t.context);
  const row=t.document.getElementById('mode-controls').children[3];
  row.children[1].value='protect';row.children[1].onchange();row.children[3].children[0].checked=true;await row.children[2].onclick();
  assert.deepEqual(t.requests.find(r=>r.path==='/api/policy').body,{adapter:'codex-hook',mode:'protect'});
  vm.runInContext("renderDiagnostics([{client:'codex-native',adapter:'codex-hook',state:'observed',readiness:'history_only',events_since_start:0,receipts_since_start:0,heartbeat_supported:false,next_step:'请验证'}])",t.context);
  assert.match(t.document.getElementById('diagnostic-codex-native').textContent,/仅有历史记录/);
  assert.match(t.document.getElementById('overlay-health').textContent,/待核对/);
  t.offline(true);await vm.runInContext("token='fixture';refresh()",t.context);
  assert.match(t.document.getElementById('diagnostic-codex-native').textContent,/服务离线/);
  assert.equal(t.document.getElementById('overlay-health').textContent,'服务断开');
});

test('unknown tool coverage never renders a safety pass',()=>{
  const t=setup();
  assert.equal(vm.runInContext("verdict({verdict:'pass',rule_coverage:{level:'generic_only'}})",t.context),'专用规则未覆盖');
  assert.equal(vm.runInContext("verdict({verdict:'pass'})",t.context),'未命中规则');
});

test('local review sends only selected event identity after model choice and confirmation',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh();setView('live')",t.context);
  const original=t.context.fetch;
  t.context.fetch=async(path,options)=>path==='/api/models/local'?{ok:true,json:async()=>({services:[{port:11434,models:[{name:'fixture:local'}]}]})}:original(path,options);
  await t.document.getElementById('scan-models').onclick();
  assert.ok(!t.requests.some(r=>r.path==='/api/reviews/local'));
  vm.runInContext("details(events[1])",t.context);
  let button=t.document.getElementById('review-controls').children.at(-1);
  await button.onclick();assert.ok(!t.requests.some(r=>r.path==='/api/reviews/local'));
  t.document.getElementById('review-model').value='0';
  await button.onclick();
  assert.deepEqual(t.requests.find(r=>r.path==='/api/reviews/local').body,{event_id:'two',port:11434,model:'fixture:local',confirmed:true,runtime:'auto'});
  assert.ok(!t.requests.some(r=>r.path==='/api/approvals'));
  vm.runInContext("renderModelReview({...events[1],model_review:{status:'running',model:'fixture:local'}})",t.context);
  assert.equal(t.document.getElementById('review-controls').children.at(-1).disabled,true);
  await t.document.getElementById('review-controls').children.find(c=>c.textContent==='取消这次模型复核').onclick();
  assert.deepEqual(t.requests.find(r=>r.path==='/api/reviews/cancel').body,{event_id:'two'});
  assert.ok(!t.requests.some(r=>r.path==='/api/approvals'));
});

test('overlay follows approval state without claiming successful execution',()=>{
  const t=setup('/overlay');
  vm.runInContext("desktopRisks.push({event_id:'risk',verdict:'review',source_adapter:'opencode-plugin',tool_name:'Bash',findings:[],execution_state:'blocked',approval_status:'pending'})",t.context);
  for(const [state,label] of [['approved','已授权'],['consumed','授权已使用'],['revoked','授权已撤销'],['expired','审批已过期'],['rejected','用户已拒绝']]){
    vm.runInContext(`desktopRisks[0].approval_status='${state}';renderDesktopRisk()`,t.context);
    assert.ok(t.document.getElementById('desktop-alert-title').textContent.includes(label));
    assert.match(t.document.getElementById('desktop-alert-body').textContent,/已停止本次调用/);
    assert.doesNotMatch(t.document.getElementById('desktop-alert-body').textContent,/执行成功/);
  }
  for(const [state,label] of [['tool_returned','未核验业务是否成功'],['failed','执行失败'],['succeeded','执行成功']]){
    vm.runInContext(`desktopRisks[0].execution_state='${state}';renderDesktopRisk()`,t.context);
    assert.ok(t.document.getElementById('desktop-alert-body').textContent.includes(label));
  }
  assert.equal(t.requests.length,0);
});

test('revoked requests explain the changed context and offer no approval button',()=>{
  const t=setup('/overlay');
  for(const [reason,label] of [['rules_changed','规则版本'],['semantic_changed','语义配置'],['service_restarted','服务已重启'],['policy_changed','模式配置']]){
    const event={event_id:'revoked',verdict:'review',is_demo:false,findings:[],execution_state:'blocked',approval_status:'revoked',approval_revocation_reason:reason};
    t.context.revokedFixture=event;
    vm.runInContext('renderApproval(revokedFixture);desktopRisks.splice(0,desktopRisks.length,revokedFixture);renderDesktopRisk()',t.context);
    const notes=t.document.getElementById('approval-controls').children.map(e=>e.textContent||'').join(' ');
    assert.ok(notes.includes(label));
    assert.ok(!t.document.getElementById('approval-controls').children.some(e=>e.textContent==='允许一次重试'));
    assert.ok(t.document.getElementById('desktop-alert-body').textContent.includes(label));
  }
});

test('consumed approval navigates to the exact retry receipt without executing',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh();",t.context);
  vm.runInContext("events[0].approval_status='consumed';events[1].approved_from='one';events[1].approval_status='consumed';renderApproval(events[0])",t.context);
  let button=t.document.getElementById('approval-controls').children.find(el=>el.textContent==='查看重试动作与回执');
  const before=t.requests.length;button.onclick();
  assert.equal(vm.runInContext('selected',t.context),'two');
  button=t.document.getElementById('approval-controls').children.find(el=>el.textContent==='查看原审批事件');
  button.onclick();assert.equal(vm.runInContext('selected',t.context),'one');
  assert.equal(t.requests.length,before);
  vm.runInContext("events=events.slice(0,1);renderApproval(events[0])",t.context);
  assert.ok(t.document.getElementById('approval-controls').children.some(el=>el.textContent.includes('不能据此判断执行结果')));
});

test('overlay keeps exact-event source fallback and errors through refresh',async()=>{
  const t=setup('/overlay');
  vm.runInContext("desktopRisks.push({source_adapter:'claude-hook',event_id:'risk-source',verdict:'warn',findings:[]})",t.context);
  t.context.fetch=async()=>({ok:true,json:async()=>({kind:'manual_resume',message:'manual',command:'claude --resume fixture'})});
  await t.document.getElementById('desktop-alert-source').onclick();
  vm.runInContext('renderDesktopRisk()',t.context);
  assert.match(t.document.getElementById('desktop-alert-count').textContent,/查看详情/);
  t.context.fetch=async()=>{throw Error('offline');};
  await t.document.getElementById('desktop-alert-source').onclick();
  vm.runInContext('renderDesktopRisk()',t.context);
  assert.match(t.document.getElementById('desktop-alert-count').textContent,/offline/);
  vm.runInContext("desktopRisks[0]={event_id:'different',verdict:'warn',findings:[]};renderDesktopRisk()",t.context);
  assert.doesNotMatch(t.document.getElementById('desktop-alert-count').textContent,/offline|查看详情/);
});

test('source locator only sends the selected event ID and never sends an agent prompt',async()=>{
  const t=setup('/overlay');
  vm.runInContext("desktopRisks.push({source_adapter:'claude-hook',event_id:'risk-source'})",t.context);
  await t.document.getElementById('desktop-alert-source').onclick();
  assert.deepEqual(t.requests.find(r=>r.path==='/api/source/open').body,{event_id:'risk-source'});
  assert.ok(!t.requests.some(r=>r.path==='/api/approvals'));
  t.requests.length=0;
  const full=setup();await vm.runInContext("(async()=>{token='fixture';await refresh();setView('live');details(events[1]);})()",full.context);
  await full.document.getElementById('source-controls').children[0].onclick();
  assert.deepEqual(full.requests.find(r=>r.path==='/api/source/open').body,{event_id:'two'});
});

test('navigation capability controls unsupported clients and does not claim expired history',async()=>{
  const t=setup('/overlay');
  vm.runInContext("desktopRisks.push({event_id:'pi',source_adapter:'pi-extension',verdict:'review',findings:[]});renderDesktopRisk();renderSource(desktopRisks[0])",t.context);
  const button=t.document.getElementById('desktop-alert-source');
  assert.equal(button.disabled,true);assert.match(button.textContent,/暂不支持/);
  await button.onclick();assert.equal(t.requests.length,0);
  assert.match(t.document.getElementById('source-controls').children[0].textContent,/独立能力/);
  t.context.catalog=[{adapter:'pi-extension',name:'Pi',mode_control:true,navigation:'terminal_window'}];
  vm.runInContext('applyAdapterCatalog(catalog);renderDesktopRisk()',t.context);
  assert.equal(button.disabled,false); // A server-declared future implementation needs no client-name exception.
  t.context.catalog=[{adapter:'pi-extension',name:'Pi',mode_control:true,navigation:'unrecognized'}];
  vm.runInContext('applyAdapterCatalog(catalog);renderDesktopRisk()',t.context);
  assert.equal(button.disabled,true);
});

test('pending source navigation survives refresh and private late results are discarded',async()=>{
  const t=setup('/overlay');let resolveSource,opens=0;
  const original=t.context.fetch;
  t.context.fetch=async(path,options)=>{
    if(path==='/api/source/open'){opens++;return new Promise(resolve=>{resolveSource=resolve;});}
    return original(path,options);
  };
  vm.runInContext("desktopRisks.push({event_id:'slow',source_adapter:'claude-hook',verdict:'warn',findings:[]});renderDesktopRisk()",t.context);
  const button=t.document.getElementById('desktop-alert-source');const pending=button.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  vm.runInContext('renderDesktopRisk()',t.context);assert.equal(button.disabled,true);
  await button.onclick();assert.equal(opens,1);
  vm.runInContext('applyPrivacy(true)',t.context);
  resolveSource({ok:true,json:async()=>({kind:'manual_resume',command:'PRIVATE_RESUME',message:'PRIVATE_RESULT'})});
  await pending;
  assert.equal(button.disabled,true);
  assert.equal(vm.runInContext('sourceResults.size',t.context),0);
  assert.doesNotMatch(t.document.getElementById('desktop-alert-count').textContent,/PRIVATE/);
});

test('onboarding requires explicit confirmation and cancelled plans cannot apply',async()=>{
  const t=setup();const calls=[];
  t.context.fetch=async(path,options)=>{
    calls.push({path,body:options.body?JSON.parse(options.body):null});
    const values={
      '/api/discovery':{clients:[{id:'codex',name:'Codex',detected:true,integration_available:true,paths:[]}]},
      '/api/onboarding/plan':{plan_id:'fixture-plan',note:'preview',clients:[{name:'Codex',path:'fixture/hooks.json',change:'append'}]},
      '/api/onboarding/apply':{results:[{id:'codex',message:'configured'}]},
      '/api/overview':{events:[],sessions:[],connections:[],integrations:[],diagnostics:[],modes:{}}
    };
    return {ok:true,json:async()=>values[path]};
  };
  await t.document.getElementById('scan-agents').onclick();
  const host=t.document.getElementById('discovery-results');
  const checkbox=host.children[1].children[0].children[0];checkbox.checked=true;checkbox.onchange();
  await host.children[3].onclick();
  const plan=host.children[5];const staleConfirm=plan.children[2];
  plan.children[3].onclick();await staleConfirm.onclick();
  assert.ok(!calls.some(c=>c.path==='/api/onboarding/apply'));
  await host.children[3].onclick();await plan.children[2].onclick();
  assert.deepEqual(calls.filter(c=>c.path==='/api/onboarding/apply').map(c=>c.body),[{plan_id:'fixture-plan',confirmed:true}]);
});

test('history clear requires preview and confirmation, cancellation sends no clear',async()=>{
  const t=setup();
  vm.runInContext("api=async(path,data)=>{historyCalls.push({path,data});if(path.endsWith('preview-clear'))return {plan_id:'bounded-plan',count:12};if(path.endsWith('/clear'))return {deleted:12};return {events:[],connections:[],integrations:[],diagnostics:[],sessions:[],modes:{}}};var historyCalls=[];",t.context);
  await t.document.getElementById('history-preview').onclick();
  let host=t.document.getElementById('history-controls');
  assert.equal(vm.runInContext('historyCalls.length',t.context),1);
  host.children[2].onclick();assert.equal(host.children.length,0);
  await t.document.getElementById('history-preview').onclick();
  await host.children[1].onclick();
  assert.equal(vm.runInContext("JSON.stringify(historyCalls.find(x=>x.path.endsWith('/clear')).data)",t.context),JSON.stringify({plan_id:'bounded-plan',confirmed:true}));
});

test('event feedback uses exact identity and revision, never submits authorization',async()=>{
  const t=setup();await vm.runInContext("(async()=>{token='fixture';await refresh();setView('live');details(events[0]);})()",t.context);
  const calls=[];
  t.context.fetch=async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});return {ok:true,json:async()=>({...vm.runInContext('events[0]',t.context),feedback_revision:1,user_feedback:{label:'false_positive',verified:false}})};};
  let host=t.document.getElementById('feedback-controls');
  const choose=host.children[3];choose.value='false_positive';await host.children[4].onclick();
  assert.deepEqual(calls,[{path:'/api/feedback',body:{event_id:'one',label:'false_positive',revision:0}}]);
  assert.match(t.document.getElementById('feedback-controls').children[2].textContent,/未经验证/);
  assert.equal(vm.runInContext('events[0].verdict',t.context),'pass');
  vm.runInContext("renderFeedback({...events[0],is_demo:true})",t.context);
  assert.equal(t.document.getElementById('feedback-controls').children.length,0);
});

test('feedback filter excludes unlabelled events and clears stale detail',async()=>{
  const t=setup();await vm.runInContext("(async()=>{token='fixture';await refresh();setView('live');events[1].user_feedback={label:'missed_risk'};})()",t.context);
  t.document.getElementById('filter').value='feedback';vm.runInContext('render()',t.context);
  assert.equal(vm.runInContext('selected',t.context),'two');
  vm.runInContext('delete events[1].user_feedback;render()',t.context);
  assert.equal(vm.runInContext('selected',t.context),null);
  assert.equal(t.document.getElementById('feedback-controls').children.length,0);
});

test('replay captures a read-only snapshot and stepping never submits actions',async()=>{
  const t=setup();await vm.runInContext("(async()=>{token='fixture';await refresh();setView('live');events[0].occurred_at='2026-11-03T01:00:00Z';events[1].occurred_at='2026-11-03T01:00:01Z';})()",t.context);
  const before=t.requests.length;let pulses=0;t.context.window.guardianVizPush=()=>pulses++;
  t.document.getElementById('replay-start').onclick();
  assert.equal(vm.runInContext('current().length',t.context),1);
  assert.match(t.document.getElementById('source-label').textContent,/REPLAY/);
  assert.match(t.document.getElementById('detail-summary').textContent,/历史快照/);
  for(const id of ['approval-controls','review-controls','source-controls','feedback-controls'])assert.match(t.document.getElementById(id).children[0].textContent,/只读/);
  await assert.rejects(vm.runInContext("api('/api/approvals',{event_id:'one',decision:'approve'})",t.context),/只读/);
  t.document.getElementById('replay-step').onclick();
  assert.equal(vm.runInContext('selected',t.context),'two');assert.equal(pulses,2);
  assert.equal(t.requests.length,before);
  assert.equal(t.document.getElementById('replay-step').disabled,true);
  t.document.getElementById('replay-exit').onclick();
  assert.equal(vm.runInContext('replay',t.context),null);
  assert.equal(t.document.getElementById('filter').disabled,false);
});

test('partial onboarding retries only incomplete clients and requires new confirmation',async()=>{
  const t=setup();const calls=[];
  t.context.fetch=async(path,options)=>{
    const body=options.body?JSON.parse(options.body):null;calls.push({path,body});
    const values={
      '/api/discovery':{clients:[{id:'claude',name:'Claude',detected:true,integration_available:true,paths:[]},{id:'codex',name:'Codex',detected:true,integration_available:true,paths:[]}]},
      '/api/onboarding/plan':{plan_id:'plan-'+calls.length,note:'preview',clients:(body?.clients||[]).map(id=>({name:id,path:'fixture',change:'append'}))},
      '/api/onboarding/apply':{results:[{id:'claude',state:'configured',message:'done'},{id:'codex',state:'uncertain',message:'inspect'}]},
      '/api/overview':{generated_at:'2026-11-03T00:00:01Z',service_started_at:'boot',events:[],sessions:[],connections:[],integrations:[],diagnostics:[],modes:{}}
    };return {ok:true,json:async()=>values[path]};
  };
  await t.document.getElementById('scan-agents').onclick();
  const host=t.document.getElementById('discovery-results');
  for(const index of [1,2]){const box=host.children[index].children[0].children[0];box.checked=true;box.onchange();}
  await host.children.find(el=>el.textContent==='预览全局接入').onclick();
  const plan=host.children.at(-1);
  await plan.children.find(el=>el.textContent==='确认备份并接入').onclick();
  assert.equal(vm.runInContext('connectionChecks.size',t.context),0);
  const verify=plan.children.find(el=>el.textContent==='检查接入是否生效');
  assert.ok(verify);
  // Only configured clients enter verification; an uncertain write is not success.
  await verify.onclick();
  assert.equal(vm.runInContext('connectionChecks.size',t.context),1);
  assert.equal(vm.runInContext("connectionChecks.has('claude')",t.context),true);
  assert.equal(vm.runInContext("connectionChecks.has('codex-native')",t.context),false);
  await plan.children.find(el=>el.textContent==='仅重新预览未完成项').onclick();
  const previews=calls.filter(c=>c.path==='/api/onboarding/plan');
  assert.deepEqual(previews.at(-1).body.clients,['codex']);
  assert.equal(calls.filter(c=>c.path==='/api/onboarding/apply').length,1);
  assert.ok(plan.children.some(el=>el.textContent==='确认备份并接入'));
});

test('live refresh does not replace replay snapshot or emit live particles',async()=>{
  const t=setup();await vm.runInContext("(async()=>{token='fixture';await refresh();setView('live');})()",t.context);
  t.document.getElementById('replay-start').onclick();let pulses=0;t.context.window.guardianVizPush=()=>pulses++;
  vm.runInContext("events[0].verdict='deny';seen.clear();snapshot='';",t.context);
  await vm.runInContext('refresh()',t.context);
  assert.equal(vm.runInContext("replay.rows.find(e=>e.event_id==='one').verdict",t.context),'pass');
  assert.equal(pulses,0);
  assert.match(t.document.getElementById('source-label').textContent,/REPLAY/);
});

test('replay speed advances timeline and tab suspension pauses instead of skipping',async()=>{
  const t=setup();await vm.runInContext("(async()=>{token='fixture';await refresh();setView('live');events[0].occurred_at='2026-11-03T01:00:00Z';events[1].occurred_at='2026-11-03T01:00:01Z';})()",t.context);
  t.document.getElementById('replay-start').onclick();
  t.document.getElementById('replay-speed').value='4';t.document.getElementById('replay-speed').onchange();
  t.document.getElementById('replay-play').onclick();
  vm.runInContext('replayTick(replay.lastTick+250)',t.context);
  assert.equal(vm.runInContext('replay.index',t.context),1);
  assert.equal(vm.runInContext('replay.playing',t.context),false);
  t.document.getElementById('replay-exit').onclick();t.document.getElementById('replay-start').onclick();t.document.getElementById('replay-play').onclick();
  vm.runInContext('replayTick(replay.lastTick+60000)',t.context);
  assert.equal(vm.runInContext('replay.index',t.context),0);assert.equal(vm.runInContext('replay.playing',t.context),false);
});

test('storage failure is visible without presenting old events as current protection',()=>{
  const t=setup();vm.runInContext("renderStorage({status:'write_failed',write_failures:1})",t.context);
  assert.equal(t.document.getElementById('storage-status').hidden,false);
  assert.match(t.document.getElementById('storage-status').textContent,/写入失败/);
  assert.equal(t.document.getElementById('overlay-health').textContent,'存储异常');
  vm.runInContext("renderStorage({status:'ready',write_failures:1})",t.context);
  assert.equal(t.document.getElementById('storage-status').hidden,true);
});

test('receipt gaps remain visible and navigate only to the matching local event',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  const before=t.requests.length;
  vm.runInContext("renderDiagnostics([{client:'claude',adapter:'claude-hook',state:'observed',readiness:'receipt_gaps',events_since_start:2,receipts_since_start:1,receipt_gaps_since_start:1,receipt_gap_sessions:1,receipt_gap_event_ids:['two']}])",t.context);
  const label=t.document.getElementById('diagnostic-claude');
  assert.match(label.textContent,/不代表执行失败/);
  assert.equal(t.document.getElementById('overlay-health').textContent,'接入待核对');
  label.children[0].onclick();
  assert.equal(vm.runInContext('selected',t.context),'two');
  assert.equal(t.document.getElementById('session-filter').value,'0:claude-hook:s2');
  assert.equal(t.requests.length,before);
});

test('pretool semantic timeout is distinct from a model safety finding',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  vm.runInContext("events[0].semantic_check={status:'timeout',latency_ms:1500};details(events[0])",t.context);
  const evidence=t.document.getElementById('evidence').children.at(-1);
  assert.match(evidence.children[1].textContent,/检查超时/);
  assert.match(evidence.children[1].textContent,/未提供用户任务上下文/);
  assert.match(evidence.children[1].textContent,/不等于授权或安全保证/);
});

test('semantic experiment requires client selection and explicit local raw-input confirmation',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  vm.runInContext("discoveredSemanticModels=[{port:11435,name:'fixture:local'}]",t.context);
  t.document.getElementById('semantic-model').value='0';
  t.document.getElementById('semantic-client-codex-hook').checked=true;
  const before=t.requests.length;
  t.document.getElementById('semantic-preview').onclick();
  let host=t.document.getElementById('semantic-confirmation');
  assert.match(host.children[0].textContent,/原始工具参数/);
  assert.equal(t.requests.length,before);
  host.children.find(el=>el.textContent==='取消').onclick();
  assert.equal(t.requests.length,before);
  t.document.getElementById('semantic-preview').onclick();
  await host.children.find(el=>el.textContent==='确认原始参数本地处理并启用实验').onclick();
  const change=t.requests.find(r=>r.path==='/api/semantic/config');
  assert.equal(change.body.confirmed_raw_local_processing,true);
  assert.deepEqual(change.body.clients,['codex-hook']);
  assert.equal(change.body.runtime,'cpu');
  assert.equal(t.requests.some(r=>r.path==='/api/semantic/prepare'),false);
});

test('semantic preparation status distinguishes ready from expired and replay is read-only',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  vm.runInContext("renderSemanticGate({enabled:true,preparation:{status:'ready',ready:false}})",t.context);
  assert.match(t.document.getElementById('semantic-status').textContent,/过期/);
  vm.runInContext("renderSemanticGate({enabled:true,preparation:{status:'preparing',ready:false}})",t.context);
  assert.equal(t.document.getElementById('semantic-prepare').disabled,true);
  const before=t.requests.length;
  vm.runInContext('replay={rows:[]}',t.context);
  t.document.getElementById('semantic-preview').onclick();
  assert.match(t.document.getElementById('semantic-confirmation').children[0].textContent,/只读/);
  assert.equal(t.requests.length,before);
});

test('connection verification starts with a read-only baseline and never launches an agent',async()=>{
  const t=setup();
  t.context.fetch=async(path,options)=>{
    t.requests.push({path,method:options.method});
    return {ok:true,json:async()=>({generated_at:'2026-11-03T00:00:01Z',service_started_at:'boot',events:[],diagnostics:[]})};
  };
  await vm.runInContext("connected=true;refreshIntegrations([{id:'claude',name:'Claude',installed:true}])",t.context);
  const box=t.document.getElementById('integration-controls').children[0];
  await box.children.find(e=>e.textContent==='验证普通对话接入').onclick();
  assert.deepEqual(t.requests,[{path:'/api/overview',method:'GET'}]);
  assert.equal(vm.runInContext("connectionChecks.get('claude').started",t.context),'2026-11-03T00:00:01Z');
  assert.match(JSON.stringify(t.document.getElementById('connection-verification').children),/等待新的读取动作/);
});

test('batch connection verification maps Codex and waits for an explicit click',async()=>{
  const t=setup();let requests=0;
  t.context.fetch=async()=>{requests++;return {ok:true,json:async()=>({generated_at:'2026-11-03T00:00:01Z',service_started_at:'boot',events:[],diagnostics:[]})};};
  assert.equal(requests,0);
  await vm.runInContext("beginConnectionChecks(['codex','opencode'])",t.context);
  assert.equal(requests,1);
  assert.equal(vm.runInContext("connectionChecks.get('codex-native').adapter",t.context),'codex-hook');
  assert.equal(vm.runInContext("connectionChecks.get('opencode').adapter",t.context),'opencode-plugin');
  assert.equal(vm.runInContext('connectionChecks.size',t.context),2);
});

test('native source click transfers focus permission before requesting the exact event',async()=>{
  const t=setup('/overlay');let prepared=false;
  t.context.window.pywebview={api:{prepare_source_navigation:async()=>{assert.ok(!t.requests.some(r=>r.path==='/api/source/open'));prepared=true;}}};
  vm.runInContext("desktopRisks.push({source_adapter:'claude-hook',event_id:'risk-source'})",t.context);
  await t.document.getElementById('desktop-alert-source').onclick();
  assert.equal(prepared,true);
  assert.deepEqual(t.requests.find(r=>r.path==='/api/source/open').body,{event_id:'risk-source'});
});

test('source click stops if privacy changes during native foreground transfer',async()=>{
  const t=setup('/overlay');
  t.context.window.pywebview={api:{prepare_source_navigation:async()=>{vm.runInContext('privacyMode=true',t.context);}}};
  vm.runInContext("desktopRisks.push({source_adapter:'claude-hook',event_id:'risk-source'})",t.context);
  await t.document.getElementById('desktop-alert-source').onclick();
  assert.ok(!t.requests.some(r=>r.path==='/api/source/open'));
});

test('verification prompt copy is explicit, never sends a message and has a manual fallback',async()=>{
  const t=setup();const copied=[];
  t.context.navigator={clipboard:{writeText:async text=>copied.push(text)}};
  await vm.runInContext("token='fixture';refresh();",t.context);
  t.context.fetch=async(path,options)=>{
    t.requests.push({path,method:options.method});
    return {ok:true,json:async()=>({generated_at:'2026-11-03T00:00:01Z',service_started_at:'boot',events:[],diagnostics:[]})};
  };
  await vm.runInContext("beginConnectionChecks(['claude'])",t.context);
  const button=t.document.getElementById('connection-verification').children.find(c=>c.textContent==='复制验证提示词');
  assert.equal(copied.length,0);const before=t.requests.length;
  await button.onclick();assert.deepEqual(copied,['请只读取当前项目的 README 文件并概括内容，不修改文件、不运行命令、不访问网络。']);
  assert.equal(t.requests.length,before);
  assert.match(t.document.getElementById('result').textContent,/复制本身不代表接入已验证/);
  t.context.navigator.clipboard.writeText=async()=>{throw Error('denied');};
  await button.onclick();assert.match(t.document.getElementById('result').textContent,/手动选择/);
  t.context.navigator.clipboard.writeText=async text=>copied.push(text);
  for(const state of ['privacyMode=true','privacyMode=false;replay={}','replay=null;connected=false','connected=true;connectionChecks.clear()']){
    vm.runInContext(state,t.context);await button.onclick();
  }
  assert.equal(copied.length,1);assert.equal(t.requests.length,before);
});

test('pending approval distinguishes missing receipt and rejects stale, private, replay and offline clicks',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  const host=t.document.getElementById('approval-controls');
  vm.runInContext("selected='one';renderApproval({event_id:'one',is_demo:false,approval_status:'pending',execution_state:'unknown'})",t.context);
  assert.match(host.children.map(c=>c.textContent).join(' '),/尚未确认原调用停止/);
  const approve=host.children.find(c=>c.textContent==='允许一次重试');
  for(const state of ["selected='two'","selected='one';privacyMode=true","privacyMode=false;replay={}","replay=null;connected=false"]){
    vm.runInContext(state,t.context);await approve.onclick();
  }
  assert.ok(!t.requests.some(r=>r.path==='/api/approvals'));
  vm.runInContext("connected=true;renderApproval({event_id:'one',is_demo:false,approval_status:'pending',execution_state:'blocked'})",t.context);
  const text=host.children.map(c=>c.textContent).join(' ');
  assert.match(text,/适配器已报告原调用停止/);assert.doesNotMatch(text,/尚未确认原调用停止/);
  vm.runInContext("privacyMode=true;renderApproval({event_id:'one',is_demo:false,approval_status:'pending'})",t.context);
  assert.equal(host.children.length,0);
});

test('native confirmation audit distinguishes authorization from execution',()=>{
  const t=setup('/');
  const e={event_id:'one',source_adapter:'pi-extension',is_demo:false,verdict:'review',decision_state:'authorized_once',execution_state:'unknown',native_confirmation:{outcome:'confirmed'}};
  t.context.auditEvent=e;
  vm.runInContext('renderApproval(auditEvent)',t.context);
  const host=t.document.getElementById('approval-controls');
  assert.match(host.children.map(c=>c.textContent).join(' '),/仅针对原动作，不代表执行成功/);
  assert.equal(vm.runInContext('verdict(auditEvent)',t.context),'单次授权通过');
  e.native_confirmation.outcome='not_confirmed';e.decision_state='denied';
  assert.equal(vm.runInContext('verdict(auditEvent)',t.context),'本次未获确认');
});

test('native confirmation prompt does not remain pending after a tool receipt',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  const host=t.document.getElementById('approval-controls');
  const render=state=>vm.runInContext(`renderApproval({event_id:'one',source_adapter:'claude-hook',is_demo:false,decision_state:'awaiting_client_confirmation',execution_state:'${state}'})`,t.context);
  render('unknown');assert.match(host.children.map(c=>c.textContent).join(' '),/请在 Claude Code 原生权限提示中判断/);
  for(const state of ['blocked','tool_returned','failed']){
    render(state);const text=host.children.map(c=>c.textContent).join(' ');
    assert.doesNotMatch(text,/请在 Claude Code 原生权限提示中判断/);
    assert.match(text,/没有独立的原生审批决定回执/);
    assert.ok(!host.children.some(c=>c.textContent==='允许一次重试'));
  }
  assert.ok(!t.requests.some(r=>r.path==='/api/approvals'));
});

test('compact refresh keeps live events but does not build hidden console panels',async()=>{
  for(const path of ['/overlay','/orb','/monitor']){
    const t=setup(path);
    await vm.runInContext("token='fixture';refresh()",t.context);
    assert.equal(vm.runInContext('events.length',t.context),2);
    assert.ok(t.document.getElementById('session-filter').children.length>0);
    for(const id of ['integration-controls','mode-controls','facts','evidence','approval-controls','review-controls']){
      assert.equal(t.document.getElementById(id).children.length,0,path+' '+id);
    }
    assert.equal(t.document.getElementById('raw').textContent,'尚未选择事件');
    assert.ok(t.document.getElementById('overlay-health').textContent);
    assert.equal(t.requests.filter(r=>r.path==='/api/overview/compact').length,1);
    assert.ok(!t.requests.some(r=>r.path==='/api/integrations'));
  }
});

test('verification cannot start after privacy is enabled while baseline is loading',async()=>{
  const t=setup();let finish;
  t.context.fetch=()=>new Promise(resolve=>{finish=resolve;});
  const pending=vm.runInContext("beginConnectionChecks(['claude'])",t.context);
  vm.runInContext('privacyMode=true',t.context);
  finish({ok:true,json:async()=>({generated_at:'2026-11-03T00:00:01Z',service_started_at:'boot',events:[],diagnostics:[]})});
  await assert.rejects(pending,/页面状态已变化/);
  assert.equal(vm.runInContext('connectionChecks.size',t.context),0);
});

test('connection verification ignores demo/history/other clients and binds one receipt',()=>{
  const t=setup();
  const event={event_id:'read-one',is_demo:false,source_adapter:'claude-hook',tool_name:'Read',session_id:'session-fixture',mode:'observe',occurred_at:'2026-11-03T00:00:02Z',execution_state:'unknown'};
  t.context.overviewFixture={service_started_at:'boot',events:[{...event,is_demo:true},{...event,source_adapter:'codex-hook'},{...event,occurred_at:'2026-11-02T00:00:01Z'}],diagnostics:[]};
  vm.runInContext("connected=true;connectionChecks.set('claude',{started:'2026-11-03T00:00:01Z',service:'boot',adapter:'claude-hook'});renderConnectionChecks(overviewFixture)",t.context);
  const notes=()=>JSON.stringify(t.document.getElementById('connection-verification').children);
  assert.match(notes(),/等待新的读取动作/);
  t.context.overviewFixture.events=[event];vm.runInContext('renderConnectionChecks(overviewFixture)',t.context);
  assert.match(notes(),/等待同一动作的执行回执/);
  t.context.overviewFixture.events.unshift({...event,event_id:'different',execution_state:'succeeded'});
  vm.runInContext('renderConnectionChecks(overviewFixture)',t.context);
  assert.match(notes(),/等待同一动作的执行回执/);
  event.execution_state='tool_returned';vm.runInContext('renderConnectionChecks(overviewFixture)',t.context);
  assert.match(notes(),/工具返回回执均已收到/);assert.match(notes(),/实际模式：观察/);
  t.context.overviewFixture.events=[];vm.runInContext('renderConnectionChecks(overviewFixture)',t.context);
  assert.match(notes(),/超出最近 200 条窗口/);
  vm.runInContext('connected=false;renderConnectionChecks(overviewFixture)',t.context);assert.match(notes(),/服务离线/);
  t.context.overviewFixture.service_started_at='different-boot';
  vm.runInContext('connected=true;renderConnectionChecks(overviewFixture)',t.context);assert.match(notes(),/服务已重启/);
});

test('connection verification distinguishes blocked and failed receipts from success',()=>{
  const t=setup();
  t.context.overviewFixture={service_started_at:'boot',events:[{event_id:'read-one',is_demo:false,source_adapter:'opencode-plugin',tool_name:'read',session_id:'s',mode:'protect',occurred_at:'2026-11-03T00:00:02Z',execution_state:'blocked'}],diagnostics:[]};
  vm.runInContext("connected=true;connectionChecks.set('opencode',{started:'2026-11-03T00:00:01Z',service:'boot',adapter:'opencode-plugin'});renderConnectionChecks(overviewFixture)",t.context);
  const notes=()=>JSON.stringify(t.document.getElementById('connection-verification').children);
  assert.match(notes(),/调用被停止/);assert.doesNotMatch(notes(),/成功回执均已收到/);
  t.context.overviewFixture.events[0].execution_state='failed';vm.runInContext('renderConnectionChecks(overviewFixture)',t.context);
  assert.match(notes(),/报告执行失败/);
  t.context.overviewFixture.diagnostics=[{client:'opencode',readiness:'disabled',next_step:'接入已停用'}];
  vm.runInContext('renderConnectionChecks(overviewFixture)',t.context);assert.match(notes(),/接入已停用/);
});

test('verification requires a session choice for simultaneous reads and ignores stale choices',async()=>{
  const t=setup();
  const event={event_id:'read-a',is_demo:false,source_adapter:'claude-hook',tool_name:'Read',session_id:'session-a',mode:'observe',occurred_at:'2026-11-03T00:00:02Z',execution_state:'succeeded'};
  t.context.overviewFixture={service_started_at:'boot',events:[event,{...event,event_id:'read-b',session_id:'session-b',execution_state:'unknown'}],diagnostics:[]};
  vm.runInContext("connected=true;latestOverview=overviewFixture;connectionChecks.set('claude',{started:'2026-11-03T00:00:01Z',service:'boot',adapter:'claude-hook'});renderConnectionChecks(overviewFixture)",t.context);
  const host=t.document.getElementById('connection-verification');
  assert.match(JSON.stringify(host.children),/多个会话同时上报/);
  assert.equal(vm.runInContext("connectionChecks.get('claude').eventId",t.context),undefined);
  let choices=host.children.at(-1).children.filter(c=>c.textContent?.startsWith('核对会话'));
  assert.equal(choices.length,2);
  vm.runInContext('privacyMode=true',t.context);await choices[1].onclick();
  assert.equal(vm.runInContext("connectionChecks.get('claude').eventId",t.context),undefined);
  vm.runInContext('privacyMode=false',t.context);await choices[1].onclick();
  assert.equal(vm.runInContext("connectionChecks.get('claude').eventId",t.context),'read-b');
  await choices[0].onclick();assert.equal(vm.runInContext("connectionChecks.get('claude').eventId",t.context),'read-b');
  assert.match(JSON.stringify(host.children),/等待同一动作的执行回执/);
  vm.runInContext("connectionChecks.set('claude',{started:'2026-11-03T00:00:03Z',service:'boot',adapter:'claude-hook'})",t.context);
  await choices[0].onclick();assert.equal(vm.runInContext("connectionChecks.get('claude').eventId",t.context),undefined);
  assert.equal(t.requests.length,0);
});

test('shared model contention is shown as busy rather than invalid model output',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  vm.runInContext("events[0].model_review={status:'failed',model:'fixture:local',error:'local_model_busy'};renderModelReview(events[0])",t.context);
  const notes=t.document.getElementById('review-controls').children.map(child=>child.textContent||'').join(' ');
  assert.match(notes,/本次复核未启动/);
  assert.match(notes,/稍后可手动重试/);
  assert.doesNotMatch(notes,/输出不符合结构/);
});


test('investigation is explicit, read-only and discards responses after selection changes',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  vm.runInContext("setView('live');details(events[0])",t.context);
  assert.ok(!t.requests.some(r=>r.path==='/api/investigations/context'));
  let release;const original=t.context.fetch;
  t.context.fetch=async(path,options)=>path==='/api/investigations/context'?new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>({anchor_event_id:'one',captured_at:new Date().toISOString(),events:[],gaps:['missing_receipt'],read_only:true})});}):original(path,options);
  let button=t.document.getElementById('investigation-controls').children.find(e=>e.textContent==='查看相关动作证据');
  const pending=button.onclick();vm.runInContext('details(events[1])',t.context);release();await pending;
  assert.equal(vm.runInContext('investigationSnapshot',t.context),null);
  vm.runInContext('details(events[0])',t.context);
  button=t.document.getElementById('investigation-controls').children.find(e=>e.textContent==='查看相关动作证据');
  const accepted=button.onclick();release();await accepted;
  assert.equal(vm.runInContext('investigationSnapshot.anchor_event_id',t.context),'one');
  assert.ok(t.document.getElementById('investigation-controls').children.some(e=>e.textContent==='部分动作没有执行回执'));
  assert.ok(!t.requests.some(r=>r.path==='/api/approvals'||r.path==='/api/reviews/local'||r.path.includes('/check')));
  t.document.getElementById('replay-start').onclick();
  assert.equal(vm.runInContext('investigationSnapshot',t.context),null);
});


test('related model review requires explicit scope selection and confirmation',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  vm.runInContext("setView('live');discoveredReviewModels=[{port:11434,name:'fixture:local'}];details(events[0])",t.context);
  t.document.getElementById('review-model').value='0';
  t.document.getElementById('review-scope').value='related';t.document.getElementById('review-scope').onchange();
  assert.ok(!t.requests.some(r=>r.path==='/api/reviews/local'));
  const button=t.document.getElementById('review-controls').children.at(-1);
  assert.equal(button.textContent,'确认发送相关动作摘要并复核');await button.onclick();
  assert.deepEqual(t.requests.find(r=>r.path==='/api/reviews/local').body,{event_id:'one',port:11434,model:'fixture:local',confirmed:true,runtime:'auto',include_context:true});
  assert.ok(!t.requests.some(r=>r.path==='/api/approvals'));
});


test('connection verification expires without accepting unrelated later actions',()=>{
  const t=setup();
  const event={event_id:'late',is_demo:false,source_adapter:'claude-hook',tool_name:'Read',session_id:'s',mode:'observe',occurred_at:'2026-11-03T00:03:00Z',execution_state:'succeeded'};
  t.context.overviewFixture={generated_at:'2026-11-03T00:03:01Z',service_started_at:'boot',events:[event],diagnostics:[]};
  vm.runInContext("connected=true;connectionChecks.set('claude',{started:'2026-11-03T00:00:01Z',service:'boot',adapter:'claude-hook'});renderConnectionChecks(overviewFixture)",t.context);
  assert.equal(vm.runInContext("connectionChecks.get('claude').expired",t.context),true);
  assert.equal(vm.runInContext("connectionChecks.get('claude').eventId",t.context),undefined);
  assert.match(JSON.stringify(t.document.getElementById('connection-verification').children),/本轮验证已结束/);
  event.occurred_at='2026-11-03T00:00:02Z';vm.runInContext('renderConnectionChecks(overviewFixture)',t.context);
  assert.equal(vm.runInContext("connectionChecks.get('claude').eventId",t.context),undefined);
});

test('checks-only verification never waits for unsupported receipt or confirms changed mode',()=>{
  const t=setup();
  t.context.overviewFixture={generated_at:'2026-11-03T00:00:03Z',service_started_at:'boot',events:[{event_id:'one',is_demo:false,source_adapter:'gemini-hook',tool_name:'Read',session_id:'s',mode:'observe',occurred_at:'2026-11-03T00:00:02Z',execution_state:'unknown'}],diagnostics:[{client:'gemini',readiness:'mode_unverified',receipt_supported:false,configured_mode:'protect'}]};
  vm.runInContext("connected=true;connectionChecks.set('gemini',{started:'2026-11-03T00:00:01Z',service:'boot',adapter:'gemini-hook'});renderConnectionChecks(overviewFixture)",t.context);
  const notes=JSON.stringify(t.document.getElementById('connection-verification').children);
  assert.match(notes,/不支持关联执行回执/);assert.match(notes,/模式尚未由本次动作确认/);
  assert.doesNotMatch(notes,/等待同一动作的执行回执/);
});


test('recording privacy masks custom tools and sessions and prevents blind operations',async()=>{
  for(const route of ['/','/overlay']){
  const t=setup(route);await vm.runInContext("token='fixture';refresh()",t.context);
  vm.runInContext("events[0].tool_name='PRIVATE_TOOL';events[0].session_id='PRIVATE_SESSION';events[0].action_preview={targets:['PRIVATE_HOST']};events[0].verdict='review';events[0].findings=['fixture'];events[0].explanations=[{title:'PRIVATE_REASON'}];desktopRisks.push(events[0]);applyPrivacy(true);details(events[0])",t.context);
  const visibleText=element=>[element.textContent||'',...element.children.map(visibleText)].join(' ');
  for(const id of ['stream','raw','desktop-alert-title','desktop-alert-body','monitor-status'])assert.doesNotMatch(visibleText(t.document.getElementById(id)),/PRIVATE_/);
  vm.runInContext("renderSessions([{key:'key',adapter:'claude-hook',session_id:'PRIVATE_SESSION',events:1}])",t.context);
  assert.doesNotMatch(visibleText(t.document.getElementById('session-filter')),/PRIVATE_/);
  const before=t.requests.length;
  await assert.rejects(vm.runInContext("api('/api/approvals',{event_id:'one',decision:'approve'})",t.context),/退出录屏隐私/);
  await t.document.getElementById('history-export').onclick();
  await t.document.getElementById('desktop-alert-source').onclick();
  assert.equal(t.requests.length,before);
  assert.equal(t.document.getElementById('approval-controls').children.length,0);
  vm.runInContext('applyPrivacy(false);details(events[0])',t.context);
  if(route==='/')assert.match(t.document.getElementById('raw').textContent,/PRIVATE_HOST/);
  else assert.doesNotMatch(t.document.getElementById('raw').textContent,/PRIVATE_HOST/);
  }
});

test('recording preference syncs without policy mutation and failure keeps local mask',async()=>{
  const t=setup();await vm.runInContext("token='fixture';refresh()",t.context);
  const original=t.context.fetch;let enabled=false;
  t.context.fetch=async(path,options)=>{
    if(path==='/api/presentation'){const body=JSON.parse(options.body);t.requests.push({path,body});enabled=body.privacy_mode;return {ok:true,json:async()=>({privacy_mode:enabled})};}
    const response=await original(path,options);const value=await response.json();return {ok:true,json:async()=>({...value,presentation:{privacy_mode:enabled}})};
  };
  await t.document.getElementById('privacy-toggle').onclick();assert.equal(vm.runInContext('privacyMode',t.context),true);
  assert.ok(!t.requests.some(r=>r.path==='/api/policy'||r.path==='/api/approvals'));
  enabled=false;await vm.runInContext('refresh()',t.context);assert.equal(vm.runInContext('privacyMode',t.context),false);
  t.context.fetch=async()=>{throw Error('offline')};await t.document.getElementById('privacy-toggle').onclick();
  assert.equal(vm.runInContext('privacyLocalLock&&privacyMode',t.context),true);
  t.context.fetch=original;await vm.runInContext('refresh()',t.context);
  assert.equal(vm.runInContext('privacyMode',t.context),true);
});

function setupOnboardingRace(){
  const t=setup();const calls=[];let planHandler,applyHandler;
  t.context.fetch=async(path,options)=>{
    const body=options.body?JSON.parse(options.body):null;calls.push({path,body});
    let value;
    if(path==='/api/discovery')value={clients:[{id:'claude',name:'Claude',detected:true,integration_available:true,paths:['fixture/path']}]};
    else if(path==='/api/onboarding/plan')value=planHandler?await planHandler(body):{plan_id:'p',expires_in:300,clients:[],note:'preview'};
    else if(path==='/api/onboarding/apply')value=applyHandler?await applyHandler(body):{results:[]};
    else value={events:[],sessions:[],connections:[],integrations:[],diagnostics:[],modes:{}};
    return {ok:true,json:async()=>value};
  };
  t.calls=calls;t.planHandler=fn=>{planHandler=fn;};t.applyHandler=fn=>{applyHandler=fn;};
  t.scan=async()=>{
    await t.document.getElementById('scan-agents').onclick();
    const host=t.document.getElementById('discovery-results');
    const check=host.children[1].children[0].children[0];check.checked=true;check.onchange();
    return host;
  };
  return t;
}

test('newer uninstall preview wins over an older slow install preview',async()=>{
  const t=setupOnboardingRace();const host=await t.scan();let finishInstall;
  t.planHandler(body=>body.action==='install'?new Promise(resolve=>{finishInstall=resolve;}):{plan_id:'remove',clients:[],note:'remove-current'});
  const old=host.children.find(e=>e.textContent==='预览全局接入').onclick();
  await host.children.find(e=>e.textContent==='预览撤销接入').onclick();
  finishInstall({plan_id:'install',clients:[],note:'stale-install'});await old;
  const plan=host.children.at(-1);
  assert.equal(plan.children[0].textContent,'remove-current');
  await plan.children.find(e=>e.textContent==='确认仅撤销 Guardian 接入').onclick();
  assert.equal(t.calls.find(c=>c.path==='/api/onboarding/apply').body.plan_id,'remove');
});

test('rescan invalidates the previous confirmation even if its handler survives',async()=>{
  const t=setupOnboardingRace();const host=await t.scan();
  await host.children.find(e=>e.textContent==='预览全局接入').onclick();
  const old=host.children.at(-1).children.find(e=>e.textContent==='确认备份并接入');
  await t.scan();await old.onclick();
  assert.ok(!t.calls.some(c=>c.path==='/api/onboarding/apply'));
});

test('expired preview is rejected locally without writing configuration',async()=>{
  const t=setupOnboardingRace();t.planHandler(()=>({plan_id:'expired',expires_in:0,clients:[]}));
  const host=await t.scan();await host.children.find(e=>e.textContent==='预览全局接入').onclick();
  const plan=host.children.at(-1);await plan.children.find(e=>e.textContent==='确认备份并接入').onclick();
  assert.ok(plan.children[0].textContent.includes('已过期'));
  assert.ok(!t.calls.some(c=>c.path==='/api/onboarding/apply'));
});

test('configuration application is single-flight and blocks rescan until it finishes',async()=>{
  const t=setupOnboardingRace();const host=await t.scan();let finish;
  t.applyHandler(()=>new Promise(resolve=>{finish=resolve;}));
  await host.children.find(e=>e.textContent==='预览全局接入').onclick();
  const confirm=host.children.at(-1).children.find(e=>e.textContent==='确认备份并接入');
  const first=confirm.onclick();await confirm.onclick();
  await t.document.getElementById('scan-agents').onclick();
  assert.equal(t.calls.filter(c=>c.path==='/api/onboarding/apply').length,1);
  assert.equal(t.calls.filter(c=>c.path==='/api/discovery').length,1);
  finish({results:[]});await first;
  assert.equal(t.document.getElementById('scan-agents').disabled,false);
});

test('privacy invalidates an in-flight discovery response before paths can reappear',async()=>{
  const t=setup();let finish;
  t.context.fetch=async()=>({ok:true,json:()=>new Promise(resolve=>{finish=resolve;})});
  const pending=t.document.getElementById('scan-agents').onclick();
  await new Promise(setImmediate);
  vm.runInContext('applyPrivacy(true)',t.context);
  finish({clients:[{id:'claude',detected:true,integration_available:true,paths:['SENSITIVE_FIXTURE_PATH']}]});await pending;
  assert.equal(t.document.getElementById('discovery-results').children.length,0);
});

test('repeated native reconnect clicks request only one ticket',async()=>{
  const t=setup();let finish,count=0;
  t.context.window.pywebview={api:{connection_ticket:()=>{count++;return new Promise(resolve=>{finish=resolve;});}}};
  const first=t.document.getElementById('native-reconnect').onclick();
  await t.document.getElementById('native-reconnect').onclick();
  assert.equal(count,1);finish({ticket:'fixture'});await first;
  assert.equal(t.document.getElementById('native-reconnect').disabled,false);
});

test('expired native startup ticket recovers once without manual credential entry',async()=>{
  const t=setup('/overlay');const original=t.context.fetch;let tickets=0;
  t.context.window.pywebview={api:{connection_ticket:async()=>{tickets++;return {ticket:'fresh'};}}};
  t.context.fetch=async(path,options)=>path==='/api/connect'?{ok:JSON.parse(options.body).ticket==='fresh',json:async()=>({token:'fixture-admin'})}:original(path,options);
  await vm.runInContext("connectWithTicket('expired',true)",t.context);
  await new Promise(setImmediate);
  assert.equal(tickets,1);assert.equal(vm.runInContext('connected',t.context),true);
  assert.equal(t.document.getElementById('token').value,'');
});

test('failed automatic native recovery stops instead of continuously minting tickets',async()=>{
  const t=setup('/overlay');let tickets=0;
  t.context.window.pywebview={api:{connection_ticket:async()=>{tickets++;throw Error('offline');}}};
  vm.runInContext('recoverNativeConnection()',t.context);await new Promise(setImmediate);
  vm.runInContext('recoverNativeConnection()',t.context);await new Promise(setImmediate);
  assert.equal(tickets,1);assert.equal(vm.runInContext('connected',t.context),false);
  assert.equal(t.document.getElementById('native-reconnect').disabled,false);
});


test('Qoder mode and source identity are independent from other clients',async()=>{
  const t=setup();
  vm.runInContext("renderModes({'qoder-hook':'observe'})",t.context);
  const row=t.document.getElementById('mode-controls').children.find(r=>r.children[0].textContent==='Qoder CLI');
  assert.ok(row);row.children[1].value='protect';row.children[1].onchange();row.children[3].children[0].checked=true;await row.children[2].onclick();
  assert.deepEqual(t.requests.find(r=>r.path==='/api/policy').body,{adapter:'qoder-hook',mode:'protect'});
  assert.equal(vm.runInContext("sourceName({source_adapter:'qoder-hook'})",t.context),'Qoder CLI');
  vm.runInContext("renderApproval({source_adapter:'qoder-hook',is_demo:false,decision_state:'awaiting_client_confirmation',execution_state:'unknown'})",t.context);
  assert.match(t.document.getElementById('approval-controls').children.map(c=>c.textContent).join(' '),/请在 Qoder CLI 原生权限提示中判断/);
});


test('configuration drift explains scope loss without claiming protection',()=>{
 const t=setup();
 vm.runInContext("renderDiagnostics([{client:'qoder',state:'config_error',readiness:'config_error',configuration_issues:['PreToolUse:matcher','PreToolUse:conditional_or_async']}])",t.context);
 const text=t.document.getElementById('diagnostic-qoder').textContent;
 assert.match(text,/匹配范围已改变/);assert.match(text,/条件执行或异步执行/);
});


test('server catalog drives new client filters, modes and keyed visual events',async()=>{
 const t=setup();const catalogs=[];t.context.window.guardianVizSources=rows=>catalogs.push(rows);
 t.context.rows=[{adapter:'fixture-agent',client:'fixture',integration:'fixture',name:'Fixture Agent',mode_control:true,scope:'native_tools'},
 {adapter:'fixture-model',client:'model',integration:null,name:'Fixture Model',mode_control:false,scope:'model_only'}];
 t.document.getElementById('source-filter').value='historical-client';
 vm.runInContext("applyAdapterCatalog(rows);renderModes({'fixture-agent':'observe'})",t.context);
 assert.equal(t.document.getElementById('source-filter').value,'historical-client');
 const filters=t.document.getElementById('source-filter').children;
 assert.ok(filters.some(r=>r.value==='fixture-agent'));assert.ok(filters.some(r=>r.value==='historical-client'));
 const controls=t.document.getElementById('mode-controls').children;assert.equal(controls.length,1);
 assert.equal(controls[0].children[0].textContent,'Fixture Agent');
 assert.equal(vm.runInContext("clientAdapters.fixture",t.context),'fixture-agent');
 assert.equal(vm.runInContext("sourceName({source_adapter:'fixture-agent'})",t.context),'Fixture Agent');
 const event=vm.runInContext("visualEvent({source_adapter:'fixture-agent',is_demo:false,verdict:'pass',findings:[]})",t.context);
 assert.equal(event.sourceId,'fixture-agent');assert.equal(event.sourceIndex,undefined);
 vm.runInContext('applyAdapterCatalog(rows)',t.context);assert.equal(catalogs.length,1);
 vm.runInContext('applyAdapterCatalog([rows[0],rows[0]])',t.context);assert.equal(catalogs.length,1);
});


test('wake refresh bypasses backoff with read-only, single-flight requests',async()=>{
 const t=setup();t.offline(true);
 await vm.runInContext("token='fixture';refresh()",t.context);
 t.offline(false);await t.listeners.online();
 assert.equal(vm.runInContext('connected',t.context),true);
 const count=t.calls();await t.listeners.pageshow();assert.equal(t.calls(),count);
 t.document.hidden=true;vm.runInContext('lastWakeRefresh=0',t.context);
 await t.listeners.visibilitychange();assert.equal(t.calls(),count);
 t.document.hidden=false;await t.listeners.visibilitychange();assert.equal(t.calls(),count+1);
 assert.ok(t.requests.every(r=>r.body===null));
 vm.runInContext('lastWakeRefresh=0;pending=true',t.context);
 await t.listeners.online();assert.equal(t.calls(),count+1);
});
