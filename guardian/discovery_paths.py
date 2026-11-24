"""Bounded install-directory discovery; no subprocesses, scripts or config reads."""
import os
from itertools import islice
from pathlib import Path


def install_directories(home, env):
    warnings=[]
    def root(key, fallback):
        value=env.get(key)
        if not value:return fallback
        candidate=Path(value)
        if not candidate.is_absolute():
            warnings.append(key+' 为相对路径，未使用')
            return fallback
        return candidate
    roaming=root('APPDATA',home/'AppData/Roaming')
    local=root('LOCALAPPDATA',home/'AppData/Local')
    dirs=[('npm',roaming/'npm'),('npm',home/'AppData/Roaming/npm'),
          ('user-bin',home/'.local/bin'),('pnpm',root('PNPM_HOME',local/'pnpm')),
          ('pnpm',home/'.local/share/pnpm'),('pnpm',home/'Library/pnpm'),
          ('bun',root('BUN_INSTALL',home/'.bun')/'bin'),
          ('volta',root('VOLTA_HOME',home/'.volta')/'bin'),
          ('asdf',home/'.asdf/shims'),('mise',home/'.local/share/mise/shims'),
          ('yarn',local/'Yarn/bin'),('yarn',home/'.yarn/bin')]
    # Single-level, capped enumeration. Do not walk package caches or projects.
    versions=[('nvm',home/'.nvm/versions/node',True),
              ('nvm',root('NVM_HOME',roaming/'nvm'),False)]
    for source,parent,bin_child in versions:
        try:
            if not parent.is_dir():continue
            with os.scandir(parent) as entries:
                children=list(islice(entries,33))
            if len(children)>32:warnings.append(source+' 版本目录超过扫描上限')
            for entry in sorted(children[:32],key=lambda entry:entry.name):
                if entry.name.startswith('v') and entry.is_dir(follow_symlinks=False):
                    dirs.append((source,Path(entry.path)/'bin' if bin_child else Path(entry.path)))
        except (OSError,ValueError):warnings.append(source+' 版本目录不可读取')
    return list(dict.fromkeys(dirs)),warnings,local
