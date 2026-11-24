"""Own one Pi extension loader; never alter model/auth/settings files."""
import json
from pathlib import Path
from guardian.config_files import check_path

ROOT=Path(__file__).resolve().parents[1]


def extension_text():
    module=(ROOT/'integrations/pi/guardian.mjs').as_uri()
    token=str(ROOT/'.local/access-token')
    return ('// Guardian managed Pi extension v1\n'
            'import {readFile} from "node:fs/promises";\n'
            'import {dirname,join} from "node:path";\n'
            'export default async function(pi) {\n'
            f'  try {{ const module=await import({json.dumps(module)}); return module.default(pi); }}\n'
            '  catch { pi.on("tool_call",async()=>{\n'
            '    let mode=process.env.GUARDIAN_MODE||"observe";\n'
            f'    try {{ const path=join(dirname(process.env.GUARDIAN_TOKEN_FILE||{json.dumps(token)}),"runtime-modes.json"); const value=JSON.parse(await readFile(path,"utf8"))["pi-extension"]; if(value!==undefined)mode=value; }}\n'
            '    catch(error) { if(error.code!=="ENOENT")mode="protect"; }\n'
            '    if(mode!=="observe")return {block:true,reason:"Guardian extension unavailable; action stopped."};\n'
            '    console.error("Guardian extension unavailable; observation incomplete.");\n'
            '  }); }\n}\n')


def manage(target,action):
    if action not in ('status','install','uninstall'):raise ValueError('Unsupported operation')
    target=Path(target);check_path(target)
    before=target.read_bytes() if target.exists() else None
    expected=extension_text().encode('utf-8')
    installed=before==expected
    conflict=before is not None and not installed
    if action=='status':return dict(installed=installed,conflict=conflict)
    if conflict:raise ValueError('Pi loader changed; refusing to overwrite or remove')
    if action=='install' and before is None:
        target.parent.mkdir(parents=True,exist_ok=True);check_path(target)
        with target.open('xb') as stream:stream.write(expected)
    elif action=='uninstall' and installed:
        check_path(target)
        if target.read_bytes()!=before:raise ValueError('Pi loader changed during removal')
        target.unlink()
    return dict(installed=action=='install',restart_required=True)
