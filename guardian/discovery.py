"""Bounded read-only discovery. Never run a discovered executable or read chat history."""
import os
from pathlib import Path
import shutil
from .client_catalog import CLIENTS
from .adapter_registry import available, target
from .discovery_paths import install_directories
from .adapter_contracts import capabilities, native_adapter
from .installation_identity import configuration_scope, identity


def scan(home=None, environ=None, which=None):
    home=Path(home) if home else Path.home()
    env=os.environ if environ is None else environ
    resolve=(lambda command:shutil.which(command,path=env.get('PATH',env.get('Path','')))) if which is None else which
    directories,scan_warnings,local=install_directories(home,env)
    rows=[]
    for spec in CLIENTS:
        client,name,config,coverage=spec.id,spec.name,spec.config,spec.coverage
        candidates={};limited=bool(scan_warnings)
        for command in (spec.command,*spec.aliases):
            try:entry=resolve(command)
            except (OSError,ValueError):entry=None;limited=True
            if entry:candidates.setdefault(Path(entry),('PATH',command))
            for source,directory in directories:
                for suffix in ('.cmd','.exe','.bat','.ps1',''):
                    candidates.setdefault(directory/(command+suffix),(source,command))
        if client=='ollama':candidates.setdefault(local/'Programs/Ollama/ollama.exe',('desktop-install','ollama'))
        configs=[home/config] if config else []
        scopes=[];target_error=False
        if available(spec):
            try:
                destination=target(client,home,env)
                scopes=[configuration_scope(client,destination)]
                configs=[destination]
                if client=='codex':configs=[destination.with_name('config.toml'),destination]
                if client=='pi':configs=[destination.parent.parent/'settings.json',destination]
                if client=='opencode':
                    root=destination.parent.parent
                    configs=[root/'opencode.json',root/'opencode.jsonc',destination]
            except ValueError:target_error=True;limited=True;configs=[]
        def present(path,directory=False):
            nonlocal limited
            try:return path.is_dir() if directory else path.is_file()
            except (OSError,ValueError):limited=True;return False
        evidence=[dict(path=str(p),source=source,command=command,candidate_id=identity(client,p,kind='executable')) for p,(source,command) in candidates.items() if present(p)]
        found=[item['path'] for item in evidence]
        hints=[str(p) for p in configs if present(p,client=='ollama')]
        rows.append(dict(id=client,name=name,kind=spec.kind,
            integration_available=available(spec) and not target_error,adapter=spec.adapter or None,discovery_evidence=evidence,
            configuration_scopes=scopes,capabilities=capabilities(native_adapter(client)),
            configuration_source=spec.config_root_env if spec.config_root_env and env.get(spec.config_root_env) else 'default',
            integration_state='config_error' if target_error else 'adapter_available' if available(spec) else 'model_only' if spec.kind=='model' else 'not_implemented',
            detected=bool(found),paths=found,config_present=bool(hints),config_paths=hints,scan_limited=limited,
            state='found' if found else 'config_only' if hints else 'unreadable' if limited else 'not_found',
            coverage=coverage,native_connected=False,
            note='只发现安装线索，未执行客户端、未验证版本和接入。'+(' 部分候选位置不可读取，结果可能不完整。' if limited else '')))
    rows.append(dict(id='codex-desktop',name='Codex 桌面端',state='manual_verification',
        integration_available=False,integration_state='manual_verification',
        detected=False,paths=[],native_connected=False,coverage='需独立验证桌面运行时；CLI 检测结果不代表桌面接入。'))
    return dict(read_only=True,external_config_writes=False,clients=rows,scan_warnings=scan_warnings,
                message='统一扫描 PATH、常见包管理器和有界版本目录，不保证发现所有安装方式。发现入口不等于接入；仅已有适配器的客户端可勾选。不运行客户端、不修改配置、不读取对话或密钥。')
