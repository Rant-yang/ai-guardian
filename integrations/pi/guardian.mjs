import {readFile} from 'node:fs/promises';
import {request} from 'node:http';
import {dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolvePort} from '../common/endpoint.mjs';

const registered=new WeakSet();
const identity=value=>typeof value==='string'&&value.length>0&&value.length<=200;
function post(port,token,path,body){
  const encoded=JSON.stringify(body);
  if(Buffer.byteLength(encoded)>262144)return Promise.reject(Error('Request too large'));
  return new Promise((resolve,reject)=>{
    const req=request({hostname:'127.0.0.1',port,path,method:'POST',headers:{
      Authorization:'Bearer '+token,'Content-Type':'application/json','Content-Length':Buffer.byteLength(encoded)}},res=>{
      const chunks=[];let size=0;
      res.on('data',chunk=>{size+=chunk.length;if(size>65536)req.destroy(Error('Response too large'));else chunks.push(chunk);});
      res.on('error',reject);
      res.on('end',()=>{try{if(res.statusCode!==200)throw Error('Guardian unavailable');resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));}catch(error){reject(error);}});
    });
    const timer=setTimeout(()=>req.destroy(Error('Guardian timeout')),3000);timer.unref?.();
    req.on('close',()=>clearTimeout(timer));req.on('error',reject);req.end(encoded);
  });
}

export default function guardian(pi,options={}){
  if(registered.has(pi))return;
  registered.add(pi);
  const tokenPath=options.tokenPath||process.env.GUARDIAN_TOKEN_FILE||fileURLToPath(new URL('../../.local/access-token',import.meta.url));
  const portOverride=options.port??process.env.GUARDIAN_PORT;
  const pending=new Map();
  let mode=process.env.GUARDIAN_MODE||'observe';
  if(!['observe','protect'].includes(mode))mode='protect';
  const warn=ctx=>{try{if(ctx.hasUI)ctx.ui.notify('Guardian unavailable: observation or receipt incomplete.','warning');}catch{}};
  const send=async(path,body)=>post(await resolvePort(tokenPath,portOverride),(await readFile(tokenPath,'utf8')).trim(),path,body);
  const receipt=async(session,call,status,ctx)=>{try{await send('/api/receipt',{adapter:'pi-extension',session_id:session,call_id:call,status});}catch{warn(ctx);}};
  const readMode=async()=>{
    try{
      const value=JSON.parse(await readFile(join(dirname(tokenPath),'runtime-modes.json'),'utf8'))['pi-extension'];
      if(value!==undefined){if(!['observe','protect'].includes(value))throw Error('Invalid mode');mode=value;}
    }catch(error){if(error.code!=='ENOENT'){mode='protect';throw error;}}
  };
  pi.on('tool_call',async(event,ctx)=>{
    let session,decision,original,key,call;
    try{
      await readMode();session=ctx.sessionManager.getSessionId();call=event.toolCallId;
      if(!identity(session)||!identity(event.toolCallId)||!identity(event.toolName)||!event.input||typeof event.input!=='object'||Array.isArray(event.input))throw Error('Invalid identity');
      original=JSON.stringify([event.toolName,event.toolCallId,event.input,ctx.cwd]);key=JSON.stringify([session,event.toolCallId]);
      decision=await send('/api/pi/check',{mode,source_pid:process.pid,resume_available:!!ctx.sessionManager.getSessionFile?.(),payload:{session_id:session,tool_use_id:event.toolCallId,
        tool_name:event.toolName,tool_input:event.input,cwd:ctx.cwd}});
      if(!decision||!['observe','protect'].includes(decision.mode)||!['pass','warn','review','deny'].includes(decision.verdict)||
         !Array.isArray(decision.findings)||decision.findings.length>64||decision.findings.some(v=>typeof v!=='string'||!/^[a-z0-9_:-]{1,120}$/.test(v)))throw Error('Invalid decision');
      mode=decision.mode;
    }catch{
      if(mode==='protect')return {block:true,reason:'Guardian unavailable: tool stopped before execution.'};
      warn(ctx);return;
    }
    let blocked=decision.verdict==='deny';
    let deadline=Infinity;
    const unchanged=()=>!ctx.signal?.aborted&&JSON.stringify([event.toolName,event.toolCallId,event.input,ctx.cwd])===original&&ctx.sessionManager.getSessionId()===session;
    if(mode==='protect'&&decision.verdict==='review'){
      blocked=true;
      if(ctx.hasUI&&typeof ctx.ui?.confirm==='function'){
        deadline=Math.min(Date.now()+300000,Number.isFinite(decision.approval_expires_at)?decision.approval_expires_at*1000:Infinity);
        try{blocked=(await ctx.ui.confirm('Guardian: allow this action once?',
          JSON.stringify(decision.action_preview||{tool:event.toolName,reasons:decision.findings}).slice(0,4000),{timeout:Math.max(0,deadline-Date.now())}))!==true||Date.now()>=deadline;}catch{}
      }
    }
    if(mode==='protect'&&decision.verdict==='review'){
      blocked=blocked||!unchanged();
      try{
        if(!identity(decision.event_id)||typeof decision.review_binding!=='string'||!/^[a-f0-9]{64}$/.test(decision.review_binding))throw Error('Missing binding');
        const outcome=blocked?'not_confirmed':'confirmed';
        const audit=await send('/api/native-confirmation',{adapter:'pi-extension',session_id:session,call_id:call,
          event_id:decision.event_id,binding:decision.review_binding,outcome});
        if(audit?.event_id!==decision.event_id||audit?.native_confirmation?.outcome!==outcome)throw Error('Unrecorded confirmation');
      }catch{blocked=true;warn(ctx);}
    }
    if(mode==='protect'&&(blocked||Date.now()>=deadline||!unchanged())){
      await receipt(session,call,'blocked',ctx);
      return {block:true,reason:decision.verdict==='review'?'Guardian: action not confirmed or context changed. Use an interactive Pi session to review and retry.':'Guardian denied this action: '+decision.findings.join(', ')};
    }
    if(pending.size>=1024)pending.delete(pending.keys().next().value);
    pending.set(key,session);
  });
  pi.on('tool_result',async(event,ctx)=>{
    // Result bodies and session transcripts are never sent to Guardian.
    let session;try{session=ctx.sessionManager.getSessionId();}catch{return;}
    const key=JSON.stringify([session,event.toolCallId]);if(!pending.has(key))return;
    pending.delete(key);
    await receipt(session,event.toolCallId,event.isError===true?'failed':event.isError===false?'succeeded':'tool_returned',ctx);
  });
  pi.on('session_shutdown',()=>{pending.clear();});
}
