import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve,sep} from 'node:path';
import guardian from '../integrations/pi/guardian.mjs';

async function fixture(t){
  const root=await mkdtemp(join(tmpdir(),'guardian-pi-'));
  const calls=[],handlers={},warnings=[];
  const state={reply:{mode:'protect',verdict:'pass',findings:[]},session:'fixture-session',confirmed:true};
  const server=createServer(async(req,res)=>{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);
    assert.equal(req.headers.authorization,'Bearer fixture-token');
    calls.push({path:req.url,body:JSON.parse(Buffer.concat(chunks))});
    const body=calls.at(-1).body;
    const reply=req.url==='/api/receipt'?{}:req.url==='/api/native-confirmation'?
      {event_id:body.event_id,native_confirmation:{outcome:body.outcome}}:
      {event_id:'fixture-event',review_binding:'a'.repeat(64),...state.reply};
    if(req.url==='/api/native-confirmation')state.onAudit?.();
    res.writeHead(req.url==='/api/native-confirmation'&&state.auditFails?503:200,{'Content-Type':'application/json'});res.end(JSON.stringify(reply));
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const tokenPath=join(root,'token');await writeFile(tokenPath,'fixture-token');
  const mode=async value=>writeFile(join(root,'runtime-modes.json'),JSON.stringify({'pi-extension':value}));
  await mode('protect');
  const pi={on:(name,fn)=>{assert.equal(handlers[name],undefined);handlers[name]=fn;}};
  const ctx={cwd:root,hasUI:true,sessionManager:{getSessionId:()=>state.session},ui:{confirm:async()=>state.confirmed,notify:value=>warnings.push(value)}};
  guardian(pi,{tokenPath,port:server.address().port});guardian(pi,{tokenPath,port:server.address().port});
  t.after(async()=>{
    await new Promise(r=>server.close(r));
    assert.ok(resolve(root).startsWith(resolve(tmpdir())+sep));await rm(root,{recursive:true});
  });
  return {handlers,ctx,calls,state,mode,warnings};
}
const action=(id='one')=>({toolName:'read',toolCallId:id,input:{path:'fixture.txt'}});

test('Pi passes native tool identity, reports success/failure and never transmits result text',async t=>{
  const f=await fixture(t),event=action();
  assert.equal(await f.handlers.tool_call(event,f.ctx),undefined);
  assert.deepEqual(f.calls[0].body.payload,{session_id:'fixture-session',tool_use_id:'one',tool_name:'read',tool_input:{path:'fixture.txt'},cwd:f.ctx.cwd});
  assert.equal(f.calls[0].body.source_pid,process.pid);
  assert.equal(f.calls[0].body.resume_available,false);
  assert.equal(await f.handlers.tool_result({...event,isError:false,content:[{text:'PRIVATE_OUTPUT'}]},f.ctx),undefined);
  assert.equal(f.calls.at(-1).body.status,'succeeded');assert.ok(!JSON.stringify(f.calls).includes('PRIVATE_OUTPUT'));
  const before=f.calls.length;await f.handlers.tool_result({...event,isError:false},f.ctx);assert.equal(f.calls.length,before);
  await f.handlers.tool_call(action('two'),f.ctx);await f.handlers.tool_result({...action('two'),isError:true},f.ctx);
  assert.equal(f.calls.at(-1).body.status,'failed');
});
test('Pi reports persistence without sending session file paths',async t=>{
  const f=await fixture(t);f.ctx.sessionManager.getSessionFile=()=>'/PRIVATE_SESSION_FILE.jsonl';
  await f.handlers.tool_call(action(),f.ctx);
  assert.equal(f.calls[0].body.resume_available,true);
  assert.ok(!JSON.stringify(f.calls).includes('PRIVATE_SESSION_FILE'));
});
test('Pi denial blocks, review uses one native confirmation and headless cannot approve',async t=>{
  const f=await fixture(t);f.state.reply={mode:'protect',verdict:'deny',findings:['destructive_command']};
  assert.equal((await f.handlers.tool_call(action(),f.ctx)).block,true);
  assert.equal(f.calls.at(-1).body.status,'blocked');
  f.state.reply={mode:'protect',verdict:'review',findings:['outbound_transfer_review']};
  f.state.confirmed=false;assert.equal((await f.handlers.tool_call(action('two'),f.ctx)).block,true);
  f.state.confirmed=true;assert.equal(await f.handlers.tool_call(action('three'),f.ctx),undefined);
  assert.equal(f.calls.at(-1).path,'/api/native-confirmation');
  assert.equal(f.calls.at(-1).body.outcome,'confirmed');
  f.ctx.hasUI=false;assert.equal((await f.handlers.tool_call(action('four'),f.ctx)).block,true);
  f.ctx.hasUI=true;f.state.reply.approval_expires_at=1;
  assert.equal((await f.handlers.tool_call(action('expired'),f.ctx)).block,true);
});
test('Pi approval cannot cover changed parameters or a switched session',async t=>{
  const f=await fixture(t);f.state.reply={mode:'protect',verdict:'review',findings:[]};
  const event=action();f.ctx.ui.confirm=async()=>{event.input.path='different';return true;};
  assert.equal((await f.handlers.tool_call(event,f.ctx)).block,true);
  f.ctx.ui.confirm=async()=>{f.state.session='other-session';return true;};
  assert.equal((await f.handlers.tool_call(action('two'),f.ctx)).block,true);
  assert.equal(f.calls.at(-1).body.session_id,'fixture-session');
});
test('Pi invalid responses cannot downgrade protection; observation remains nonblocking',async t=>{
  const f=await fixture(t);f.state.reply={mode:'observe',verdict:'invalid',findings:[]};
  assert.equal((await f.handlers.tool_call(action(),f.ctx)).block,true);
  await f.mode('observe');assert.equal(await f.handlers.tool_call(action('two'),f.ctx),undefined);
  assert.equal(f.warnings.length,1);
  f.state.reply={mode:'observe',verdict:'warn',findings:['destructive_command']};
  assert.equal(await f.handlers.tool_call(action('three'),f.ctx),undefined);
});
test('Pi requires durable confirmation and rechecks context after its audit response',async t=>{
  const f=await fixture(t);f.state.reply={mode:'protect',verdict:'review',findings:[]};
  f.state.auditFails=true;
  assert.equal((await f.handlers.tool_call(action(),f.ctx)).block,true);
  assert.equal(f.calls.at(-1).body.status,'blocked');
  f.state.auditFails=false;
  const event=action('changed');f.state.onAudit=()=>{event.input.path='changed-after-confirm';};
  assert.equal((await f.handlers.tool_call(event,f.ctx)).block,true);
  assert.equal(f.calls.at(-1).body.status,'blocked');
  const before=f.calls.length;await f.handlers.tool_result({...event,isError:false},f.ctx);
  assert.equal(f.calls.length,before);
});
test('Pi session shutdown drops pending receipts instead of assigning them elsewhere',async t=>{
  const f=await fixture(t);await f.handlers.tool_call(action(),f.ctx);const before=f.calls.length;
  f.handlers.session_shutdown();await f.handlers.tool_result({...action(),isError:false},f.ctx);
  assert.equal(f.calls.length,before);
});
