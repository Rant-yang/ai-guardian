"""Build a deterministic, explicit-allowlist local preview; never publishes."""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

ROOT=Path(__file__).resolve().parents[1]
MANIFEST='packaging/preview-files.json'
EXTENSIONS={'.py','.json','.js','.mjs','.cjs','.css','.html','.md','.ps1','.vbs','.cmd','.txt'}
FORBIDDEN={'.local','.venv','.git','.codex','.agents','.aws','__pycache__','artifacts','design','组件风格','node_modules'}


def check_local_imports(root, files):
    """Reject omitted local Python dependencies; never import packaged code.

    Only static imports with a source module in this checkout are resolved.
    Dynamic imports, resources and external dependencies still need smoke tests.
    """
    missing=set()
    def require(parts):
        if not parts:return False
        module=Path(*parts)
        for candidate in (module.with_suffix('.py'),module/'__init__.py'):
            if (root/candidate).is_file():
                name=candidate.as_posix()
                if name not in files:missing.add(name)
                for size in range(1,len(parts)):
                    parent=Path(*parts[:size])/'__init__.py'
                    if (root/parent).is_file() and parent.as_posix() not in files:missing.add(parent.as_posix())
                return True
        return False
    for name,content in files.items():
        if not name.endswith('.py'):continue
        directory=list(PurePosixPath(name).parent.parts)
        for node in ast.walk(ast.parse(content,filename=name)):
            if isinstance(node,ast.Import):
                for alias in node.names:require(alias.name.split('.'))
            elif isinstance(node,ast.ImportFrom):
                prefix=directory[:len(directory)-node.level+1] if node.level else []
                module=prefix+(node.module.split('.') if node.module else [])
                found=require(module)
                if not node.level and not found:
                    require(directory+module)  # Direct-script sibling imports.
                for alias in node.names:
                    if alias.name!='*':require(module+[alias.name])
    if missing:raise ValueError('Local imports missing from allowlist: '+', '.join(sorted(missing)))


def relative(name):
    if not isinstance(name,str):raise ValueError('Invalid manifest path')
    path=PurePosixPath(name)
    if name=='.gitignore':return path
    if not isinstance(name,str) or not name or '\\' in name or ':' in name or path.is_absolute() or str(path)!=name:
        raise ValueError('Invalid manifest path')
    if any(part in ('.','..') or part.startswith('.') or part in FORBIDDEN or 'backup' in part.lower() for part in path.parts):
        raise ValueError('Private or unsafe manifest path')
    if path.suffix not in EXTENSIONS:raise ValueError('Unsupported package file type')
    return path


def checked(root,name):
    path=relative(name)
    current=root
    for part in path.parts:
        current=current/part
        info=current.lstat()
        if current.is_symlink() or getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
            raise ValueError('Linked package paths are forbidden')
    if not current.is_file():raise ValueError('Expected file')
    return current


def build(root=ROOT):
    root=Path(root).resolve()
    manifest=checked(root,MANIFEST)
    names=json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(names,list) or not names or len(names)>300 or any(not isinstance(n,str) for n in names):
        raise ValueError('Invalid file allowlist')
    if len({name.casefold() for name in names})!=len(names):raise ValueError('Duplicate package path')
    if MANIFEST not in names:raise ValueError('Include the source allowlist')
    files={};total=0
    for name in sorted(names):
        source=checked(root,name)
        if source.stat().st_size>2_000_000:raise ValueError('Package file exceeds limit')
        content=source.read_bytes();total+=len(content)
        if total>20_000_000:raise ValueError('Package exceeds limit')
        files[name]=content
    check_local_imports(root,files)
    inventory={'schema':'guardian-local-preview-v1','public_release_ready':False,
               'scope':'local installation rehearsal; no runtime state or dependencies bundled',
               'files':[{'path':name,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()} for name,content in files.items()]}
    files['BUNDLE_MANIFEST.json']=(json.dumps(inventory,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,content in sorted(files.items()):
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.create_system=3;info.external_attr=0o100644<<16
            archive.writestr(info,content)
    return stream.getvalue(),inventory


def verify(content):
    """Integrity/allowlist validation, not a signature or proof of authorship."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names=archive.namelist()
        if len(names)>301 or len(set(n.casefold() for n in names))!=len(names):raise ValueError('Duplicate or excessive archive entries')
        if sum(i.file_size for i in archive.infolist())>20_100_000:raise ValueError('Oversized archive')
        for name in names:
            relative(name)
            if archive.getinfo(name).file_size>2_000_000:raise ValueError('Oversized entry')
        inventory=json.loads(archive.read('BUNDLE_MANIFEST.json'))
        if inventory.get('schema')!='guardian-local-preview-v1' or inventory.get('public_release_ready') is not False:
            raise ValueError('Invalid preview metadata')
        rows=inventory['files']
        if not isinstance(rows,list) or len({r['path'] for r in rows})!=len(rows):raise ValueError('Invalid inventory')
        if {r['path'] for r in rows}|{'BUNDLE_MANIFEST.json'}!=set(names):raise ValueError('Unexpected archive files')
        for row in rows:
            data=archive.read(row['path'])
            if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Content hash mismatch')
        if set(json.loads(archive.read(MANIFEST)))!={r['path'] for r in rows}:raise ValueError('Allowlist mismatch')
        return inventory


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'.local/releases/guardian-local-preview.zip')
    parser.add_argument('--verify',type=Path)
    args=parser.parse_args()
    if args.verify:
        content=args.verify.read_bytes();inventory=verify(content)
        print(json.dumps({'verified':True,'files':len(inventory['files']),'sha256':hashlib.sha256(content).hexdigest(),'authenticity_verified':False}));return
    content,inventory=build()
    verify(content)
    digest=hashlib.sha256(content).hexdigest()
    output=args.output.absolute()
    if not output.is_relative_to(ROOT):raise ValueError('Output must stay inside the project')
    # Resolve existing ancestors before creating anything; do not write through links.
    if not output.resolve().is_relative_to(ROOT):raise ValueError('Output leaves project through a link')
    for ancestor in (output,*output.parents):
        if ancestor==ROOT:break
        if ancestor.exists() and (ancestor.is_symlink() or getattr(ancestor.lstat(),'st_file_attributes',0)&1024):
            raise ValueError('Linked output path')
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with output.open('xb') as stream:stream.write(content)
    except FileExistsError:
        if output.read_bytes()!=content:raise ValueError('Different bundle exists; choose a new output filename')
    print(json.dumps({'output':str(output),'sha256':digest,'files':len(inventory['files']),'bytes':len(content),
                      'public_release_ready':False}))


if __name__=='__main__':main()
