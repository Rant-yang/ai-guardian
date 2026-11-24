const $ = id => document.getElementById(id);
const desktopMode=location.pathname==='/overlay';
const orbMode=location.pathname==='/orb';
const overlayStartedAt=Date.now();
const desktopRisks=[];let lastAlertVisible=false;
const compactMode=location.pathname==='/monitor'||orbMode||desktopMode;
let token = '', events = [], view = 'live', selected = null, snapshot = '', connected = false, pending = false, busy = false;
const seen = new Set();
let privacyMode=false,privacyLocalLock=false;
const privateSessions=new Map();
const sourceResults=new Map();
const sourcePending=new Set();
const connectionChecks=new Map();
let latestOverview=null;
let previousWindowIds=null,previousWindowService=null,displayContinuityGap=false;
function trackDisplayContinuity(overview){
  const ids=new Set(overview.events.map(e=>e.event_id));
  const limit=overview.event_window;
  if(previousWindowService===overview.service_started_at&&previousWindowIds?.size&&
     Number.isInteger(limit)&&limit>0&&ids.size>=limit&&
     ![...ids].some(id=>previousWindowIds.has(id)))displayContinuityGap=true;
  previousWindowIds=ids;previousWindowService=overview.service_started_at;
  if(displayContinuityGap){
    const message='事件显示连续性待核对：两次刷新窗口没有重叠，期间可能有动作未在此窗口展示；不表示后台漏检。请在控制台查看或导出历史核对。';
    $('monitor-status').textContent=message;
    $('overlay-health').textContent='显示缺口待核对';
    $('overlay-health').title=message;$('overlay-health').setAttribute('aria-label',message);
  }
}
function localModelLabel(model){
  const size=Number.isFinite(model.size)&&model.size>0?' · 文件 '+(model.size/(1024**3)).toFixed(1)+' GiB':'';
  return model.name+' · '+model.port+size;
}
let clientAdapters={qoder:'qoder-hook',claude:'claude-hook',opencode:'opencode-plugin',gemini:'gemini-hook','codex-native':'codex-hook'};
let adapterCatalog=null,adapterCatalogSignature='';
function applyAdapterCatalog(rows){
  if(!Array.isArray(rows)||!rows.length||rows.length>32)return;
  if(rows.some(r=>!r||typeof r.adapter!=='string'||!/^[-a-z0-9]+$/.test(r.adapter)||typeof r.name!=='string'||r.name.length>100||typeof r.mode_control!=='boolean'))return;
  if(new Set(rows.map(r=>r.adapter)).size!==rows.length)return;
  const signature=JSON.stringify(rows);if(signature===adapterCatalogSignature)return;
  adapterCatalogSignature=signature;adapterCatalog=rows;
  clientAdapters=Object.fromEntries(rows.filter(r=>r.mode_control&&typeof r.integration==='string').map(r=>[r.integration,r.adapter]));
  const filter=$('source-filter'),selectedSource=filter.value;
  filter.replaceChildren();const all=node('option','','全部客户端');all.value='';filter.append(all);
  for(const row of rows){const option=node('option','',row.name);option.value=row.adapter;filter.append(option);}
  // Preserve a removed source filter so history never silently switches clients.
  if(selectedSource&&!rows.some(r=>r.adapter===selectedSource)){const option=node('option','','历史来源 · '+selectedSource);option.value=selectedSource;filter.append(option);}
  filter.value=selectedSource;
  modeSnapshot='';integrationSnapshot='';
  window.guardianVizSources?.(rows.map(r=>({id:r.adapter,name:r.name})));
}
function visualEvent(e){return {demo:e.is_demo,sourceId:e.source_adapter||e.adapter_id,kind:isBlocked(e)||e.verdict==='deny'?'bad':hasRisk(e)?'warn':'ok'};}
function sourceNavigationCapability(event){
  const id=event.source_adapter||event.adapter_id;
  const declared=adapterCatalog?.find(row=>row.adapter===id)?.navigation;
  const value=declared??({'claude-hook':'terminal_window','codex-hook':'terminal_or_desktop_request','opencode-plugin':'session_request_and_terminal'}[id]||'unsupported');
  return ['terminal_window','terminal_or_desktop_request','session_request_and_terminal'].includes(value)?value:'unsupported';
}
const sourceUnavailableNote='该客户端暂不支持自动返回原窗口或会话；请按事件时间和工具手动核对。动作监督与来源导航是独立能力。';
async function beginConnectionChecks(clients){
  if(replay||privacyMode)throw Error('请先退出历史回放或录屏隐私模式');
  const baseline=await api('/api/overview');
  if(!baseline.generated_at||!baseline.service_started_at)throw Error('服务未提供验证时间，请重新连接');
  if(replay||privacyMode)throw Error('页面状态已变化，请退出历史回放或录屏隐私模式后重新验证');
  for(const client of clients){
    const id=client==='codex'?'codex-native':client;
    if(clientAdapters[id])connectionChecks.set(id,{started:baseline.generated_at,service:baseline.service_started_at,adapter:clientAdapters[id]});
  }
  latestOverview=baseline;renderConnectionChecks(baseline);
  $('connection-verification').scrollIntoView?.({behavior:'smooth',block:'center'});
}
let historyExportUrl=null;
let replay=null;
let modeSnapshot='', ruleSnapshot='', integrationSnapshot='', connectionSnapshot='', sessionSnapshot='', failureCount=0, nextRefreshAt=0;
async function refreshIntegrations(rows) {
  rows=rows || await api('/api/integrations');
  const next=JSON.stringify(rows);if(next===integrationSnapshot)return;integrationSnapshot=next;
  const host=$('integration-controls');host.replaceChildren();
  for(const row of rows) {
    const box=node('div','appitem','');box.append(node('strong','',row.name),node('div','note',row.error||row.coverage));
    const status=node('div','note','');status.id='diagnostic-'+row.id;box.append(status);
    const button=node('button','btn',row.outdated?'更新接入':row.installed?'已启用 · 停用':'启用全局接入');
    button.disabled=!!(row.read_only||row.error||row.conflict);
    if(row.read_only)button.textContent=row.installed?'已配置 · 在扫描向导中管理':'未接入 · 在扫描向导中管理';
    button.onclick=async()=>{
      button.disabled=true;
      try{await api('/api/integrations',{client:row.id,action:row.installed&&!row.outdated?'uninstall':'install'});integrationSnapshot='';await refresh();$('result').textContent='接入配置已更新，请重启对应客户端使变更生效。';}
      catch(error){$('result').textContent=error.message+'，配置可能存在冲突；请保留现有配置。';button.disabled=false;}
    };box.append(button);
    if(clientAdapters[row.id]){
      const verify=node('button','btn','验证普通对话接入');verify.disabled=!row.installed||!!row.error||!!row.conflict;
      verify.onclick=async()=>{
        verify.disabled=true;
        try{
          await beginConnectionChecks([row.id]);
        }catch(error){$('result').textContent='无法开始接入验证：'+error.message;}
        finally{verify.disabled=false;}
      };
      box.append(verify);
    }
    host.append(box);
  }
}
function renderConnections(rows) {
  const active=rows.filter(row=>row.online);
  const state=$('state-opencode-plugin');
  state.textContent=active.length?`在线实例 ${active.length}`:rows.length?'实例已失联':'等待实例连接';
  state.className='chip '+(active.length?'on':'half');
  const signature=JSON.stringify(rows.slice(0,12).map(row=>[row.instance_id,row.mode,row.online,row.revision_current]));
  if(signature===connectionSnapshot)return;connectionSnapshot=signature;
  const host=$('opencode-instances');host.replaceChildren();
  for(const row of rows.slice(0,12)) host.append(node('div','note',`${row.instance_id.slice(0,8)} · ${row.mode==='protect'?'保护':'观察'} · ${row.online?'在线':'失联'}${row.online&&!row.revision_current?' · 需重启加载新版适配器':''}`));
}
const titles = {Read: '读取材料', Bash: '命令调用', guardian_demo_upload: '模拟文件上传', OllamaGenerate:'本地模型推理'};
const reasons = {possible_injection: '材料含有可能改变指令优先级的文本。规则只能提示可疑信号，不能判断真实因果。', destructive_command: '命令文本命中了危险操作规则。启发式可能误报，需要结合实际参数复核。', outbound_transfer_review: '动作命中了外传审查规则，需要进一步核对授权与目标。'};
const outputWarning=e=>e.output_scan?.status==='scanned'&&e.output_scan.findings?.includes('instruction_override');
const hasRisk=e=>!!(e.findings?.length||outputWarning(e));
const noticeKey=e=>e.event_id+(outputWarning(e)?':output':'');
const noticeTime=e=>outputWarning(e)?e.output_scan_at:e.occurred_at;
const isBlocked = e => e.enforcement_status === 'blocked_demo';
const revocationNote=e=>({rules_changed:'规则版本已变化',semantic_changed:'本地语义配置已变化',service_restarted:'守卫服务已重启',policy_changed:'模式配置已变化'}[e.approval_revocation_reason]||'检查上下文已变化')+'，旧审批请求或授权已失效；请在原会话重新发起动作检查。';
const verdict = e => outputWarning(e)?'返回内容待核对': e.verdict==='pass'&&e.rule_coverage?.level==='generic_only'?'专用规则未覆盖':e.approval_status==='approved'?'已授权 · 待重试':e.approval_status==='rejected'?'用户已拒绝':e.approval_status==='expired'?'审批已过期':e.approval_status==='revoked'?'授权已撤销':e.native_confirmation?.outcome==='not_confirmed'?'本次未获确认':e.decision_state==='authorized_once'?'单次授权通过':e.approval_status==='consumed'?'单次授权已使用':e.enforcement_status==='inference_failed' ? '推理失败' : isBlocked(e) ? '模拟阻断' : ({pass:'未命中规则',warn:'告警',review:'请求确认',deny:'拒绝决定'}[e.verdict] || e.verdict);
const sourceName = e => adapterCatalog?.find(r=>r.adapter===(e.source_adapter||e.adapter_id))?.name || ({'qoder-hook':'Qoder CLI','claude-hook':'Claude Code','opencode-plugin':'OpenCode','gemini-hook':'Gemini CLI','codex-mcp':'Codex MCP','codex-hook':'Codex 原生 Hooks','ollama-local':'Ollama'}[e.source_adapter || e.adapter_id] || (e.is_demo?'模拟工具':'未知来源'));
const kind = e => isBlocked(e) ? 'block' : hasRisk(e) || e.enforcement_status==='inference_failed' ? 'warn' : 'ok';
const displayTool=e=>privacyMode?({Read:'读取',Bash:'命令',Write:'写入',Edit:'编辑'}[e.rule_coverage?.canonical_tool]||'工具动作'):(titles[e.tool_name]||e.tool_name);
function explainAction(e){
  // Use only the already-redacted event; never infer a path or decode a command.
  const plain={
    destructive_command:['命令带有批量删除文件或修改磁盘的特征。','可能丢失文件，部分操作无法撤销。','核对是否确实要删除、删除范围和备份；不符合任务就让 Agent 停止或缩小范围。'],
    sensitive_file_access:['动作涉及可能保存密码、密钥或登录信息的文件。','可能读取或改动登录凭据；文件名命中不等于已经泄露。','核对任务是否需要这些凭据，优先让 Agent 使用脱敏示例。'],
    outbound_transfer_review:['命令含有向网络地址提交或上传数据的特征。','可能将本机内容发送给外部服务。','回到会话核对发送内容和接收地址是否都是你授权的。'],
    remote_code_execution:['命令可能把下载到的内容直接当作程序运行。','远端内容可能以你的权限修改文件或系统。','先让 Agent 展示脚本内容、来源和用途，再决定是否继续。'],
    encoded_execution:['命令内容经过编码，无法直接从可见文字判断用途。','编码可能隐藏文件、网络或系统修改动作。','让 Agent 用可读方式解释实际动作和范围；不清楚时不要批准。'],
    possible_injection:['材料中出现了要求忽略原有指令或改变任务的文字。','Agent 可能被带离你的任务；也可能只是正常引用。','核对这段文字是否只是材料内容，不要把它当成你的授权。'],
    patch_delete_review:['补丁中声明了删除文件。','应用补丁后，相应文件可能被删除。','核对删除列表是否符合任务，并确认有可恢复的版本。'],
    patch_unparsed_review:['守卫未能完整理解这份补丁的格式或大小。','尚不能可靠确认全部修改目标；不代表已经发现恶意。','请让 Agent 展示或拆分补丁，核对修改范围后再决定。'],
    semantic_review:['自动检查需要你补充判断，尚未确认这次动作得到授权。','这是不确定性提示，不是已经证实的危险。','结合你的原始任务核对动作；模型判断不能代替你的授权。']
  };
  const ids=e.findings||[],first=ids[0],ex=e.explanations?.find(r=>r.id===first),known=plain[first];
  const tool=e.rule_coverage?.canonical_tool||e.tool_name;
  const action=({Read:'读取文件',Write:'写入文件',Edit:'修改文件',apply_patch:'应用文件补丁',Bash:'执行命令'}[tool]||'调用工具')+'（'+displayTool(e)+'）';
  const targets=(e.action_preview?.targets||[]).filter(v=>typeof v==='string').slice(0,3).join('、');
  let why=known?.[0]||ex?.reason||(ids.length?'检测到了需要核对的信号，但当前记录缺少可读说明；不能据此认定恶意。':'未命中当前规则，不代表已经证明安全。');
  let impact=known?.[1]||ex?.impact||'当前记录不足以说明具体影响，请在原会话核对完整动作。';
  let check=known?.[2]||'回到原会话，核对完整参数是否符合你的任务。';
  if(outputWarning(e)){why='工具返回文本含指令覆盖表达，可能只是引用；这是执行后提示，不表示已拦截。';impact='返回内容可能影响后续动作，但不证明 Agent 已经照做。';check='核对返回内容，要求 Agent 继续遵守你的原始任务。';}
  if(ids.length>1)why+=' 另有 '+(ids.length-1)+' 项线索，见下方依据。';
  let next=e.mode==='observe'?'观察模式不会替你暂停 Agent；需要停止时请回原会话手动中止。':e.verdict==='deny'?'已发出拒绝决定；请回原会话核对并调整任务。':e.decision_state==='awaiting_client_confirmation'?'请在原客户端的确认提示中判断；返回窗口本身不会批准。':e.approval_status==='pending'?'核对后可在详情中允许一次重试或拒绝；不会自动执行。':'请核对原会话与最新执行回执；返回窗口不等于继续执行。';
  if(e.approval_status==='approved')next='已授权一次；请在原会话重试完全相同的动作，不会自动执行。';
  else if(e.approval_status==='revoked')next=revocationNote(e);
  else if(e.approval_status==='expired')next='审批已过期；请重新发起动作检查，不要使用旧授权。';
  else if(e.approval_status==='rejected'||e.native_confirmation?.outcome==='not_confirmed')next='本次未获授权；回原会话核对并调整任务。';
  if(['succeeded','failed','tool_returned'].includes(e.execution_state))next='本次动作已有执行回执；返回会话核对结果，审批不能撤销已经发生的操作。';
  return {action,targets:targets?'脱敏目标：'+targets+'（仅名称或主机，不是完整路径）':'目标未在守卫中完整保存；请回原会话核对具体文件、地址和参数。',why,impact,check,next};
}
const sessionLabel=row=>{if(!privacyMode)return row.session_id.slice(0,8);const key=row.key||sessionKey(row);if(!privateSessions.has(key)){if(privateSessions.size>=2000)privateSessions.clear();privateSessions.set(key,'会话 '+(privateSessions.size+1));}return privateSessions.get(key);};
const sessionKey=e=>`${Number(e.is_demo)}:${e.source_adapter||e.adapter_id}:${e.session_id}`;
const current = () => replay?replay.rows.slice(0,replay.index+1).reverse():events.filter(e => e.is_demo === (view === 'demo') && (!$('source-filter').value||(e.source_adapter||e.adapter_id)===$('source-filter').value) && (!$('session-filter').value||sessionKey(e)===$('session-filter').value));
const filterMatches = e => $('filter').value==='feedback'?!!e.user_feedback:$('filter').value!=='risk'||hasRisk(e);
const flowMatches = e => !desktopMode || ((!$('source-filter').value||(e.source_adapter||e.adapter_id)===$('source-filter').value) && (!$('session-filter').value||sessionKey(e)===$('session-filter').value) && filterMatches(e));
function node(tag, cls, text) {const el=document.createElement(tag);el.className=cls;el.textContent=text;return el;}
async function api(path, data, timeout=5000) {
  if(privacyMode&&data&&!['/api/presentation','/api/launch-ticket','/api/desktop/open'].includes(path))throw Error('请先退出录屏隐私，核对完整详情后操作');
  if(replay&&data&&!['/api/launch-ticket','/api/presentation'].includes(path))throw Error('历史回放为只读，请先退出回放再进行操作');
  const response = await fetch(path, {method:data?'POST':'GET', headers:{Authorization:'Bearer '+token,...(data?{'Content-Type':'application/json'}:{})},body:data?JSON.stringify(data):undefined,signal:AbortSignal.timeout(timeout)});
  if(!response.ok){
    let problem;try{problem=await response.json();}catch{}
    const error=Error(response.status===401||response.status===403?'连接认证已失效：请点击本机重连，或重新双击 Guardian.vbs':'服务请求失败（'+response.status+'）');
    if(problem?.code==='storage_unavailable'&&['write_failed','restart_required'].includes(problem.storage_status))error.storageStatus=problem.storage_status;
    throw error;
  }
  return response.json();
}
let investigationSnapshot=null, investigationRequest=0;
function details(e) {
  if(selected!==e.event_id){investigationSnapshot=null;investigationRequest++;}
  selected=e.event_id;
  // Compact windows open the separate console for details and approvals.
  // Do not repeatedly construct an invisible copy of that entire panel.
  if(compactMode)return;
  if(privacyMode){$('detail-title').textContent=verdict(e)+' · '+sourceName(e);$('detail-summary').textContent='录屏隐私已隐藏详细参数；退出后核对详情再进行审批。';for(const id of ['action-explanation','facts','evidence','approval-controls','source-controls','review-controls','feedback-controls','investigation-controls'])$(id).replaceChildren();$('raw').textContent='录屏隐私：记录已隐藏';return;}
  $('detail-time').textContent=new Date(e.occurred_at).toLocaleTimeString();
  $('detail-title').textContent=(isBlocked(e)?'⊗ ':hasRisk(e)?'△ ':'✓ ')+verdict(e)+' · '+(displayTool(e));
  $('verdict').className='verdict '+(isBlocked(e)?'':hasRisk(e)?'warning':'neutral');
  $('detail-summary').textContent=e.is_demo?(isBlocked(e)?'模拟执行器已确认停止这次动作。没有产生真实文件或网络副作用。':'这是演示事件。'+(e.mode==='observe'?'观察模式保留模拟行为，仅记录风险。':'本次动作已由模拟执行器完成。')):'执行前检查已返回决定；当前没有真实执行回执，不能确认动作是否完成或已被阻断。';
  $('facts').replaceChildren();
  if(e.source_adapter==='ollama-local') $('detail-summary').textContent=e.enforcement_status==='inference_failed'?'本地模型调用失败；此事件不能证明推理完成。':e.enforcement_status==='completed_demo'?'使用合成文本完成真实本地模型推理。当前仅检查输入规则，尚未启用模型内部安全探针。':'已记录模型输入检查，正在等待推理结果。';
  for(const [key,value] of [['来源',e.is_demo?'Demo · 隔离模拟工具':sourceName(e)+' · 执行前检查'],['工具',e.tool_name],['会话',e.session_id],['模式',e.mode==='protect'?'保护':'观察'],['检测器',e.detector],['阶段',e.enforcement_status]]) {
    const row=node('div','line','');row.append(node('span','k',key),node('span','v',value));$('facts').append(row);
  }
  $('evidence').replaceChildren();
  $('action-explanation').replaceChildren();
  const explanation=explainAction(e);
  for(const [label,text] of [['发生了什么',explanation.action+'。'+explanation.targets],['为什么提醒',explanation.why+' '+explanation.impact],['现在怎么办',explanation.next]]){
    const card=node('div','evi','');card.append(node('div','src',label),node('div','body',text));$('action-explanation').append(card);
  }
  const advice=node('div','evi','');advice.append(node('div','src','建议核对'),node('div','body',explanation.check));$('evidence').append(advice);
  const findings=e.findings.length?e.findings:['no_match'];
  for(const reason of findings){const rule=e.explanations?.find(r=>r.id===reason);const card=node('div','evi','');card.append(node('div','src',reason==='no_match'?'规则 · 未命中':rule?.title||'检测依据 · 待核对'),node('div','body',rule?.reason||reasons[reason]||(reason==='no_match'?'本次没有命中现有规则；不代表安全。':'已记录风险信号，但缺少详细解释；请核对原动作。')));$('evidence').append(card);}
  if(e.semantic_check){
    const check=e.semantic_check;
    const states={disabled:'未启用',model_not_prepared:'模型未预热或预热已过期',skipped_rule_decision:'已有规则拒绝或审批，未调用模型',skipped_read_only:'只读工具未路由到模型',busy:'模型繁忙',timeout:'检查超时',input_too_large:'输入超出预算',unavailable_or_invalid:'模型不可用或输出无效',completed:'已完成',configuration_changed:'检查期间配置变化'};
    const assessment={concern:'提示风险线索（未核实）',uncertain:'无法判断',no_additional_signal:'未发现额外线索'}[check.assessment];
    const card=node('div','evi','');card.append(node('div','src','本地语义 · 实验通道'),node('div','body',`${states[check.status]||'状态待核对'}${assessment?' · '+assessment:''}。未提供用户任务上下文，结果不等于授权或安全保证。${check.latency_ms!==undefined?' 用时 '+check.latency_ms+' ms。':''}`));$('evidence').append(card);
  }
  if(!e.is_demo&&e.execution_state&&e.execution_state!=='unknown')$('detail-summary').textContent=({blocked:'适配器已报告停止本次调用。',tool_returned:'收到工具返回回执；尚未核验业务操作是否成功。',succeeded:'客户端执行后钩子报告成功。',failed:'客户端执行后钩子报告失败。'}[e.execution_state]||'状态待核对');
  if(e.rule_coverage?.level==='generic_only')$('detail-summary').textContent+=' '+e.rule_coverage.note+'；未命中不代表安全。';
  renderSource(e);
  renderApproval(e);
  renderModelReview(e);
  renderInvestigation(e);
  renderFeedback(e);
  if(replay)$('detail-summary').textContent='历史快照 · 非实时动作。'+$('detail-summary').textContent;
  $('raw').textContent=JSON.stringify(e,null,2);
  document.querySelectorAll('.evt').forEach(el=>{el.classList.toggle('selected',el.dataset.eventId===selected);el.setAttribute('aria-pressed',String(el.dataset.eventId===selected));});
}
function render() {
  for(const adapter of ['claude-hook','gemini-hook','codex-mcp','codex-hook','ollama-local']) {
    const state=$('state-'+adapter);
    const recent=events.find(e=>(e.source_adapter||e.adapter_id)===adapter && (!e.is_demo || ['codex-mcp','ollama-local'].includes(adapter)));
    if(state && recent) {state.textContent=Date.now()-Date.parse(recent.occurred_at)<60000?'近期有事件':'有历史记录';state.className='chip half';}
  }
  const list=current();
  $('evtCount').textContent=list.length;
  $('blkCount').textContent=list.filter(isBlocked).length;
  $('coreNum').textContent=list.length;
  $('riskCount').textContent=list.filter(e=>hasRisk(e)).length;
  $('core-mode').textContent=replay?'历史回放 · 非实时':view==='demo'?'演示数据':'真实接入';
  $('source-label').textContent=replay?'REPLAY / 历史快照':view==='demo'?'DEMO / 独立演示':'LIVE / 真实接入';
  const filtered=list.filter(filterMatches);
  const visible=compactMode?filtered.slice(0,5):filtered;
  const host=$('stream');const scroll=host.scrollTop;host.replaceChildren();
  if(!visible.length){
    const empty=node('div','empty','');
    const hasReal=events.some(e=>!e.is_demo);
    empty.append(node('span','symbol','◈'),node('div','',view==='demo'?'暂无匹配事件，运行安全演示开始验证。':hasReal?'当前筛选没有匹配的真实动作，可调整事件、客户端或会话筛选。':'尚无真实工具事件。扫描并接入客户端后，在普通对话中读取项目 README 开始验证。'));
    if(view==='live'&&!hasReal&&!compactMode&&!replay){
      const scan=node('button','btn primary','扫描本地客户端');scan.disabled=!connected||privacyMode;
      scan.onclick=async()=>{
        if(!connected||privacyMode||replay)return;
        scan.disabled=true;
        try{await $('scan-agents').onclick();$('discovery-results').scrollIntoView?.({behavior:'smooth',block:'center'});}
        finally{scan.disabled=!connected||privacyMode;}
      };
      empty.append(scan);
    }
    host.append(empty);
  }
  for(const e of visible){const row=node('button','evt '+kind(e)+(e.event_id===selected?' selected':''),'');row.dataset.eventId=e.event_id;row.setAttribute('aria-pressed',String(e.event_id===selected));row.append(node('span','t',new Date(e.occurred_at).toLocaleTimeString('zh-CN',{hour12:false})),node('span','ico',isBlocked(e)?'×':hasRisk(e)?'!':'✓'));const text=node('div','','');text.append(node('div','ttl',displayTool(e)),node('div','meta',(e.is_demo?'DEMO · '+(['codex-mcp','ollama-local'].includes(e.source_adapter)?sourceName(e):'模拟工具'):sourceName(e))+' · '+displayTool(e)+' · '+(e.mode==='protect'?'保护':'观察')));row.append(text,node('span','verd',verdict(e)));row.onclick=()=>{details(e);if(compactMode)$('monitor-status').textContent=sourceName(e)+' · '+displayTool(e)+' · '+verdict(e)+'；查看详情或审批请打开控制台。';};host.append(row);}
  host.scrollTop=scroll;
  if(!visible.some(e=>e.event_id===selected)) {
    if(visible.length)details(visible.find(e=>hasRisk(e))||visible[0]);
    else {selected=null;investigationSnapshot=null;investigationRequest++;$('investigation-controls').replaceChildren();$('feedback-controls').replaceChildren();$('approval-controls').replaceChildren();$('review-controls').replaceChildren();$('source-controls').replaceChildren();$('verdict').className='verdict neutral';$('detail-time').textContent='—';$('detail-title').textContent='等待匹配事件';$('detail-summary').textContent='当前筛选没有事件。';for(const id of ['action-explanation','facts','evidence','source-controls','approval-controls','feedback-controls','review-controls','investigation-controls'])$(id).replaceChildren();$('raw').textContent='尚未选择事件';}
  }
}
async function refresh() {
  if(!token||pending)return;pending=true;
  try{const overview=await api(compactMode?'/api/overview/compact':'/api/overview');const next=overview.events;applyAdapterCatalog(overview.adapter_catalog);applyPrivacy(privacyLocalLock||overview.presentation?.privacy_mode===true);failureCount=0;nextRefreshAt=0;connected=true;document.body.classList.remove('overlay-offline');$('login').hidden=true;$('status').classList.remove('offline');$('connection').textContent='本地在线 · 规则版';$('demo').disabled=busy||!!replay;$('ollama-demo').disabled=busy||!!replay;$('sync').textContent='最近同步 '+new Date().toLocaleTimeString();$('monitor-status').textContent='监控已连接 · 约每 1.5 秒同步 · 仅覆盖已接入工具';
    for(const e of next){if(!seen.has(noticeKey(e))){seen.add(noticeKey(e));if(!replay&&e.is_demo===(view==='demo')&&flowMatches(e)&&Date.now()-Date.parse(noticeTime(e))<10000)window.guardianVizPush?.(visualEvent(e));}}
    collectDesktopRisks(next);
    if(!compactMode)renderModes(overview.modes,overview.events);
    if(overview.rulebook)$('rule-version').textContent=' · '+overview.rulebook.version+' / '+overview.rulebook.rules.length+' 条规则';
    renderConnections(overview.connections);
    if(!compactMode)await refreshIntegrations(overview.integrations);
    renderDiagnostics(overview.diagnostics);
    latestOverview=overview;if(!compactMode)renderConnectionChecks(overview);
    trackDisplayContinuity(overview);
    renderStorage(overview.storage);
    if(!compactMode)renderSemanticGate(overview.semantic_gate);
    renderSessions(overview.sessions);
    if(seen.size>4000){seen.clear();next.forEach(e=>seen.add(noticeKey(e)));}
    const value=JSON.stringify(next);if(value!==snapshot){snapshot=value;events=next;render();const active=events.find(e=>e.event_id===selected);if(active&&!replay)details(active);}if(replay)replayStatus();
  }catch(error){$('client-overview').replaceChildren(node('p','note','后台连接中断，当前客户端状态未确认。'));modeSnapshot='';for(const el of $('mode-controls').querySelectorAll('button,select'))el.disabled=true;integrationSnapshot='';for(const el of $('integration-controls').querySelectorAll('button'))el.disabled=true;for(const client of [...Object.keys(clientAdapters),'codex']){const label=$('diagnostic-'+client);if(label)label.textContent='服务离线 · 状态待刷新';}failureCount++;nextRefreshAt=Date.now()+Math.min(1500*2**Math.min(failureCount,5),30000);connected=false;document.body.classList.add('overlay-offline');$('overlay-health').textContent='服务断开';$('overlay-health').title='当前监控未确认，正在重连';if(!replay)window.guardianVizClear?.();$('state-opencode-plugin').textContent='连接状态未知';$('state-opencode-plugin').className='chip half';$('status').classList.add('offline');$('connection').textContent='连接中断';$('monitor-status').textContent='连接中断 · 以下为历史记录，当前动作未确认';$('sync').textContent='数据已停止更新';$('demo').disabled=true;$('ollama-demo').disabled=true;$('result').textContent=error.message+'。正在自动重连；也可双击桌面 Guardian。';$('login').hidden=false;if(error.storageStatus)renderStorage({status:error.storageStatus});}
  finally{pending=false;if(!connected&&latestOverview)renderConnectionChecks(latestOverview);if(replay)replayStatus();}
}
$('login').onsubmit=async event=>{event.preventDefault();token=$('token').value.trim();await refresh();if(connected){$('token').value='';$('login').hidden=true;}};
function setView(next){if(replay)return;view=next;selected=null;$('session-filter').value='';window.guardianVizClear?.();for(const id of ['demo','live']){$(id+'-view').classList.toggle('active',id===view);$(id+'-view').setAttribute('aria-pressed',String(id===view));}$('detail-title').textContent='◈ 等待检查事件';$('detail-summary').textContent='选择当前视图中的事件查看详情。';for(const id of ['action-explanation','facts','evidence','source-controls','approval-controls','feedback-controls','review-controls','investigation-controls'])$(id).replaceChildren();$('raw').textContent='尚未选择事件';$('detail-time').textContent='—';$('verdict').className='verdict neutral';render();}
$('demo-view').onclick=()=>setView('demo');$('live-view').onclick=()=>setView('live');$('filter').onchange=render;
$('demo').onclick=async()=>{busy=true;$('demo').disabled=true;try{setView('demo');const result=await api('/api/demo',{mode:$('mode').value});$('result').textContent='DEMO 验证完成 · 模拟上传 '+result.simulated_upload_count+' 次。未发出真实网络请求。';await refresh();}catch(error){$('result').textContent=error.message;}finally{busy=false;$('demo').disabled=!connected;}};
setInterval(()=>{if(!document.hidden&&Date.now()>=nextRefreshAt)refresh();},1500);
$('source-filter').onchange=()=>{$('session-filter').value='';render();};
$('session-filter').onchange=render;

