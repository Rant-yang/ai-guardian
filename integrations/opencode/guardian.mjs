import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {createHash, randomUUID} from 'node:crypto';
import {join, dirname} from 'node:path';
import {resolvePort} from './endpoint.mjs';

const instances = new Map();
function scanOutput(value){
  const result={version:'output-1',status:value==null?'missing':'unsupported',characters_scanned:0,truncated:false,findings:[]};
  if(typeof value!=='string')return result;
  const text=value.slice(0,32768);
  result.status='scanned';result.characters_scanned=text.length;result.truncated=text.length<value.length;
  if(/ignore\s+(?:(?:all|previous|prior)\s+){0,2}instructions|忽略.{0,8}(?:指令|规则)|system\s+prompt/i.test(text))result.findings=['instruction_override'];
  return result;
}

// Project-scoped plugin. No cloud requests and no additional tool permissions.
export default async function GuardianPlugin({client, directory} = {}, registration = {}) {
  let mode = process.env.GUARDIAN_MODE || 'observe';
  if (!['observe','protect'].includes(mode)) throw Error('Guardian: invalid mode');
  const explicitPort = process.env.GUARDIAN_PORT;
  const tokenPath = process.env.GUARDIAN_TOKEN_FILE || fileURLToPath(new URL('../../.local/access-token', import.meta.url));
  const readMode = async () => {
    try {
      const value=JSON.parse(await readFile(join(dirname(tokenPath),'runtime-modes.json'),'utf8'))['opencode-plugin'];
      if(value!==undefined){if(!['observe','protect'].includes(value))throw Error('invalid mode');mode=value;}
    } catch(error) {if(error.code!=='ENOENT'){mode='protect';throw error;}}
  };
  const receipt = async (input,status,outputScan) => {
    try {
      const token=(await readFile(tokenPath,'utf8')).trim();
      const port=await resolvePort(tokenPath,explicitPort);
      await fetch(`http://127.0.0.1:${port}/api/receipt`,{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},
        body:JSON.stringify({adapter:'opencode-plugin',session_id:input.sessionID,call_id:input.callID,status,...(outputScan?{output_scan:outputScan}:{})}),signal:AbortSignal.timeout(2000)});
    } catch {}
  };
  const key = JSON.stringify([directory, mode, explicitPort, tokenPath]);
  // Global and project entrypoints import this same module. Register once per project.
  if (directory && instances.has(key)) return {};
  if (directory) instances.set(key, true);
  const instanceId = randomUUID();
  const canNavigate = typeof client?.tui?.publish==='function';
  const projectId = createHash('sha256').update(directory || 'unknown').digest('hex').slice(0,16);
  let beating = false;
  const heartbeat = async () => {
    if (beating) return;
    beating = true;
    try {
      await readMode();
      const token = (await readFile(tokenPath,'utf8')).trim();
      const port=await resolvePort(tokenPath,explicitPort);
      const response=await fetch(`http://127.0.0.1:${port}/api/opencode/heartbeat`, {
        method:'POST', headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},
        body:JSON.stringify({instance_id:instanceId,adapter:'opencode-plugin',adapter_revision:'scope-4',mode,project_id:projectId,
          installation_id:registration.installation_id,loader_revision:registration.loader_revision,navigation:canNavigate?'session_select':undefined}),
        signal:AbortSignal.timeout(2000),
      });
      if(response.ok){
        const instruction=(await response.json()).navigation;
        if(canNavigate&&instruction?.kind==='select_session'&&/^[0-9a-f-]{36}$/.test(instruction.request_id||'')&&/^ses_[A-Za-z0-9]{8,128}$/.test(instruction.session_id||'')){
          let status='failed';
          try{
            // Navigation only: never submit prompts, commands, permissions or session resumes.
            const result=await client.tui.publish({body:{type:'tui.session.select',properties:{sessionID:instruction.session_id}},
              query:{directory},signal:AbortSignal.timeout(1500)});
            if(result?.data===true&&!result.error)status='dispatched';
          }catch{}
          await fetch(`http://127.0.0.1:${port}/api/opencode/navigation-result`,{method:'POST',
            headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},
            body:JSON.stringify({instance_id:instanceId,request_id:instruction.request_id,status}),signal:AbortSignal.timeout(2000)});
        }
      }
    } catch {} finally {beating=false;}
  };
  // Presence is advisory and never blocks tool execution. Re-register after server restart.
  if (directory) {void heartbeat(); const timer=setInterval(heartbeat,canNavigate?2000:15000); timer.unref?.();}
  const log = async message => {
    try {await client?.app?.log({body:{service:'guardian',level:'warn',message}});} catch {}
  };
  return {
    'tool.execute.before': async (input, output) => {
      let event;
      try {
        await readMode();
        if (!input.sessionID || !input.callID || !output.args) throw Error('Missing tool identity');
        const token = (await readFile(tokenPath,'utf8')).trim();
        const port=await resolvePort(tokenPath,explicitPort);
        const tool = {bash:'Bash',read:'Read',write:'Write',edit:'Edit'}[input.tool] || input.tool;
        const response = await fetch(`http://127.0.0.1:${port}/api/opencode/check`, {
          method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},
          body:JSON.stringify({mode,instance_id:instanceId,source_pid:process.pid,payload:{session_id:input.sessionID,tool_use_id:input.callID,tool_name:tool,tool_input:output.args,...(typeof directory==='string'&&directory?{cwd:directory}:{})}}),
          signal:AbortSignal.timeout(3000),
        });
        if (!response.ok) throw Error('Guardian check unavailable');
        event = await response.json();
        if (!event || !['observe','protect'].includes(event.mode) || !['pass','warn','review','deny'].includes(event.verdict)
            || !Array.isArray(event.findings) || event.findings.length>64
            || event.findings.some(value=>typeof value!=='string'||!/^[a-z0-9_:-]{1,120}$/.test(value))) throw Error('Invalid decision');
        // A malformed response must never overwrite the last valid local mode.
        mode=event.mode;
      } catch {
        if (mode==='protect') throw Error('Guardian unavailable: tool stopped before execution.');
        await log('Guardian unavailable: observation incomplete.');
        return;
      }
      if (mode==='protect' && ['deny','review'].includes(event.verdict)) {
        await receipt(input,'blocked');
        // No automatic approval or replay: review is conservatively stopped in this adapter.
        throw Error('Guardian stopped this tool: '+event.findings.join(', ')+(event.verdict==='review'?'. Review in Guardian; after one-time authorization, explicitly retry the identical action in this session within 5 minutes.':'. This action is denied.'));
      }
      if (event.findings.length) await log('Guardian warning: '+event.findings.join(', '));
    },
    'tool.execute.after': async (input,output) => { await receipt(input,'tool_returned',scanOutput(output?.output)); },
  };
}
