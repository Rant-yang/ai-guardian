"""Shared conservative checks for client configuration files, including CLI use."""
from pathlib import Path
import stat


def check_path(path):
    path=Path(path)
    for entry in (path,*path.parents):
        try:info=entry.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
            raise ValueError('配置路径包含链接，请手动核对')
    if path.exists() and path.stat().st_size>2*1024*1024:
        raise ValueError('配置文件过大')
    return path
