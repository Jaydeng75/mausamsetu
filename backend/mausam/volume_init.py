"""Initialize only explicitly mounted application volumes; never reset existing data."""
import os,shutil
from pathlib import Path


def initialize():
    if os.geteuid()!=0:raise RuntimeError('Volume initialization requires container root')
    for name in ['/public','/cache','/backups']:
        path=Path(name);path.mkdir(parents=True,exist_ok=True)
        os.chown(path,10001,10001);path.chmod(0o755 if name=='/public' else 0o700)
    count=0
    for source,destination,patterns in [('/seed-public','/public',['*.json']),
                                        ('/seed-cache','/cache',['gfs-*.grib2','gefs-*.grib2','ifs-*.grib2','aifs-*.grib2'])]:
        for pattern in patterns:
            for path in Path(source).glob(pattern):
                if not path.is_file() or path.is_symlink() or path.name=='operations.json':continue
                target=Path(destination)/path.name
                if target.exists():continue
                temporary=target.with_suffix(target.suffix+'.seed-part')
                shutil.copyfile(path,temporary);os.chown(temporary,10001,10001)
                temporary.chmod(0o644 if destination=='/public' else 0o600)
                temporary.replace(target);count+=1
    print('Initialized application volumes; seeded files:',count,flush=True)


if __name__=='__main__':initialize()
