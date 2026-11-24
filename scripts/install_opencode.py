"""Install only our dedicated global plugin file. Never rewrite user configuration."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from guardian.config_files import check_path
from guardian.installation_identity import identity
NAME = 'guardian-agent-security.js'


def plugin_text(config=None):
    uri = (ROOT/'integrations/opencode/guardian.mjs').as_uri()
    registration=(', '+json.dumps({'installation_id':identity('opencode',Path(config)/'plugins'/NAME),'loader_revision':'scope-1'})) if config is not None else ''
    return ('// Managed by Guardian: global observation adapter v1\n'
            'export default async function GuardianGlobal(context) {\n'
            '  try {\n'
            f'    const module = await import({json.dumps(uri)});\n'
            f'    return await module.default(context{registration});\n'
            '  } catch (error) {\n'
            '    if (process.env.GUARDIAN_MODE === "protect") throw error;\n'
            '    console.warn("Guardian adapter unavailable; observation is offline.");\n'
            '    return {};\n'
            '  }\n}\n')


def manage(config, action):
    if action not in ('status','install','uninstall'):raise ValueError('Unsupported operation')
    target = config/'plugins'/NAME
    check_path(target)
    expected = plugin_text(config)
    if target.is_symlink():
        raise ValueError('Refusing to modify a symlink')
    before=target.read_bytes() if target.exists() else None
    existing=before.decode('utf-8').replace('\r\n','\n') if before is not None else None
    legacy=existing==plugin_text()
    if action == 'status':
        return {'path':str(target),'installed':existing == expected or legacy,'partial':legacy,
                'conflict':existing is not None and existing != expected and not legacy}
    if existing is not None and existing != expected and not legacy:
        raise ValueError('Plugin file differs from this installer; refusing to overwrite or remove it')
    if action == 'uninstall':
        if existing is not None:
            check_path(target)
            if target.read_text(encoding='utf-8')!=existing:raise ValueError('Plugin changed; not removed')
            target.unlink()
        return {'removed':str(target),'restart_required':True}
    if legacy:
        from guardian.integrations import atomic_change
        atomic_change(target,before,expected.encode('utf-8'))
    elif existing is None:
        target.parent.mkdir(parents=True, exist_ok=True)
        check_path(target)
        # Exclusive create prevents overwriting a file created after the check above.
        with target.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(expected)
    return {'installed':str(target),'sha256':hashlib.sha256(expected.encode()).hexdigest(),
            'mode':'observe (unless GUARDIAN_MODE overrides it)','restart_required':True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=['install','uninstall','status'])
    parser.add_argument('--config-dir',type=Path,default=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'opencode')
    args = parser.parse_args()
    print(json.dumps(manage(args.config_dir.resolve(),args.action),ensure_ascii=False,indent=2))
