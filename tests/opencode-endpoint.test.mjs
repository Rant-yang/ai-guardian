import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {resolvePort} from '../integrations/opencode/endpoint.mjs';
import GuardianPlugin from '../integrations/opencode/guardian.mjs';

test('endpoint refresh, explicit override and invalid descriptor rejection',async()=>{
  const root=await mkdtemp(join(tmpdir(),'guardian-endpoint-'));
  const token=join(root,'token'),path=join(root,'service-endpoint.json');
  try{
    assert.equal(await resolvePort(token),8765);
    for(const port of [18001,18002]){
      await writeFile(path,JSON.stringify({version:1,host:'127.0.0.1',port}));
      assert.equal(await resolvePort(token),port);
      assert.equal(await resolvePort(token,'19000'),19000);
    }
    for(const data of ['{',' '.repeat(4097),JSON.stringify({version:1,host:'example.com',port:80}),JSON.stringify({version:1,host:'127.0.0.1',port:'8765'})]){
      await writeFile(path,data);await assert.rejects(resolvePort(token));
    }
  }finally{await rm(root,{recursive:true});}
});

test('the same loaded plugin refreshes the endpoint for checks and receipts',async()=>{
  const root=await mkdtemp(join(tmpdir(),'guardian-moving-'));
  const previous={token:process.env.GUARDIAN_TOKEN_FILE,port:process.env.GUARDIAN_PORT,mode:process.env.GUARDIAN_MODE,fetch:globalThis.fetch};
  const urls=[];
  try{
    process.env.GUARDIAN_TOKEN_FILE=join(root,'token');delete process.env.GUARDIAN_PORT;process.env.GUARDIAN_MODE='protect';
    await writeFile(join(root,'token'),'fixture');
    globalThis.fetch=async url=>{urls.push(url);return new Response(JSON.stringify({mode:'protect',verdict:'pass',findings:[]}));};
    const plugin=await GuardianPlugin();
    for(const port of [18001,18002]){
      await writeFile(join(root,'service-endpoint.json'),JSON.stringify({version:1,host:'127.0.0.1',port}));
      await plugin['tool.execute.before']({sessionID:'fixture',callID:'one',tool:'read'},{args:{file_path:'fixture'}});
      await plugin['tool.execute.after']({sessionID:'fixture',callID:'one'},{output:'ok'});
      assert.ok(urls.slice(-2).every(url=>url.startsWith(`http://127.0.0.1:${port}/`)));
    }
    await writeFile(join(root,'service-endpoint.json'),'{');
    await assert.rejects(plugin['tool.execute.before']({sessionID:'fixture',callID:'one',tool:'read'},{args:{}}));
    assert.equal(urls.length,4);
  }finally{
    globalThis.fetch=previous.fetch;
    for(const [key,value] of [['GUARDIAN_TOKEN_FILE',previous.token],['GUARDIAN_PORT',previous.port],['GUARDIAN_MODE',previous.mode]]){if(value===undefined)delete process.env[key];else process.env[key]=value;}
    await rm(root,{recursive:true});
  }
});
