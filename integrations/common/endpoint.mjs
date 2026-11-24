import {open} from 'node:fs/promises';
import {dirname,join} from 'node:path';

function port(value){
  if(!Number.isInteger(value)||value<1||value>65535)throw Error('Invalid Guardian port');
  return value;
}

export async function resolvePort(tokenPath,explicit){
  if(explicit!==undefined)return port(Number(explicit));
  let file;
  try{file=await open(join(dirname(tokenPath),'service-endpoint.json'),'r');}
  catch(error){if(error.code==='ENOENT')return 8765;throw error;}
  let raw;
  try{const buffer=Buffer.alloc(4097);const {bytesRead}=await file.read(buffer,0,4097,0);if(bytesRead>4096)throw Error('Invalid endpoint descriptor');raw=buffer.subarray(0,bytesRead);}
  finally{await file.close();}
  const data=JSON.parse(raw.toString('utf8'));
  if(!data||data.version!==1||data.host!=='127.0.0.1')throw Error('Invalid endpoint descriptor');
  return port(data.port);
}
