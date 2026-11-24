"""Backend source snapshot, not a signature or proof of loaded bytecode."""
import hashlib
from pathlib import Path


def source_revision(directory=None):
    directory=Path(directory) if directory is not None else Path(__file__).resolve().parent
    digest=hashlib.sha256()
    files=sorted([*directory.glob('*.py'),directory/'rules.json'],key=lambda p:p.name)
    for path in files:
        if path.is_symlink() or not path.is_file():raise ValueError('Expected regular backend source')
        content=path.read_bytes()
        digest.update(path.name.encode('utf-8')+b'\0'+str(len(content)).encode('ascii')+b'\0'+content)
    return digest.hexdigest()


if __name__=='__main__':print(source_revision())