$('ollama-demo').onclick=async()=>{
  busy=true;$('demo').disabled=true;$('ollama-demo').disabled=true;setView('demo');
  $('result').textContent='本地模型正在加载并推理，首次可能需要数分钟；完成后保留加载状态 5 分钟…';
  try {const result=await api('/api/ollama/demo',{model:'qwen3:8b'},310000);$('result').textContent='Ollama / '+result.model+'：'+result.response;await refresh();}
  catch(error){$('result').textContent='模型演示失败：'+error.message+'。请先启动 scripts/start-ollama-demo.ps1。';}
  finally {busy=false;$('demo').disabled=!connected;$('ollama-demo').disabled=!connected;}
};

// A launch ticket is short-lived and single-use; remove it from history before any request.
const launchParams=new URLSearchParams(location.hash.slice(1));
const launchTicket=launchParams.get('connect');
let requestedEvent=launchParams.get('event');
function focusRequestedEvent(){
  if(!requestedEvent||compactMode)return;
  const e=events.find(row=>row.event_id===requestedEvent);
  if(!e){$('result').textContent='未在最近 200 条记录中找到该事件，可能已超出列表范围；请勿审批其他事件代替。';return;}
  requestedEvent=null;$('source-filter').value='';$('filter').value='all';setView(e.is_demo?'demo':'live');details(e);
  $('result').textContent='已定位所点击的事件；请查看右侧详情与可用的审批操作。';
}
let ticketConnecting=false,nativeRecoveryAttempted=false;
function recoverNativeConnection(){
  if(token||connected||ticketConnecting||nativeConnecting||nativeRecoveryAttempted||!window.pywebview?.api?.connection_ticket)return;
  nativeRecoveryAttempted=true;void reconnectNative();
}
async function connectWithTicket(ticket,recover=false){
  if(ticketConnecting)return;
  ticketConnecting=true;
    try {
      const response=await fetch('/api/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket}),signal:AbortSignal.timeout(5000)});
      if(!response.ok)throw Error('启动连接已过期，请重新双击 Guardian。');
      const credential=(await response.json()).token;
      if(typeof credential!=='string'||!credential||credential.length>1024)throw Error('本地连接响应无效，请重新打开 Guardian。');
      token=credential;await refresh();if(connected){$('login').hidden=true;setView('live');focusRequestedEvent();}
    }catch(error){$('result').textContent=error.message;$('connection-help').textContent=error.message+' 无需输入模型 API 密钥。';}
    finally{ticketConnecting=false;if(recover)recoverNativeConnection();}
}
if(launchTicket){
  history.replaceState(null,'',location.pathname+location.search);
  void connectWithTicket(launchTicket,true);
}
let nativeConnecting=false;
async function reconnectNative(){
  const bridge=window.pywebview?.api;
  if(!bridge?.connection_ticket||ticketConnecting||nativeConnecting)return;
  nativeConnecting=true;
  const button=$('native-reconnect');button.hidden=false;button.disabled=true;
  try{await connectWithTicket((await bridge.connection_ticket()).ticket);}
  catch{$('connection-help').textContent='本机守卫暂时不可用。请双击 Guardian.vbs 启动服务后重试，无需粘贴令牌。';}
  finally{nativeConnecting=false;button.disabled=false;}
}
$('native-reconnect').onclick=reconnectNative;
window.addEventListener?.('pywebviewready',()=>{
  if(!window.pywebview?.api?.connection_ticket)return;
  $('native-reconnect').hidden=false;
  recoverNativeConnection();
});

function renderDiagnostics(rows) {
  renderClientOverview(rows);
  const labels={adapter_refresh_required:'在线实例需加载新版',checks_only:'仅执行前检查 · 无关联回执',mode_unverified:'新模式待实际检查确认',idle_unverified:'近期无动作 · 当前在线未确认',config_error:'配置异常',partial_config:'钩子不完整',upgrade_required:'接入需要更新',disabled:'未配置',demo_only:'仅演示工具',heartbeat_lost:'实例心跳超时',history_only:'仅有历史记录',receiving:'检查与回执已收到',awaiting_receipt:'已收到检查 · 等待回执',online:'实例心跳在线',observed:'已收到事件 · 在线状态未知',awaiting_event:'已配置 · 等待真实检查'};
  for(const row of rows) {
    const el=$('diagnostic-'+row.client);
    if(el&&!compactMode){
      const parts=[row.readiness==='receipt_gaps'?'部分动作回执待核对':labels[row.readiness||row.state]||row.state];
      if(row.events_since_start!==undefined)parts.push(`本次服务启动后：${row.events_since_start} 次检查 / ${row.receipts_since_start} 条回执（最近 200 条范围）`);
      if(row.last_event)parts.push('最近检查：'+new Date(row.last_event).toLocaleString());
      if(row.configured_mode)parts.push('设置：'+(row.configured_mode==='protect'?'保护':'观察')+'；最近实际检查：'+(row.last_observed_mode?(row.last_observed_mode==='protect'?'保护':'观察'):'未确认'));
      if(row.heartbeat_supported===false)parts.push('无常驻心跳；空闲不等于断线，历史记录不证明当前在线');
      if(row.lifecycle?.protection==='unverified')parts.push('保护效果需按具体动作验证，在线不等于全部窗口已受保护');
      if(row.configuration_matched_instances)parts.push(`${row.configuration_matched_instances} 个在线实例的加载声明与本地接入配置匹配`);
      if(row.configuration_unmatched_instances)parts.push(`${row.configuration_unmatched_instances} 个在线实例尚未匹配当前接入配置；可能是旧入口、其他配置范围或配置已撤销`);
      if(row.generic_only_in_window)parts.push(`最近记录中 ${row.generic_only_in_window} 次动作无专用规则`);
      if(row.receipt_gaps_since_start)parts.push(`${row.receipt_gap_sessions} 个会话共 ${row.receipt_gaps_since_start} 次动作超过 30 秒未收到回执（不代表执行失败）`);
      if(row.waiting_decisions_since_start)parts.push(`${row.waiting_decisions_since_start} 次动作待审批或原生确认（原调用停止回执不等于已审批）`);
      if(row.authorized_retries_since_start)parts.push(`${row.authorized_retries_since_start} 次单次授权待原会话重试（尚不代表已执行）`);
      if(row.next_step)parts.push(row.next_step);
      const issueNames={matcher:'匹配范围已改变',duplicate:'重复接入命令',conditional_or_async:'条件执行或异步执行',disabled:'钩子已禁用',type:'处理器类型已改变',execution_override:'启动参数或环境已改变',shell:'Shell 与安装协议不符',timeout:'超时不足或无效'};
      for(const issue of row.configuration_issues||[]){const [event,code]=issue.split(':');parts.push(event+'：'+(issueNames[code]||'配置需核对'));}
      el.textContent=parts.join(' · ');
      for(const eventId of (row.receipt_gap_event_ids||[]).slice(0,10)){
        const event=events.find(e=>e.event_id===eventId);if(!event)continue;
        const button=node('button','btn',`核对 ${event.session_id.slice(0,8)} · ${event.tool_name}`);
        button.disabled=!!replay;
        button.onclick=()=>{
          if(replay)return;
          $('source-filter').value='';$('filter').value='all';setView('live');
          $('session-filter').value=sessionKey(event);render();details(event);
        };
        el.append(button);
      }
    }
  }
  const relevant=rows.filter(row=>row.adapter!=='codex-mcp'&&(row.state!=='disabled'||row.readiness==='partial_config'));
  const checked=relevant.filter(row=>row.events_since_start>0).length;
  const gaps=relevant.filter(row=>['config_error','partial_config','upgrade_required','adapter_refresh_required','heartbeat_lost','history_only','awaiting_event','awaiting_receipt','receipt_gaps','mode_unverified','idle_unverified','checks_only'].includes(row.readiness)).length;
  const message=relevant.length?`本次启动后 ${checked}/${relevant.length} 类接入收到检查${gaps?' · '+gaps+' 类待核对':''}；仅覆盖已接入工具`:'尚无已配置接入；请打开控制台扫描并验证';
  $('monitor-status').textContent=message;
  const hint=$('overlay-health');if(hint){hint.textContent=gaps||!checked?'接入待核对':'已收到动作';hint.title=message;hint.setAttribute('aria-label',message);}
}
function renderClientOverview(rows){
  if(compactMode)return;
  const host=$('client-overview');host.replaceChildren();
  const active=rows.filter(row=>row.adapter!=='codex-mcp'&&row.adapter!=='ollama-local'&&row.state!=='disabled');
  if(!active.length){host.append(node('p','note','尚无接入记录，展开下方管理入口开始扫描。'));return;}
  for(const row of active){
    const card=node('div','client-summary','');
    card.append(node('strong','',sourceName({source_adapter:row.adapter})),node('span','summary-mode',row.configured_mode==='protect'?'严格保护':row.configured_mode==='observe'?'陪伴观察':'模式待确认'));
    const states={receiving:'已收到动作与回执',online:'实例在线',checks_only:'仅执行前检查',awaiting_event:'等待首次动作',disabled:'尚未接入',history_only:'仅有历史记录',idle_unverified:'近期无动作',mode_unverified:'新模式待验证',awaiting_receipt:'等待执行回执'};
    const key=row.readiness||row.state;
    card.append(node('p','',states[key]||'接入状态需核对'));host.append(card);
  }
}
function renderConnectionChecks(overview){
  const host=$('connection-verification');host.replaceChildren();
  if(!connectionChecks.size)return;
  host.append(node('p','note','验证提示词：请只读取当前项目的 README 文件并概括内容，不修改文件、不运行命令、不访问网络。请在你选择的客户端普通对话中发送；这里不会自动发送。'));
  const copyPrompt=node('button','btn','复制验证提示词');
  copyPrompt.disabled=privacyMode||!!replay||!connected;
  copyPrompt.onclick=async()=>{
    if(copyPrompt.disabled||privacyMode||replay||!connected||!connectionChecks.size)return;
    try{
      if(!navigator.clipboard?.writeText)throw Error('Clipboard unavailable');
      await navigator.clipboard.writeText('请只读取当前项目的 README 文件并概括内容，不修改文件、不运行命令、不访问网络。');
      $('result').textContent='验证提示词已复制，请粘贴到要验证的客户端普通对话中发送。复制本身不代表接入已验证。';
    }catch(error){$('result').textContent='未能写入剪贴板，请手动选择上面的验证提示词复制。';}
  };
  host.append(copyPrompt);
  host.append(node('p','note','本轮只接收开始后两分钟内的新读取检查；这里只核对该客户端上报的动作，不证明其所有窗口或所有工具均受保护。'));
  for(const [client,check] of connectionChecks){
    const box=node('div','appitem','');box.append(node('strong','',sourceName({source_adapter:check.adapter})));
    let message;
    if(!connected)message='服务离线，验证暂停；不能确认当前接入。';
    else if(overview.service_started_at!==check.service)message='服务已重启，本轮验证已失效；请重新点击验证按钮。';
    else{
      const diagnostic=(overview.diagnostics||[]).find(row=>row.client===client);
      if(diagnostic&&['disabled','config_error','partial_config','upgrade_required','adapter_refresh_required'].includes(diagnostic.readiness))message=diagnostic.next_step||'接入配置待核对。';
      else{
        // Bind evidence to one actual event, never combine one check with another receipt.
        if(!check.eventId&&!check.expired){
          const deadline=Date.parse(check.started)+120000;
          const candidates=overview.events.filter(e=>!e.is_demo&&(e.source_adapter||e.adapter_id)===check.adapter&&Date.parse(e.occurred_at)>Date.parse(check.started)&&Date.parse(e.occurred_at)<=deadline);
          const reads=candidates.filter(e=>e.rule_coverage?.canonical_tool==='Read'||['Read','read','read_file'].includes(e.tool_name));
          const sessions=new Map();for(const row of reads)if(!sessions.has(sessionKey(row)))sessions.set(sessionKey(row),row);
          const candidate=reads[0];
          if(sessions.size>1||(check.needsSessionChoice&&sessions.size)){
            check.needsSessionChoice=true;
            message='本轮发现多个会话同时上报读取，请选择刚发送验证提示词的会话；不能仅凭其他窗口的活动确认本次接入。';
            for(const row of sessions.values()){
              const choose=node('button','btn','核对会话 '+sessionLabel(row)+' · '+new Date(row.occurred_at).toLocaleTimeString());
              choose.disabled=privacyMode||!!replay;
              choose.onclick=()=>{
                if(privacyMode||replay||!connected||check.eventId||connectionChecks.get(client)!==check||latestOverview?.service_started_at!==check.service)return;
                const current=latestOverview.events.find(e=>e.event_id===row.event_id);
                if(!current||sessionKey(current)!==sessionKey(row))return;
                check.eventId=row.event_id;renderConnectionChecks(latestOverview);
              };box.append(choose);
            }
          }
          else if(candidate)check.eventId=candidate.event_id;
          else if(Date.parse(overview.generated_at)>deadline){check.expired=true;}
          else message=candidates.length?'已收到其他工具动作；请按提示读取项目 README，以验证读取与回执。':'等待新的读取动作；请重启已配置客户端、完成原生信任提示，再发送上面的提示词。';
        }
        if(check.expired)message='两分钟内没有收到匹配读取，本轮验证已结束；请核对客户端信任和接入状态，再重新开始。';
        if(check.eventId){
          const event=overview.events.find(e=>e.event_id===check.eventId);
          if(!event)message='验证动作已超出最近 200 条窗口；请重新验证，不能把其他动作当作其回执。';
          else{
            const states={tool_returned:'这次读取的检查与工具返回回执均已收到；未核验内容是否正确。',succeeded:'这次读取的检查与客户端成功回执均已收到。',failed:'这次读取已收到检查，但客户端报告执行失败；请查看详情。',blocked:'这次读取已收到检查，但调用被停止；请核对判定与客户端提示。'};
            message=diagnostic?.receipt_supported===false?'这次读取的执行前检查已收到；该适配不支持关联执行回执，请在原客户端确认结果。':states[event.execution_state]||'已收到这次读取检查，等待同一动作的执行回执。';
            if(diagnostic?.configured_mode&&event.mode!==diagnostic.configured_mode)message+=' 当前设置模式尚未由本次动作确认，请重新验证。';
            message+=' 实际模式：'+(event.mode==='protect'?'保护':'观察')+'；会话：'+event.session_id.slice(0,8)+'。';
            const detail=node('button','btn','查看本次验证动作');detail.disabled=!!replay;
            detail.onclick=()=>{if(replay)return;requestedEvent=check.eventId;focusRequestedEvent();};box.append(detail);
          }
        }
      }
    }
    box.append(node('p','note',message));
    const clear=node('button','btn','结束本轮验证');clear.onclick=()=>{connectionChecks.delete(client);renderConnectionChecks(latestOverview||overview);};box.append(clear);host.append(box);
  }
}
function renderSessions(rows) {
  if(!privacyMode&&document.activeElement===$('session-filter'))return;
  const key=JSON.stringify(rows.map(row=>[row.key,row.events]));if(key===sessionSnapshot)return;sessionSnapshot=key;
  const select=$('session-filter'),previous=select.value;select.replaceChildren();
  const all=node('option','','全部会话');all.value='';select.append(all);
  for(const row of rows) {
    const option=node('option','',`${row.is_demo?'演示 · ':''}${sourceName({adapter_id:row.adapter})} · ${sessionLabel(row)} · ${row.events} 次`);
    option.value=row.key;select.append(option);
  }
  select.value=rows.some(row=>row.key===previous)?previous:'';
}

function renderModes(modes, observations=[]) {
  if(!modes)return;
  const latest=Object.fromEntries(Object.keys(modes).map(adapter=>[adapter,observations.find(e=>!e.is_demo&&(e.source_adapter||e.adapter_id)===adapter)]));
  const signature=JSON.stringify([modes,Object.values(latest).map(e=>e?.event_id)]);if(signature===modeSnapshot)return;modeSnapshot=signature;
  const host=$('mode-controls');host.replaceChildren();
  for(const [adapter,name] of (adapterCatalog?adapterCatalog.filter(r=>r.mode_control).map(r=>[r.adapter,r.name]):[['claude-hook','Claude Code'],['gemini-hook','Gemini CLI'],['opencode-plugin','OpenCode'],['codex-hook','Codex 原生 Hooks'],['qoder-hook','Qoder CLI']])) {
    const row=node('div','appitem','');row.append(node('strong','',name));
    const select=node('select','','');select.setAttribute('aria-label',name+' 真实模式');
    for(const [value,label] of [['observe','陪伴观察 · 只提示，不阻断（推荐）'],['protect','严格保护 · 可阻断操作']]){const option=node('option','',label);option.value=value;select.append(option);}
    select.value=modes[adapter]||'observe';
    const button=node('button','btn','保存模式');
    const acknowledge=node('input','','');acknowledge.type='checkbox';acknowledge.checked=false;
    acknowledge.setAttribute('aria-label',name+' 确认严格保护的离线影响');
    const consent=node('label','note','');consent.append(acknowledge,node('span','','我理解：严格保护会拒绝或要求确认动作；后台关闭、失联时也可能阻断读写。'));
    const explanation=node('p','note','');
    const updateExplanation=()=>{acknowledge.checked=false;consent.hidden=select.value!=='protect';explanation.textContent=select.value==='protect'?'需要后台持续运行。关闭悬浮球仅隐藏窗口；如需停止监督，请先保存陪伴观察或撤销接入。':'后台在线时监控并提示风险，支持的客户端可返回来源会话；后台关闭时不由守卫阻断操作，客户端自身权限仍有效。';};
    select.onchange=updateExplanation;updateExplanation();
    button.onclick=async()=>{const mode=select.value;if(mode==='protect'&&!acknowledge.checked){$('result').textContent='请先确认严格保护的离线影响；日常桌宠体验推荐陪伴观察。';return;}button.disabled=true;select.disabled=true;try{await api('/api/policy',{adapter,mode});modeSnapshot='';await refresh();$('result').textContent=name+(mode==='observe'?' 已保存陪伴观察：只提示，不由守卫阻断操作。':' 已保存严格保护：后台不可用时也可能阻断操作。')+' 下一次工具检查生效；已开始执行的工具不受追溯影响。';}catch(error){$('result').textContent=error.message;}finally{button.disabled=false;select.disabled=false;acknowledge.checked=false;}};
    row.append(select,button,consent,explanation);const recent=latest[adapter];row.append(node('p','note',recent?'最近检查实际模式：'+(recent.mode==='protect'?'保护':'观察')+' · '+new Date(recent.occurred_at).toLocaleTimeString():'尚无真实检查确认；保存配置不代表客户端已经加载。'));host.append(row);
  }
}
function renderApproval(e) {
  const host=$('approval-controls');host.replaceChildren();
  if(privacyMode)return;
  if(replay){host.append(node('p','note','历史回放只读；退出回放后再处理当前事件。'));return;}
  if(e.is_demo)return;
  const states={unknown:'尚无执行回执',blocked:'适配器报告：本次调用已停止',tool_returned:'工具已返回；未核验业务是否成功',succeeded:'客户端报告执行成功',failed:'客户端报告执行失败'};
  host.append(node('p','note',states[e.execution_state]||'尚无执行回执'));
  if(e.output_scan){
    const scan=e.output_scan;
    const note=outputWarning(e)?'工具返回内容含指令覆盖表达；可能是引用或示例，未证明发生注入。工具已经返回，不代表被阻断；后续动作仍独立检查。':scan.status==='scanned'?'工具返回文本已做有限词法扫描，未命中本规则；不代表内容安全。':'客户端没有提供可扫描的返回文本；不代表内容已检查。';
    host.append(node('p','note',note+(scan.truncated?' 扫描已截断，剩余内容未检查。':'')+' 正文仅在客户端处理，守卫不保存返回正文。'));
  }
  if(e.native_confirmation){
    host.append(node('p','note',e.native_confirmation.outcome==='confirmed'?'客户端报告：已通过本次原生确认；仅针对原动作，不代表执行成功。':'客户端报告：本次动作未获得原生确认；可能取消、无交互界面或上下文已变化。'));
  }
  if(e.decision_state==='awaiting_client_confirmation'&&e.approval_status!=='revoked'){
    if(!e.execution_state||e.execution_state==='unknown')host.append(node('p','note','请在 '+sourceName(e)+' 原生权限提示中判断；控制台未收到确认结果前不会显示已授权。'));
    else host.append(node('p','note','本次调用已有客户端回执，结果见上方；守卫没有独立的原生审批决定回执，不再提示此调用等待确认。'));
    return;
  }
  const state=e.approval_status;
  if(!state)return;
  host.append(node('p','note',e.working_directory_context==='reported'?'单次授权同时绑定客户端上报的工作目录；目录变化需要重新检查。':'客户端未上报工作目录；守卫无法核对工具参数之外的相对路径上下文，请在原客户端核对。'));
  const pendingReceipt=e.execution_state==='blocked'?'适配器已报告原调用停止。':'已返回要求停止并复核的决定；尚未确认原调用停止，请核对客户端。';
  const labels={pending:'待审批：'+pendingReceipt+'允许后须在原会话重试完全相同的动作；不自动执行。',approved:'已授权一次：请在有效期内于原会话重试完全相同的动作。',consumed:'单次授权已使用。',rejected:'用户已拒绝本次审批。',revoked:revocationNote(e),expired:'审批已过期；重新发起动作后重新检查。'};
  host.append(node('p','note',labels[state]||state));
  if(!compactMode&&(state==='consumed'||e.approved_from)){
    const targetId=e.approved_from||events.find(row=>row.approved_from===e.event_id)?.event_id;
    if(targetId){
      const link=node('button','btn',e.approved_from?'查看原审批事件':'查看重试动作与回执');
      link.onclick=()=>{requestedEvent=targetId;focusRequestedEvent();};host.append(link);
    }else host.append(node('p','note','关联重试不在最近 200 条记录中；不能据此判断执行结果。'));
  }
  if(e.approval_expires_at)host.append(node('p','note','有效期至 '+new Date(e.approval_expires_at*1000).toLocaleTimeString()));
  if(state==='pending')for(const [decision,label] of [['approve','允许一次重试'],['reject','拒绝本次']]){
    const button=node('button','btn',label);button.onclick=async()=>{
      if(button.disabled||privacyMode||replay||selected!==e.event_id||!connected)return;
      button.disabled=true;
      try{await api('/api/approvals',{event_id:e.event_id,decision});await refresh();}
      catch(error){if(!privacyMode&&!replay&&selected===e.event_id)$('result').textContent=error.message+'，请刷新并核对审批是否过期。';button.disabled=false;}
    };host.append(button);
  }
}

// Separate authenticated view; never place the management token in a URL or storage.
if(compactMode){
  document.body.classList.add('compact-monitor');if(orbMode)document.body.classList.add('orb-monitor');document.title=orbMode?'Guardian · 粒子核心':'Guardian · 最近 5 条动作';
  $('monitor-open').textContent='打开控制台 ↗';$('monitor-status').hidden=false;
  $('orb-open').textContent=orbMode?'动作面板 ↗':'◉ 粒子';
  setView('live');
}
async function openGuardianWindow(route,name,features) {
  if(!connected){$('connection').textContent='请先连接本地服务';return;}
  const popup=window.open('',name,features);
  if(!popup){$('connection').textContent='弹窗被拦截，请允许本站弹窗';return;}
  try{
    const ticket=await api('/api/launch-ticket',{});
    if(popup.closed)return;
    popup.location.replace(route+'#connect='+encodeURIComponent(ticket.ticket));
    popup.focus();
  }catch(error){popup.close();$('connection').textContent='打开失败：'+error.message;}
}
$('monitor-open').onclick=()=>openGuardianWindow(compactMode?'/':'/monitor',compactMode?'guardian-console':'guardian-monitor',compactMode?'popup,width=1280,height=860':'popup,width=340,height=400,resizable=yes,scrollbars=yes');
$('orb-open').onclick=()=>openGuardianWindow(orbMode?'/monitor':'/orb',orbMode?'guardian-monitor':'guardian-orb',orbMode?'popup,width=340,height=400,resizable=yes':'popup,width=240,height=260,resizable=yes');

if(desktopMode){
  document.body.classList.add('desktop-overlay');
  document.querySelector('.coreband').classList.add('pywebview-drag-region');
  document.title='Guardian Desktop';
}
$('desktop-open').onclick=async()=>{
  try{await api('/api/desktop/open',{});$('result').textContent='桌面悬浮组件已启动；拖动粒子区域可移动，鼠标移入显示关闭按钮。';}
  catch(error){$('result').textContent='桌面组件启动失败：'+error.message;}
};
$('overlay-close').onclick=()=>window.pywebview?.api.close();
$('overlay-console').onclick=()=>openDesktopConsole(false);
$('overlay-pin').onclick=async()=>{const pinned=await window.pywebview?.api.toggle_pin();$('overlay-pin').textContent=pinned?'◆':'◇';$('overlay-pin').title=pinned?'取消置顶':'启用置顶';};

const riskNotified=new Set();
function collectDesktopRisks(rows){
  if(!desktopMode)return;
  const retained=new Set(rows.map(e=>e.event_id));
  for(let i=desktopRisks.length-1;i>=0;i--)if(!retained.has(desktopRisks[i].event_id))desktopRisks.splice(i,1);
  for(const e of [...rows].reverse()){
    const index=desktopRisks.findIndex(r=>r.event_id===e.event_id);
    if(index>=0)desktopRisks[index]=e;
    if(riskNotified.has(noticeKey(e))||e.is_demo||Date.parse(noticeTime(e))<overlayStartedAt)continue;
    riskNotified.add(noticeKey(e));
    if(index<0&&(['warn','review','deny'].includes(e.verdict)||outputWarning(e)))desktopRisks.push(e);
  }
  // Bound the companion queue; complete records remain in the console.
  if(desktopRisks.length>20)desktopRisks.splice(0,desktopRisks.length-20);
  if(riskNotified.size>4000){riskNotified.clear();rows.forEach(e=>riskNotified.add(noticeKey(e)));}
  renderDesktopRisk();
}
function renderDesktopRisk(){
  if(!desktopMode)return;
  const e=desktopRisks[0],visible=!!e;
  $('desktop-alert').hidden=!visible;
  document.body.classList.toggle('has-risk-alert',visible);
  if(visible!==lastAlertVisible){lastAlertVisible=visible;window.pywebview?.api.alert_visible?.(visible);}
  if(!e)return;
  const sourceSupported=sourceNavigationCapability(e)!=='unsupported';
  $('desktop-alert-source').disabled=privacyMode||!sourceSupported||sourcePending.has(e.event_id);
  $('desktop-alert-source').textContent=!sourceSupported?'暂不支持自动返回':sourcePending.has(e.event_id)?'正在请求返回…':'请求返回原会话';
  $('desktop-alert-source').title=sourceSupported?'请求客户端导航；是否显示原会话仍需核对':sourceUnavailableNote;
  $('desktop-alert-title').textContent=verdict(e)+' · '+sourceName(e);
  $('desktop-alert').className=e.verdict==='deny'?'risk-deny':'risk-warn';
  const receipts={blocked:'适配器报告已停止本次调用。',tool_returned:'工具已返回，未核验业务是否成功。',succeeded:'客户端报告本次执行成功。',failed:'客户端报告本次执行失败。'};
  const approvalNotes={approved:'授权仅供原会话重试完全相同的动作，不会自动执行。',consumed:'授权已用于另一次检查；请查看重试动作的执行回执。',revoked:revocationNote(e),expired:'审批已过期，需要重新发起检查。',rejected:'用户已拒绝，不会授权重试。'};
  const outcome=(receipts[e.execution_state]||(e.mode==='observe'?'观察模式：仅记录风险，未阻断。':'已返回检查决定，尚无执行回执。'))+(approvalNotes[e.approval_status]||'');
  const explanation=explainAction(e);
  $('desktop-alert-body').textContent=privacyMode?displayTool(e)+' · 详细目标和依据已隐藏。'+outcome:outcome+'\n'+explanation.action+'：'+explanation.why+'\n'+explanation.next;
  $('desktop-alert-count').textContent=desktopRisks.length>1?'另有 '+(desktopRisks.length-1)+' 条风险待查看':'收起只关闭提示，不代表授权。';
  const sourceResult=e.source_navigation||sourceResults.get(e.event_id);
  if(sourceResult&&!privacyMode)$('desktop-alert-count').textContent=sourceResult.kind==='manual_resume'&&!sourceResult.window_foreground_verified?'此客户端暂不能自动激活原窗口；请查看详情中的会话定位方式。':sourceResult.message;
}
function rememberSourceResult(eventId,result){
  sourceResults.set(eventId,result);
  if(sourceResults.size>200)sourceResults.delete(sourceResults.keys().next().value);
}
$('desktop-alert-dismiss').onclick=()=>{desktopRisks.shift();renderDesktopRisk();};
async function openDesktopConsole(fromRisk=true){
  const button=$(fromRisk?'desktop-alert-open':'overlay-console');
  if(button.disabled)return;
  const label=button.textContent;
  const eventId=fromRisk?desktopRisks[0]?.event_id:null;
  button.disabled=true;button.textContent='正在打开…';
  try{
    if(typeof window.pywebview?.api.open_console!=='function')throw Error('桌面连接尚未就绪，请关闭并重新打开悬浮组件');
    const result=await window.pywebview.api.open_console(eventId||null);
    if(!result?.opened)throw Error('详情窗口未能打开，请重启悬浮组件');
    if(fromRisk)$('desktop-alert-count').textContent='详情窗口已打开，审批请在该窗口完成。';
  }catch(error){
    const message='打开失败：'+(error.message||String(error));
    if(fromRisk)$('desktop-alert-count').textContent=message;
    else {$('monitor-status').hidden=false;$('monitor-status').textContent=message;document.body.classList.add('overlay-offline');}
  }finally{button.disabled=false;button.textContent=label;}
}
$('desktop-alert-open').onclick=()=>openDesktopConsole();
window.addEventListener?.('pywebviewready',()=>{if(desktopMode)window.pywebview?.api.alert_visible?.(desktopRisks.length>0);});


let discoveryGeneration=0,onboardingApplying=false;
$('scan-agents').onclick=async()=>{
  if(privacyMode||replay||onboardingApplying)return;
  $('connection-manager').open=true;
  const generation=++discoveryGeneration;
  const current=()=>generation===discoveryGeneration&&!privacyMode&&!replay;
  const button=$('scan-agents'),host=$('discovery-results');
  button.disabled=true;host.replaceChildren(node('p','note','正在检查固定安装位置…'));
  try{
    const report=await api('/api/discovery');
    if(!current())return;
    host.replaceChildren(node('p','note',report.message));
    const selectedClients=new Map(),clientChecks=new Map();let selectionVersion=0;
    const planHost=node('div','onboarding-plan','');
    const summary=node('p','note','勾选客户端后先预览变更；只有确认计划后才会写入接入配置。');
    for(const row of report.clients){
      const box=node('div','appitem',''),label=node('label','',''),check=node('input','','');
      check.type='checkbox';check.disabled=row.integration_available!==true||!(row.detected||row.config_present);
      clientChecks.set(row.id,{check,name:row.name});
      check.onchange=()=>{if(!current()||onboardingApplying||check.disabled)return;selectionVersion++;planHost.replaceChildren();if(check.checked)selectedClients.set(row.id,row.name);else selectedClients.delete(row.id);
        summary.textContent=selectedClients.size?'已选择：'+[...selectedClients.values()].join('、')+'。尚未启用接入，请先预览变更。':'尚未选择客户端。';};
      label.append(check,node('strong','',row.name));box.append(label);
      box.append(node('div','note',({found:'发现可执行入口',config_only:'仅有配置线索',not_found:'固定位置未发现',unreadable:'检测受限',manual_verification:'需单独验证'}[row.state]||row.state)+' · '+row.coverage));
      const evidence=new Map((row.discovery_evidence||[]).map(item=>[item.path,item]));
      for(const path of row.paths){const hint=evidence.get(path);box.append(node('div','note',path+(hint?' · '+hint.source+' / '+hint.command:'')));}
      for(const path of row.config_paths||[])box.append(node('div','note','配置线索：'+path));
      for(const scope of row.configuration_scopes||[])box.append(node('div','note','接入范围：'+scope.runtime+' · 当前用户 · '+scope.configuration_path+'（尚未绑定运行实例）'));
      if(row.configuration_source&&row.configuration_source!=='default')box.append(node('div','note','配置目录来源：'+row.configuration_source+'；仅代表守卫当前进程可见的环境'));
      if(row.capabilities?.precheck){
        const cap=row.capabilities;
        box.append(node('div','note','适配器能力：执行前检查'+(cap.receipt?'、执行回执':'；暂不支持关联回执')+(cap.approval==='native_confirmation'?'；使用客户端原生确认':cap.approval==='retry_required'?'；授权后需重新发起动作':'')+'。能力声明不等于本机已验证。'));
      }
      if(row.note)box.append(node('div','note',row.note));
      host.append(box);
    }
    host.append(summary);
    for(const [action,label] of [['install','预览全局接入'],['uninstall','预览撤销接入']]){
      const preview=node('button','btn',label);
      preview.onclick=async()=>{
        if(!current()||onboardingApplying)return;
        if(!selectedClients.size){summary.textContent='请先勾选客户端。';return;}
        const version=++selectionVersion;preview.disabled=true;planHost.replaceChildren();
        try{
          const plan=await api('/api/onboarding/plan',{clients:[...selectedClients.keys()],action});
          if(!current()||version!==selectionVersion)return;
          const expiresAt=Date.now()+Math.min(300,Math.max(0,Number(plan.expires_in??300)))*1000;
          summary.textContent='请核对下方路径和变更；预览最多 5 分钟有效，确认后才写入配置。';
          planHost.replaceChildren(node('p','note',plan.note));
          for(const item of plan.clients){
            planHost.append(node('p','note',item.name+' · '+item.change+'：'+item.path+(item.requires_trust?'；需在客户端完成适用的信任确认':'')));
            for(const warning of item.warnings||[])planHost.append(node('p','note',warning));
          }
          const confirm=node('button','btn primary',action==='install'?'确认备份并接入':'确认仅撤销 Guardian 接入');
          const cancel=node('button','btn','取消');cancel.onclick=()=>{selectionVersion++;planHost.replaceChildren();};
          confirm.onclick=async()=>{
            if(!current()||version!==selectionVersion||confirm.disabled||onboardingApplying)return;
            if(Date.now()>=expiresAt){planHost.replaceChildren(node('p','note','预览已过期，未写入配置。请重新预览后确认。'));return;}
            confirm.disabled=true;cancel.disabled=true;onboardingApplying=true;button.disabled=true;
            for(const {check} of clientChecks.values()){check.wasDisabled=check.disabled;check.disabled=true;}
            try{
              const result=await api('/api/onboarding/apply',{plan_id:plan.plan_id,confirmed:true});
              if(!current())return;
              planHost.replaceChildren();
              for(const item of result.results){
                planHost.append(node('p','note',(selectedClients.get(item.id)||item.id)+'：'+item.message));
                if(action==='install'&&item.preflight){
                  planHost.append(node('p','note',item.preflight.reload_hint+' '+item.preflight.verification_hint));
                  for(const warning of item.preflight.warnings||[])planHost.append(node('p','note',warning));
                }
              }
              const incomplete=result.results.filter(item=>['failed','uncertain'].includes(item.state)).map(item=>item.id);
              if(incomplete.length){
                planHost.append(node('p','note',`还有 ${incomplete.length} 个客户端未确认完成；已完成项保留，没有自动回滚。`));
                const retry=node('button','btn','仅重新预览未完成项');
                retry.onclick=()=>{
                  if(!current()||onboardingApplying)return;
                  selectionVersion++;selectedClients.clear();
                  for(const [id,item] of clientChecks){item.check.checked=incomplete.includes(id);if(item.check.checked)selectedClients.set(id,item.name);}
                  summary.textContent='仅选择未完成项；重新预览后仍需明确确认。';
                  return preview.onclick();
                };
                planHost.append(retry);
              }
              planHost.append(node('p','note',action==='install'?'配置完成不等于已保护。重启对应客户端，完成其信任提示，再做一次无害读取，核对真实事件与回执。':'已撤销项需重启对应客户端后生效；仍在运行的旧插件可能继续上报，未完成项需单独核对。'));
              const ready=result.results.filter(item=>['configured','preserved'].includes(item.state)).map(item=>item.id);
              if(action==='install'&&ready.length){
                const verify=node('button','btn primary','检查接入是否生效');
                verify.onclick=async()=>{
                  verify.disabled=true;
                  try{await beginConnectionChecks(ready);}
                  catch(error){summary.textContent='无法开始接入验证：'+error.message;}
                  finally{verify.disabled=false;}
                };
                planHost.append(verify);
              }
              integrationSnapshot='';await refresh();
            }catch(error){if(current())planHost.replaceChildren(node('p','note','接入未确认完成：'+error.message+'。请重新扫描并预览，勿重复使用旧计划。'));}
            finally{onboardingApplying=false;button.disabled=false;for(const {check} of clientChecks.values())check.disabled=check.wasDisabled;}
          };
          planHost.append(confirm,cancel);
        }catch(error){if(current()&&version===selectionVersion)planHost.replaceChildren(node('p','note','无法生成计划：'+error.message));}
        finally{preview.disabled=false;}
      };
      host.append(preview);
    }
    host.append(planHost);
  }catch(error){if(current())host.replaceChildren(node('p','note','扫描失败：'+error.message));}
  finally{if(generation===discoveryGeneration)button.disabled=onboardingApplying;}
};

$('overlay-stage').onclick=()=>{const dark=document.body.classList.toggle('cosmic-stage');$('overlay-stage').title=dark?'恢复透明悬浮':'切换黑底光效预览';$('overlay-stage').setAttribute('aria-pressed',String(dark));};

let discoveredReviewModels=[];
let discoveredSemanticModels=[];
function renderSemanticGate(state){
  const preparation=state?.preparation;
  const label=!state?.enabled?'未启用':preparation?.status==='preparing'?'正在用合成输入预热':preparation?.ready?'已预热 · 不代表满足实时预算':preparation?.status==='failed'?'预热失败 · 动作检查将请求人工确认':'未预热或预热已过期';
  const config=state?.configuration;
  $('semantic-status').textContent=label+(config?` · ${config.model} / ${config.port} · ${config.clients.join('、')} · 仅本次运行`:'');
  $('semantic-prepare').disabled=!!replay||!state?.enabled||preparation?.status==='preparing';
  $('semantic-disable').disabled=!!replay||!state?.enabled;
}
$('semantic-scan').onclick=async()=>{
  const button=$('semantic-scan');button.disabled=true;
  try{
    const data=await api('/api/models/local',undefined,10000);
    discoveredSemanticModels=data.services.flatMap(service=>service.models.map(model=>({port:service.port,name:model.name,size:model.size})));
    const select=$('semantic-model');select.replaceChildren();const empty=node('option','','选择本地模型');empty.value='';select.append(empty);
    discoveredSemanticModels.forEach((model,index)=>{const option=node('option','',localModelLabel(model));option.value=String(index);select.append(option);});select.value='';
    $('semantic-confirmation').replaceChildren(node('p','note',discoveredSemanticModels.length?'只列出已安装本地模型；选择客户端后预览配置。':'未发现可用模型，不会自动下载。'));
  }catch(error){discoveredSemanticModels=[];$('semantic-confirmation').replaceChildren(node('p','note','发现失败：'+error.message));}
  finally{button.disabled=false;}
};
$('semantic-preview').onclick=()=>{
  const host=$('semantic-confirmation');host.replaceChildren();if(replay){host.append(node('p','note','回放期间只读。'));return;}
  const index=$('semantic-model').value;const model=index!==''?discoveredSemanticModels[Number(index)]:null;
  const clients=['claude-hook','opencode-plugin','codex-hook','gemini-hook'].filter(client=>$('semantic-client-'+client).checked);
  if(!model||!clients.length){host.append(node('p','note','先发现并选择模型，至少勾选一个客户端。'));return;}
  const config={enabled:true,confirmed_raw_local_processing:true,clients,port:model.port,model:model.name,runtime:$('semantic-runtime').value||'cpu'};
  host.append(node('p','note',`将 ${clients.join('、')} 的原始工具参数发送至本机 ${model.port} / ${model.name}，运行方式 ${config.runtime}。不会保存参数或改变客户端模式。未预热、超时或无法判断时，保护模式请求审批。重启服务关闭实验。`));
  const confirm=node('button','btn','确认原始参数本地处理并启用实验');const cancel=node('button','btn','取消');
  cancel.onclick=()=>host.replaceChildren();
  confirm.onclick=async()=>{confirm.disabled=true;cancel.disabled=true;try{const state=await api('/api/semantic/config',config);host.replaceChildren(node('p','note','配置已启用，请用合成输入预热；预热不是检测效果验收。'));renderSemanticGate(state);}catch(error){host.replaceChildren(node('p','note','未确认启用：'+error.message));}};
  host.append(confirm,cancel);
};
$('semantic-prepare').onclick=async()=>{try{renderSemanticGate(await api('/api/semantic/prepare',{confirmed:true}));}catch(error){$('semantic-confirmation').replaceChildren(node('p','note','预热未启动：'+error.message));}};
$('semantic-disable').onclick=async()=>{try{renderSemanticGate(await api('/api/semantic/config',{enabled:false}));$('semantic-confirmation').replaceChildren(node('p','note','实验已关闭；当前检查与已发生动作不能撤回。'));}catch(error){$('semantic-confirmation').replaceChildren(node('p','note','关闭未确认：'+error.message));}};
$('scan-models').onclick=async()=>{
  const button=$('scan-models');button.disabled=true;
  try{
    const data=await api('/api/models/local',undefined,10000);
    discoveredReviewModels=data.services.flatMap(service=>service.models.map(model=>({port:service.port,name:model.name,size:model.size})));
    const select=$('review-model');select.replaceChildren();
    const empty=node('option','','选择本地模型');empty.value='';select.append(empty);
    discoveredReviewModels.forEach((model,index)=>{const option=node('option','',localModelLabel(model));option.value=String(index);select.append(option);});select.value='';
    $('model-discovery-status').textContent=discoveredReviewModels.length?'只列出本地已安装模型，不自动下载。文件大小不是内存需求或速度保证；大模型在 CPU 上可能等待较久，可查看复核状态，完成后显示耗时。':'未发现可用本地模型。请启动 Ollama，并确认 11434 或 11435 端口有已安装的本地模型。';
  }catch(error){discoveredReviewModels=[];$('review-model').replaceChildren();$('model-discovery-status').textContent='发现失败：'+error.message;}
  finally{button.disabled=false;}
};
let reviewTaskEvent=null,reviewTaskDraft='';
function clearReviewTask(){reviewTaskEvent=null;reviewTaskDraft='';}
function renderModelReview(event){
  if(reviewTaskEvent===event.event_id&&!replay&&document.activeElement?.id==='review-task-input'
      &&!['queued','running'].includes(event.model_review?.status))return;
  if(reviewTaskEvent!==event.event_id){clearReviewTask();reviewTaskEvent=event.event_id;}
  const host=$('review-controls');host.replaceChildren();
  if(replay){clearReviewTask();host.append(node('p','note','历史回放只读；退出回放后再处理当前事件。'));return;}
  if(event.is_demo){host.append(node('p','note','请在真实接入中选择事件；演示模型调用与事件复核分别标注。'));return;}
  const result=event.model_review;
  if(result){
    const states={cancelled:'复核已取消（不影响 Agent 动作）',queued:'排队中',running:'本地复核中',failed:'复核失败或输出无效',interrupted:'复核被服务重启或退出中断',completed:'复核完成'};
    const assessments={concern:'提示风险线索',uncertain:'上下文不足，无法判断',no_additional_signal:'未发现额外线索；不代表安全'};
    const categories={data_transfer:'数据外传',destructive_action:'破坏性动作',credential_access:'凭据访问',instruction_injection:'指令注入',security_change:'安全设置变更',insufficient_context:'上下文不足'};
    host.append(node('p','note',(states[result.status]||'状态未知')+' · '+result.model+(result.runtime==='cpu'?' · CPU 兼容模式':' · 自动设备')+(result.assessment?' · '+assessments[result.assessment]:'')+(result.latency_ms!==undefined?' · '+result.latency_ms+' ms':'')));
    if(result.scope==='bounded_related_events')host.append(node('p','note','已采用同会话相关摘要：'+result.context_count+' 条 · '+new Date(result.context_captured_at).toLocaleTimeString()+(result.context_truncated?' · 已达范围预算，部分记录未送入模型':'')+'。这是历史线索，不是任务授权或因果证明。'));
    if(result.error)host.append(node('p','note',result.error==='context_history_removed'?'相关历史已清理，复核取消。':result.error==='local_model_busy'?'本地模型正用于其他检查或预热，本次复核未启动；稍后可手动重试，原判定与审批未改变。':result.error==='local_review_timeout'?'模型超过 120 秒预算。可选择 CPU 兼容模式或更小的本地模型后重试；原判定与审批未改变。':result.error==='local_service_unavailable'?'本地模型服务不可用；请检查 Ollama。':'模型不可用或输出不符合结构要求，未采用该结果。'));
    if(result.categories?.length)host.append(node('p','note','模型推测（未验证）：'+result.categories.map(code=>categories[code]||'未知类型').join('、')));
    if(result.task_context_provided)host.append(node('p','note','本次使用了你临时补充的任务说明；正文不写入守卫历史，不构成执行授权。'));
    if(result.evidence_status==='insufficient')host.append(node('p','note','模型未提供可对应的摘要引用，已降为上下文不足；未采用缺乏引用的风险分类。'));
    if(result.evidence_status==='references_matched'){
      host.append(node('p','note','以下引用已与发送的历史摘要逐字核对；仅证明引用存在，不证明风险推断或因果关系正确。'));
      const fields={action_preview:'动作摘要',findings:'规则线索',explanations:'规则解释',output_scan:'返回扫描'};
      for(const ref of (result.evidence||[]).slice(0,6))host.append(node('p','note',
        '证据 '+(ref.event_index+1)+' · '+(categories[ref.category]||'未知类型')+' · '+(fields[ref.field]||'摘要')+'：'+ref.quote));
    }
    if(result.status==='completed'&&!result.evidence_check)host.append(node('p','note','这是旧版复核结果，尚未核对证据引用；可重新提交复核。'));
  }
  if(result?.status==='queued'||result?.status==='running'){
    const cancel=node('button','btn','取消这次模型复核');
    cancel.onclick=async()=>{cancel.disabled=true;try{
      const result=await api('/api/reviews/cancel',{event_id:event.event_id});
      if(selected===event.event_id)host.append(node('p','note',result.cancelled?'已停止等待本次复核并丢弃后续结果；不能据此保证 Ollama 已立即释放资源。Agent 动作与审批未改变。':'复核已结束或不在队列中，未执行取消。'));
      await refresh();
    }catch(error){cancel.disabled=false;if(selected===event.event_id)host.append(node('p','note','取消未确认：'+error.message));}};
    host.append(cancel);
  }
  const context=node('textarea','review-task','');context.id='review-task-input';context.value=reviewTaskDraft;context.maxLength=2000;
  context.setAttribute('aria-label','本次复核的可选任务说明');context.setAttribute('placeholder','可选：这次任务要做什么、允许的范围。不填写密码或密钥。');context.setAttribute('autocomplete','off');context.setAttribute('spellcheck','false');
  context.disabled=result?.status==='queued'||result?.status==='running';
  host.append(node('p','note','可选任务说明：最多 2000 UTF-8 字节，原文发送给所选本地 Ollama，仅用于本次复核；不写入守卫历史，不等于批准。Ollama 自身日志由其配置决定。'),context);
  const defaultLabel=$('review-scope').value==='related'?'确认发送相关动作摘要并复核':'确认发送摘要并复核本次事件';
  const button=node('button','btn',reviewTaskDraft.trim()?'确认发送摘要和任务说明并复核':defaultLabel);
  context.oninput=()=>{reviewTaskDraft=context.value;button.textContent=reviewTaskDraft.trim()?'确认发送摘要和任务说明并复核':defaultLabel;};
  button.disabled=result?.status==='queued'||result?.status==='running';
  button.onclick=async()=>{
    const value=$('review-model').value;
    const model=value!==''?discoveredReviewModels[Number(value)]:null;
    if(!model){$('model-discovery-status').textContent='请先发现并选择本地模型。';return;}
    button.disabled=true;
    try{
      const task=reviewTaskEvent===event.event_id?reviewTaskDraft.trim():'';
      await api('/api/reviews/local',{event_id:event.event_id,port:model.port,model:model.name,confirmed:true,runtime:$('review-runtime').value||'auto',...($('review-scope').value==='related'?{include_context:true}:{}),...(task?{task_context:task,task_context_confirmed:true}:{})});
      if(reviewTaskEvent===event.event_id&&reviewTaskDraft.trim()===task){reviewTaskDraft='';context.value='';}
      if(selected===event.event_id)host.append(node('p','note','复核已提交，模型冷启动最多等待约两分钟；不会改变原决定或执行状态。'));
      await refresh();
    }catch(error){button.disabled=false;if(selected===event.event_id)host.append(node('p','note','复核未完成：'+error.message));}
  };
  host.append(button);
}

async function prepareSourceNavigation(){
  const prepare=window.pywebview?.api?.prepare_source_navigation;
  if(prepare){try{await prepare();}catch{/* The source API still returns an explicit routing/focus result. */}}
}

function renderSource(event){
  const host=$('source-controls');host.replaceChildren();
  if(privacyMode)return;
  if(replay){host.append(node('p','note','历史回放只读；退出回放后再处理当前事件。'));return;}
  if(event.is_demo)return;
  if(sourceNavigationCapability(event)==='unsupported'){
    host.append(node('p','note',sourceUnavailableNote));return;
  }
  const button=node('button','btn','定位原 Agent 会话');
  button.disabled=sourcePending.has(event.event_id);
  const previous=event.source_navigation||sourceResults.get(event.event_id);
  const note=node('p','note',previous?.message||'Claude / Codex 尝试前置已识别的唯一关联终端，标签页仍需核对；Codex 无终端线索时请求打开桌面会话；OpenCode 请求选择会话。不可用时提供手动方式。');
  const command=node('code','',previous?.command||'');
  const copy=node('button','btn','复制恢复命令');
  copy.hidden=!command.textContent;
  copy.onclick=async()=>{
    if(privacyMode||replay||selected!==event.event_id||!command.textContent)return;
    copy.disabled=true;
    try{
      await navigator.clipboard.writeText(command.textContent);
      if(!privacyMode&&!replay&&selected===event.event_id)note.textContent='恢复命令已复制；请核对会话后在终端手动使用。没有启动客户端或重试动作。';
    }catch{
      if(!privacyMode&&!replay&&selected===event.event_id)note.textContent='剪贴板不可用，请手动选择下方命令复制。没有执行命令。';
    }finally{copy.disabled=false;}
  };
  button.onclick=async()=>{
    if(privacyMode||replay||selected!==event.event_id||sourcePending.has(event.event_id))return;
    sourcePending.add(event.event_id);
    button.disabled=true;
    note.textContent='正在请求客户端返回目标会话；尚未确认原窗口或标签页。';
    try{
      await prepareSourceNavigation();
      if(privacyMode||replay||selected!==event.event_id)return;
      const result=await api('/api/source/open',{event_id:event.event_id});
      if(privacyMode||replay||selected!==event.event_id)return;
      rememberSourceResult(event.event_id,result);
      note.textContent=result.message;command.textContent=result.command||'';copy.hidden=!command.textContent;
    }catch(error){if(selected===event.event_id)note.textContent='来源定位未完成：'+error.message;}
    finally{sourcePending.delete(event.event_id);button.disabled=false;}
  };
  host.append(button,note,command,copy);
}

$('desktop-alert-source').onclick=async()=>{
  const event=desktopRisks[0];if(!event||privacyMode||sourcePending.has(event.event_id)||sourceNavigationCapability(event)==='unsupported')return;
  sourcePending.add(event.event_id);
  const button=$('desktop-alert-source');button.disabled=true;
  renderDesktopRisk();
  try{
    await prepareSourceNavigation();
    if(privacyMode||desktopRisks[0]?.event_id!==event.event_id)return;
    const result=await api('/api/source/open',{event_id:event.event_id});
    if(privacyMode||desktopRisks[0]?.event_id!==event.event_id)return;
    rememberSourceResult(event.event_id,result);renderDesktopRisk();
  }catch(error){if(!privacyMode&&desktopRisks[0]?.event_id===event.event_id){rememberSourceResult(event.event_id,{kind:'error',message:'来源定位失败：'+error.message});renderDesktopRisk();}}
  finally{sourcePending.delete(event.event_id);button.disabled=privacyMode||!desktopRisks[0]||sourcePending.has(desktopRisks[0].event_id)||sourceNavigationCapability(desktopRisks[0])==='unsupported';renderDesktopRisk();}
};
$('history-export').onclick=async()=>{
  if(privacyMode)return;
  const host=$('history-controls');host.replaceChildren();
  try{
    const report=await api('/api/history/export');
    if(historyExportUrl)URL.revokeObjectURL(historyExportUrl);
    historyExportUrl=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
    const link=node('a','btn',`保存 ${report.count} 条脱敏记录`);link.href=historyExportUrl;link.download='guardian-history.json';
    const show=node('button','btn','显示 JSON（下载不可用时可复制）');
    show.onclick=()=>{$('history-output').hidden=false;$('history-output').textContent=JSON.stringify(report,null,2);};
    host.append(link,show,node('p','note','导出文件仍包含事件时间和风险分类；分享前请核对。'));
  }catch(error){host.textContent=error.message;}
};
$('history-preview').onclick=async()=>{
  const host=$('history-controls');host.replaceChildren();
  try{
    const plan=await api('/api/history/preview-clear',{});
    host.append(node('p','note',`将清理预览时已有的 ${plan.count} 条记录，同时移除相关单次授权、来源定位和复核任务。新到达的事件保留。确认有效期五分钟。`));
    const confirm=node('button','btn','确认清理这批记录'),cancel=node('button','btn','取消');
    confirm.disabled=plan.count===0;cancel.onclick=()=>host.replaceChildren();
    confirm.onclick=async()=>{
      confirm.disabled=true;cancel.disabled=true;
      try{
        const result=await api('/api/history/clear',{plan_id:plan.plan_id,confirmed:true});
        sourceResults.clear();snapshot='';selected=null;investigationSnapshot=null;investigationRequest++;
        $('history-output').textContent='';$('history-output').hidden=true;
        if(historyExportUrl){URL.revokeObjectURL(historyExportUrl);historyExportUrl=null;}
        host.textContent=`已清理 ${result.deleted} 条记录；相关单次授权已移除。已下载的导出文件需自行管理。`;
        await refresh();
      }catch(error){host.textContent='清理未确认完成：'+error.message+'。请重新预览核对。';}
    };
    host.append(confirm,cancel);
  }catch(error){host.textContent=error.message;}
};

function renderFeedback(event){
  const host=$('feedback-controls');host.replaceChildren();
  if(replay){host.append(node('p','note','历史回放只读；退出回放后再处理当前事件。'));return;}
  if(event.is_demo)return;
  const labels={false_positive:'疑似误报',risk_confirmed:'确有风险',missed_risk:'疑似漏报',unsure:'暂不能判断'};
  host.append(node('div','sect-label','我的判断 · 仅本机记录'),node('p','note','反馈用于后续核对，不会自动授权、改变规则或恢复执行。仅保存分类，不收集完整命令或补充文本。'));
  const status=node('p','note',event.user_feedback?`已记录：${labels[event.user_feedback.label]||'待核对'}（用户判断，未经验证）`:'尚未反馈');
  const select=node('select','filter','');select.setAttribute('aria-label','事件反馈分类');
  for(const [value,label] of Object.entries(labels)){const option=node('option','',label);option.value=value;select.append(option);}
  select.value=event.user_feedback?.label||(hasRisk(event)?'false_positive':'missed_risk');
  const save=node('button','btn','保存判断'),clear=node('button','btn','撤回判断');clear.disabled=!event.user_feedback;
  const send=async label=>{
    if(selected!==event.event_id)return;
    save.disabled=true;clear.disabled=true;
    try{
      const updated=await api('/api/feedback',{event_id:event.event_id,label,revision:event.feedback_revision||0});
      events=events.map(row=>row.event_id===updated.event_id?updated:row);snapshot='';
      if(selected===event.event_id)details(updated);
    }catch(error){
      if(selected===event.event_id)status.textContent='反馈未确认保存：'+error.message+'。可能已在其他窗口更新，请刷新后重试。';
    }finally{save.disabled=false;clear.disabled=!event.user_feedback;}
  };
  save.onclick=()=>send(select.value);clear.onclick=()=>send('clear');
  host.append(status,select,save,clear);
}

function replayStatus(){
  $('replay-controls').hidden=!replay;$('replay-start').hidden=!!replay;
  for(const id of ['filter','source-filter','session-filter','demo-view','live-view'])$(id).disabled=!!replay;
  $('demo').disabled=busy||!!replay||!connected;$('ollama-demo').disabled=busy||!!replay||!connected;
  if(!replay){$('replay-status').textContent='回放最近 200 条中的当前筛选；不执行动作。';return;}
  $('replay-play').textContent=replay.playing?'暂停':'播放';
  $('replay-step').disabled=replay.index>=replay.rows.length-1;
  $('replay-play').disabled=replay.index>=replay.rows.length-1;
  $('replay-status').textContent=`历史快照 · ${replay.index+1}/${replay.rows.length} · ${replay.playing?'播放中':'已暂停'} · 长间隔压缩至 3 秒 · ${connected?'后台仍在同步，退出后查看':'服务连接中断，当前仅播放本页快照'}`;
}
function replayPulse(event){
  window.guardianVizPush?.(visualEvent(event));
}
function replayStep(){
  if(!replay||replay.index>=replay.rows.length-1)return;
  replay.index++;replay.elapsed=0;selected=replay.rows[replay.index].event_id;
  if(replay.index===replay.rows.length-1)replay.playing=false;
  render();details(replay.rows[replay.index]);replayPulse(replay.rows[replay.index]);replayStatus();
}
function replayTick(now=Date.now()){
  if(!replay)return;
  const delta=Math.max(0,now-replay.lastTick);replay.lastTick=now;
  if(document.hidden||delta>2000){replay.playing=false;replayStatus();return;}
  if(!replay.playing)return;
  const next=replay.rows[replay.index+1];if(!next)return;
  const rawGap=Date.parse(next.occurred_at)-Date.parse(replay.rows[replay.index].occurred_at);
  const gap=Number.isFinite(rawGap)?Math.max(200,Math.min(3000,rawGap)):1000;
  replay.elapsed+=delta*replay.speed;
  if(replay.elapsed>=gap)replayStep();
}
$('replay-start').onclick=()=>{
  if(compactMode||replay||busy)return;
  const rows=current().filter(filterMatches).map(e=>JSON.parse(JSON.stringify(e))).sort((a,b)=>Date.parse(a.occurred_at)-Date.parse(b.occurred_at));
  if(!rows.length){$('replay-status').textContent='当前筛选没有可回放事件。';return;}
  replay={rows,index:0,playing:false,speed:Number($('replay-speed').value)||1,elapsed:0,lastTick:Date.now()};
  window.guardianVizClear?.();selected=rows[0].event_id;replayStatus();render();details(rows[0]);replayPulse(rows[0]);
};
$('replay-play').onclick=()=>{if(!replay)return;replay.playing=!replay.playing;replay.lastTick=Date.now();replayStatus();};
$('replay-step').onclick=()=>{if(replay){replay.playing=false;replayStep();}};
$('replay-speed').onchange=()=>{if(replay)replay.speed=[.5,1,2,4].includes(Number($('replay-speed').value))?Number($('replay-speed').value):1;};
$('replay-exit').onclick=()=>{replay=null;selected=null;window.guardianVizClear?.();replayStatus();render();};
setInterval(()=>replayTick(),100);

function renderStorage(storage){
  const failed=storage&&storage.status!=='ready';
  $('storage-status').hidden=!failed;
  if(!failed){$('storage-status').textContent='';return;}
  const message=storage.status==='restart_required'?'数据库回滚失败，服务需要重启；当前不能确认检查与记录。':'本地存储写入失败；失败请求未返回有效决定，请检查磁盘空间或权限。后续写入成功后解除提示。';
  $('storage-status').textContent=message;
  $('connection').textContent='本地存储异常';$('overlay-health').textContent='存储异常';$('overlay-health').title=message;
  $('monitor-status').textContent=message;
}

function renderInvestigation(event){
  const host=$('investigation-controls');host.replaceChildren();
  if(replay||event.is_demo){investigationSnapshot=null;investigationRequest++;host.append(node('p','note','仅支持真实事件的只读调查；请退出历史回放后使用。'));return;}
  host.append(node('p','note','最多读取同一客户端、同一会话中截至本动作的 15 分钟内 8 条脱敏记录。不会执行工具、调用模型或改变审批。'));
  const button=node('button','btn','查看相关动作证据');
  button.onclick=async()=>{
    const request=++investigationRequest;button.disabled=true;
    try{
      const snapshot=await api('/api/investigations/context',{event_id:event.event_id});
      if(request!==investigationRequest||selected!==event.event_id||replay)return;
      investigationSnapshot=snapshot;renderInvestigation(event);
    }catch(error){if(request===investigationRequest&&selected===event.event_id){button.disabled=false;host.append(node('p','note','证据读取失败：'+error.message));}}
  };
  host.append(button);
  const snapshot=investigationSnapshot;
  if(!snapshot||snapshot.anchor_event_id!==event.event_id)return;
  host.append(node('p','note','只读快照 · '+new Date(snapshot.captured_at).toLocaleTimeString()+' · '+snapshot.events.length+' 条。仅含仍保留的历史；先后顺序不证明因果，未提供用户任务授权。'));
  const gaps={context_budget:'达到条数或长度上限，部分相关记录未展示',missing_receipt:'部分动作没有执行回执',output_truncated:'部分返回扫描被截断',output_unavailable:'部分动作没有可用的返回扫描'};
  for(const gap of snapshot.gaps||[])host.append(node('p','note',gaps[gap]||'证据范围不完整'));
  for(const item of snapshot.events){
    const card=node('div','evi','');
    card.append(node('div','src',new Date(item.occurred_at).toLocaleTimeString()+' · '+item.tool_name+(item.event_id===event.event_id?' · 当前动作':'')),
      node('div','body',JSON.stringify(item.action_preview||{})),
      node('p','note','执行前决定：'+({pass:'未命中规则',warn:'告警',review:'请求确认',deny:'拒绝'}[item.verdict]||'未知')+' · 回执：'+({succeeded:'客户端报告成功',failed:'客户端报告失败',blocked:'客户端报告阻止',tool_returned:'工具已返回，业务结果未核验'}[item.execution_state]||'尚无回执')));
    if(item.output_scan?.findings?.length)card.append(node('p','note','返回文本含指令覆盖信号；引用也可能命中，不代表已证实攻击。'));
    if(item.findings?.length)card.append(node('p','note','命中：'+item.findings.join('、')));
    host.append(card);
  }
}

$('review-scope').onchange=()=>{const event=events.find(e=>e.event_id===selected);if(event)renderModelReview(event);};

function applyPrivacy(enabled){
  if(enabled)clearReviewTask();
  const changed=privacyMode!==enabled;privacyMode=enabled;
  document.body.classList.remove('privacy-pending');document.body.classList.toggle('privacy-mode',enabled);
  $('privacy-toggle').textContent=enabled?'录屏隐私 · 已隐藏':'录屏隐私';
  $('overlay-privacy').title=enabled?'录屏隐私已开启，点击退出':'开启录屏隐私';
  $('overlay-privacy').setAttribute('aria-pressed',String(enabled));
  $('privacy-status').hidden=!enabled;
  $('privacy-status').textContent='录屏隐私已开启：详情、会话标识和配置线索已隐藏；审批、来源跳转和导出暂停。确认其他守卫窗口同步显示已隐藏后再录屏，其他应用不受保护。';
  if(changed){
    if(enabled){discoveryGeneration++;$('discovery-results').replaceChildren();$('scan-agents').disabled=onboardingApplying;}
    sessionSnapshot='';snapshot='';investigationSnapshot=null;investigationRequest++;
    if(enabled){if(historyExportUrl){URL.revokeObjectURL(historyExportUrl);historyExportUrl=null;}$('session-filter').blur?.();$('monitor-status').textContent='录屏隐私已开启 · 动作详情已隐藏';$('history-output').textContent='';$('history-controls').replaceChildren();$('source-controls').replaceChildren();}
    if(latestOverview)renderSessions(latestOverview.sessions||[]);
    render();renderDesktopRisk();const event=events.find(e=>e.event_id===selected);if(event)details(event);
  }
}
async function togglePrivacy(){
  const enabled=!privacyMode;
  $('privacy-toggle').disabled=true;$('overlay-privacy').disabled=true;
  if(enabled){privacyLocalLock=true;applyPrivacy(true);}
  try{
    const result=await api('/api/presentation',{privacy_mode:enabled});
    if(typeof result.privacy_mode!=='boolean')throw Error('隐私设置未确认');
    privacyLocalLock=false;applyPrivacy(result.privacy_mode);
  }catch(error){
    if(enabled||privacyMode){privacyLocalLock=true;applyPrivacy(true);}
    $('privacy-status').hidden=false;$('privacy-status').textContent='隐私设置未同步；本窗口继续隐藏。请核对其他窗口后再录屏，恢复连接后重试。';
  }finally{$('privacy-toggle').disabled=false;$('overlay-privacy').disabled=false;}
}
$('privacy-toggle').onclick=togglePrivacy;$('overlay-privacy').onclick=togglePrivacy;
