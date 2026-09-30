"""Consistent local artifact snapshots. Database backups are made separately."""
import argparse, os, sys, tarfile
from contextlib import ExitStack
from pathlib import Path
from .storage import Archive, file_lock

ALLOWED=['published','models','raw','observation-archive','verification-reports',
         'verification.json','latest.json','operations.json']


def snapshot(root,output,max_bytes=2_000_000_000):
    root=Path(root)
    with ExitStack() as locks:
        for name in ['.publication.lock','models/.registry.lock','.verification.lock']:
            locks.enter_context(file_lock(root/name))
        files=[]
        for name in ALLOWED:
            path=root/name
            if not path.exists():continue
            for item in ([path] if path.is_file() else path.rglob('*')):
                if item.is_symlink():raise ValueError('Symlinks are not included in backup snapshots')
                if item.is_file() and not item.name.endswith('.lock'):files.append(item)
        if sum(path.stat().st_size for path in files)>max_bytes:
            raise ValueError('Local snapshot exceeds size budget; use managed object-store backup')
        for path in (root/'published').glob('*/manifest.json'):Archive(root).verify(path.parent.name)
        with tarfile.open(fileobj=output,mode='w|gz') as archive:
            for path in sorted(files):archive.add(path,arcname=str(path.relative_to(root)),recursive=False)


def restore(source,destination):
    destination=Path(destination)
    if destination.exists() and any(destination.iterdir()):raise ValueError('Restore requires an empty destination')
    destination.mkdir(parents=True,exist_ok=True)
    with tarfile.open(source,'r:gz') as archive:
        members=archive.getmembers()
        if sum(m.size for m in members)>2_000_000_000:raise ValueError('Restore exceeds size bound')
        for member in members:
            path=Path(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in ALLOWED:
                raise ValueError('Unsafe archive member')
            if not member.isfile():raise ValueError('Only regular files may be restored')
        archive.extractall(destination,filter='data')
    restored=Archive(destination)
    for manifest in (destination/'published').glob('*/manifest.json'):
        restored.verify(manifest.parent.name)
    return restored.latest()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',default=os.getenv('MAUSAM_DATA_DIR','./data'))
    parser.add_argument('--restore');parser.add_argument('--into');args=parser.parse_args()
    if args.restore:
        if not args.into:parser.error('--into is required for restoration')
        print(restore(args.restore,args.into))
    else:snapshot(args.root,sys.stdout.buffer)
