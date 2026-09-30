"""Docker-native scheduled ingestion, monitoring and scientific-artifact backups."""
import hashlib,json,os,time,shutil
from datetime import datetime,timezone
from pathlib import Path
from .backup import snapshot
from .refresh import checked_pointer
from .storage import atomic_write,json_bytes


def container_backup(config,now):
    folder=Path(config.get('backups','/backups'));day=now.strftime('%Y%m%d')
    database=folder/'db'/(day+'.dump');checksum=database.with_suffix('.dump.sha256')
    if not database.is_file() or not checksum.is_file():return {'status':'pending_database_backup'}
    digest=hashlib.sha256(database.read_bytes()).hexdigest()
    if digest!=checksum.read_text().strip():return {'status':'failed','error_type':'DatabaseBackupChecksumFailure'}
    base=folder/'artifacts';base.mkdir(parents=True,exist_ok=True)
    manifest=base/(day+'.json')
    if manifest.exists():
        record=json.loads(manifest.read_text())
        if record.get('database_sha256')==digest:
            pairs=[('artifacts','artifacts_sha256'),('public_asset','public_sha256')]
            if record.get('global_public_asset'):pairs.append(('global_public_asset','global_public_sha256'))
            elif (Path(config['public'])/'global-latest.json').exists():pairs.append(('global_public_asset','global_public_sha256'))
            for key,hash_key in pairs:
                name=record.get(key,'')
                if Path(name).name!=name or not (base/name).is_file():break
                if hashlib.sha256((base/name).read_bytes()).hexdigest()!=record.get(hash_key):break
            else:return record
    name='artifacts-'+day+'-'+digest[:12]+'.tar.gz';target=base/name;temporary=base/(name+'.part')
    with temporary.open('wb') as stream:
        snapshot(config['runtime'],stream);stream.flush();os.fsync(stream.fileno())
    temporary.replace(target)
    target.chmod(0o600)
    pointer,product=checked_pointer(config['public'])
    saved=base/('public-'+day+'-'+digest[:12]+'.json')
    shutil.copyfile(Path(config['public'])/pointer['path'],saved);saved.chmod(0o600)
    result={'status':'complete','created_at':datetime.now(timezone.utc).isoformat(),
      'database':database.name,'database_sha256':digest,'artifacts':target.name,
      'artifacts_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
      'public_asset':saved.name,'public_original_path':pointer['path'],
      'public_sha256':pointer['sha256'],'run_id':product['run_id']}
    try:
        global_pointer,global_product=checked_pointer(config['public'],'global-latest.json')
        global_saved=base/('global-'+day+'-'+digest[:12]+'.json')
        shutil.copyfile(Path(config['public'])/global_pointer['path'],global_saved);global_saved.chmod(0o600)
        result.update(global_public_asset=global_saved.name,global_public_original_path=global_pointer['path'],
          global_public_sha256=global_pointer['sha256'],global_run_id=global_product['run_id'])
    except (OSError,ValueError,KeyError):pass
    atomic_write(manifest,json_bytes(result))
    records=sorted(base.glob('[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].json'),reverse=True)
    for old in records[7:]:
        record=json.loads(old.read_text())
        for key in ['artifacts','public_asset','global_public_asset']:
            name=record.get(key,'')
            if Path(name).name==name and old.stem in name:(base/name).unlink(missing_ok=True)
        old.unlink()
    return result


if __name__=='__main__':
    from .operations import run_once
    config={'runtime':'/data','public':'/public','cache':'/cache','backups':'/backups',
      'api_url':'http://api:8000','container_mode':True,'interval_seconds':3600,
      'backup_copies':7,'minimum_free_bytes':5000000000,'stale_after_hours':30,
      'host_budget_path':'/host-budget','enable_global_refresh':True}
    while True:
        try:print(json.dumps(run_once(config)),flush=True)
        except Exception as error:print(json.dumps({'status':'failed','error_type':type(error).__name__}),flush=True)
        time.sleep(3600)
