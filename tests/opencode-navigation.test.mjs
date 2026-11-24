import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import GuardianPlugin from '../integrations/opencode/guardian.mjs';

test('navigation publishes only fixed session selection and acknowledges interface result',async()=>{
  const root=await mkdtemp(join(tmpdir(),'guardian-nav-'));
  const oldFetch=globalThis.fetch,oldInterval=globalThis.setInterval,oldToken=process.env.GUARDIAN_TOKEN_FILE;
  let pulse;const requests=[],published=[];
  try{
    process.env.GUARDIAN_TOKEN_FILE=join(root,'token');await writeFile(join(root,'token'),'fixture');
    globalThis.setInterval=fn=>{pulse=fn;return {unref(){}};};
    let instruction={request_id:'12345678-1234-1234-1234-123456789012',kind:'select_session',session_id:'ses_fixture1234'};
    globalThis.fetch=async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return new Response(JSON.stringify(url.endsWith('/heartbeat')?{navigation:instruction}:url.endsWith('/check')?{mode:'observe',verdict:'pass',findings:[]}:{accepted:true}));};
    const plugin=await GuardianPlugin({directory:root,client:{tui:{publish:async options=>{published.push(options);return {data:true};}}}},
      {installation_id:'a'.repeat(32),loader_revision:'scope-1'});
    for(let n=0;n<100&&!requests.some(r=>r.url.endsWith('/navigation-result'));n++)await new Promise(resolve=>setTimeout(resolve,10));
    assert.deepEqual(published[0].body,{type:'tui.session.select',properties:{sessionID:'ses_fixture1234'}});
    assert.equal(requests.find(r=>r.url.endsWith('/heartbeat')).body.adapter_revision,'scope-4');
    assert.equal(requests.find(r=>r.url.endsWith('/heartbeat')).body.installation_id,'a'.repeat(32));
    assert.equal(requests.find(r=>r.url.endsWith('/heartbeat')).body.loader_revision,'scope-1');
    assert.equal(requests.find(r=>r.url.endsWith('/navigation-result')).body.status,'dispatched');
    assert.ok(requests.every(r=>r.url.endsWith('/heartbeat')||r.url.endsWith('/navigation-result')));
    instruction={...instruction,session_id:'https://example.invalid'};await pulse();assert.equal(published.length,1);
    await plugin['tool.execute.before']({tool:'read',sessionID:'ses_fixture1234',callID:'context-test'},{args:{filePath:'.env'}});
    const check=requests.find(r=>r.url.endsWith('/check'));
    assert.equal(check.body.payload.cwd,root);
    assert.equal(check.body.source_pid,process.pid);
    assert.deepEqual(check.body.payload.tool_input,{filePath:'.env'});
  }finally{
    globalThis.fetch=oldFetch;globalThis.setInterval=oldInterval;
    if(oldToken===undefined)delete process.env.GUARDIAN_TOKEN_FILE;else process.env.GUARDIAN_TOKEN_FILE=oldToken;
    await rm(root,{recursive:true});
  }
});
