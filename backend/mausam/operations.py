"""One bounded maintenance iteration, suitable for launchd, cron or a worker."""
import argparse, hashlib, json, os, shutil, subprocess
from datetime import datetime, timezone
from pathlib import Path
import httpx
from .refresh import refresh_once, checked_pointer, choose_cycle
from .storage import atomic_write, file_lock, json_bytes


def iso():return datetime.now(timezone.utc).isoformat()


def backup(config,now):
    if config.get('container_mode'):
        from .container_service import container_backup
        try:return container_backup(config,now)
        except Exception as error:return {'status':'failed','error_type':type(error).__name__}
    root=Path(config['runtime']);folder=root/'backups';folder.mkdir(parents=True,exist_ok=True)
    folder.chmod(0o700);name=now.strftime('%Y%m%d');manifest=folder/(name+'.json')
    if manifest.exists():
        record=json.loads(manifest.read_text())
        pairs=[('database','database_sha256'),('public_asset','public_sha256'),('artifacts','artifacts_sha256')]
        if record.get('global_public_asset'):pairs.append(('global_public_asset','global_public_sha256'))
        elif (Path(config['public'])/'global-latest.json').exists():pairs.append(('global_public_asset','global_public_sha256'))
        for name,key in pairs:
            filename=record.get(name,'')
            if not filename or Path(filename).name!=filename:
                return {'status':'failed','error_type':'InvalidBackupManifest','checked_at':iso()}
            saved=folder/filename
            if not saved.is_file() or hashlib.sha256(saved.read_bytes()).hexdigest()!=record.get(key):
                return {'status':'failed','error_type':'BackupIntegrityFailure','checked_at':iso()}
        return record
    command=['docker','compose','-p',config['compose_project']]
    temporary=folder/(name+'.dump.part');target=folder/(name+'.dump')
    try:
        with temporary.open('wb') as stream:
            subprocess.run(command+['exec','-T','postgres','pg_dump','-U','mausam','-Fc','mausam'],
                cwd=config['repository'],stdout=stream,stderr=subprocess.PIPE,timeout=90,check=True)
        if not temporary.read_bytes().startswith(b'PGDMP'):raise ValueError('Invalid database backup')
        temporary.chmod(0o600);temporary.replace(target)
        public=Path(config['public']);pointer,product=checked_pointer(public)
        saved=folder/(name+'-'+pointer['path']);shutil.copyfile(public/pointer['path'],saved);saved.chmod(0o600)
        result={'status':'complete','created_at':iso(),'database':target.name,
                'database_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                'public_asset':saved.name,'public_sha256':pointer['sha256'],'run_id':product['run_id']}
        try:
            global_pointer,global_product=checked_pointer(public,'global-latest.json')
            global_saved=folder/(name+'-'+global_pointer['path']);shutil.copyfile(public/global_pointer['path'],global_saved);global_saved.chmod(0o600)
            result.update(global_public_asset=global_saved.name,global_public_sha256=global_pointer['sha256'],global_run_id=global_product['run_id'])
        except (OSError,ValueError,KeyError):pass
        archive=folder/(name+'-artifacts.tar.gz')
        with archive.open('wb') as stream:
            subprocess.run(command+['exec','-T','api','python','-m','mausam.backup'],cwd=config['repository'],
                stdout=stream,stderr=subprocess.PIPE,timeout=120,check=True)
        archive.chmod(0o600)
        result.update(artifacts=archive.name,artifacts_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        atomic_write(manifest,json_bytes(result))
        # Retention applies only to backups created by this utility, never raw research files.
        records=sorted(folder.glob('[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].json'),reverse=True)
        for old in records[int(config.get('backup_copies',7)):]:
            data=json.loads(old.read_text())
            for key in ['database','public_asset','global_public_asset','artifacts']:
                filename=data.get(key,'')
                if filename and Path(filename).name==filename:
                    (folder/filename).unlink(missing_ok=True)
            old.unlink()
        return result
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        temporary.unlink(missing_ok=True)
        return {'status':'failed','error_type':type(error).__name__,'checked_at':iso()}


def run_once(config):
    root=Path(config['runtime']);root.mkdir(parents=True,exist_ok=True)
    public=Path(config['public']);now=datetime.now(timezone.utc)
    with file_lock(root/'.operations-cycle.lock',blocking=False):
        free=shutil.disk_usage(root).free
        budget=config.get('host_budget_path')
        if budget and Path(budget).exists():free=min(free,shutil.disk_usage(budget).free)
        minimum=int(config.get('minimum_free_bytes',5_000_000_000))
        status={'schema_version':1,'checked_at':iso(),'service':'local-research-deployment',
                'disk_free_gb':round(free/1e9,2),'scientific_status':'experimental','alerts':[]}
        date,cycle=choose_cycle(now);wanted=date+f'-{cycle:02d}'
        try:
            _,current=checked_pointer(public)
            required={'GFS','GEFS','IFS','AIFS'}
            complete=set(current.get('source_status',{}))==required and all(v=='loaded' for v in current.get('source_status',{}).values())
            fresh=current['run_id']=='public-'+wanted and max(current['leads'])>=168 and complete
        except (OSError,ValueError,KeyError):current=None;fresh=False
        if free<minimum:
            status['refresh']={'state':'withheld','reason':'insufficient_disk_space'}
            status['alerts'].append({'severity':'critical','code':'low_disk','message':'Ingestion paused before disk exhaustion.'})
        elif fresh:
            status['refresh']={'state':'unchanged','run_id':current['run_id']}
        else:
            result=refresh_once(root,config['cache'],public,max_lead=168,step=6,deadline=1800)
            status['refresh']={k:result[k] for k in ['state','run_id','finished_at'] if k in result}
        if config.get('enable_global_refresh') and free>=minimum:
            from .global_refresh import refresh_global_once
            try:
                global_result=refresh_global_once(root,config['cache'],public,deadline=2400,
                    minimum_free_bytes=minimum,budget_path=budget)
                status['global_refresh']={k:global_result[k] for k in ['state','run_id','finished_at','reason'] if k in global_result}
            except BlockingIOError:
                status['global_refresh']={'state':'skipped','reason':'global_refresh_lock_busy'}
        elif config.get('enable_global_refresh'):
            status['global_refresh']={'state':'withheld','reason':'insufficient_disk_space'}
        try:
            _,current=checked_pointer(public)
            age=(now-datetime.fromisoformat(current['initialization'])).total_seconds()/3600
            status.update(run_id=current['run_id'],initialization=current['initialization'],forecast_age_hours=round(age,2),
                          sources={k:'loaded' if v=='loaded' else 'unavailable' for k,v in current['source_status'].items()})
            if age>float(config.get('stale_after_hours',30)):
                status['alerts'].append({'severity':'warning','code':'stale_forecast','message':'Newest published forecast exceeds the age limit.'})
        except (OSError,ValueError,KeyError):
            status['alerts'].append({'severity':'critical','code':'no_product','message':'No intact published forecast is available.'})
        try:
            _,global_product=checked_pointer(public,'global-latest.json')
            global_age=(now-datetime.fromisoformat(global_product['initialization'])).total_seconds()/3600
            status['global_forecast']={'state':'available','run_id':global_product['run_id'],'initialization':global_product['initialization'],'forecast_age_hours':round(global_age,2),'sources':{k:'loaded' if v=='loaded' else 'unavailable' for k,v in global_product.get('source_status',{}).items()}}
            if global_age>36:
                status['alerts'].append({'severity':'warning','code':'stale_global_forecast','message':'Newest live-global forecast exceeds the age limit.'})
        except (OSError,ValueError,KeyError):
            status['global_forecast']={'state':'not_available'}
            status['alerts'].append({'severity':'warning','code':'global_forecast_unavailable','message':'No intact live-global publication is available.'})
        if config.get('probe_india_sources'):
            try:
                from .india_sources import probe_all
                source_report=probe_all(config.get('research_neps_dir'),config.get('ncum_staging_dir'))
                status['provider_readiness']=[{'name':p['name'],'status':p['status']} for p in source_report['providers']]
                source_output=config.get('source_status_output')
                if source_output:
                    atomic_write(Path(source_output),json_bytes(source_report));Path(source_output).chmod(0o644)
            except Exception as error:
                status['provider_readiness']=[{'name':'India provider probes','status':'probe_failed','error_type':type(error).__name__}]
                status['alerts'].append({'severity':'warning','code':'provider_probe_failed','message':'One or more external provider probes failed.'})
        try:
            response=httpx.get(config['api_url'].rstrip('/')+'/health/ready',timeout=5)
            status['backend']={'ready':response.status_code==200}
        except httpx.HTTPError:status['backend']={'ready':False}
        if not status['backend']['ready']:
            status['alerts'].append({'severity':'critical','code':'backend_not_ready','message':'Backend readiness check failed.'})
        status['backup']=backup(config,now) if free>=minimum else {'status':'withheld_low_disk'}
        if status['backup']['status']!='complete':
            status['alerts'].append({'severity':'warning','code':'backup_not_current','message':'A current backup was not completed.'})
        status['validation']={}
        for name in ['shadow-rain-status.json','multi-shadow-status.json','imd-gauge-status.json']:
            path=public/name
            if not path.exists():continue
            try:
                report=json.loads(path.read_text())
                if name=='shadow-rain-status.json':
                    status['validation'].update(prospective_start=report.get('prospective_start'),rain_prospective_event_blocks=report.get('prospective_event_blocks'),rain_event_blocks=report.get('event_blocks'))
                elif name=='multi-shadow-status.json':
                    status['validation']['candidate_models']=report.get('summary',{}).get('candidate_models')
                else:
                    rows=report.get('rows',[])
                    status['validation']['imd_reports']=len(rows)
                    status['validation']['imd_latest_window']=max((x['forecast_window_end'] for x in rows),default=None)
            except (OSError,ValueError,KeyError):
                status['alerts'].append({'severity':'warning','code':'validation_status_invalid','message':'Validation status could not be read.'})
        from .operational_health import apply_health, attach_mosdac
        apply_health(attach_mosdac(status, public))
        status['alert_delivery']='local_operations_dashboard_and_event_log'
        status['next_check_seconds']=int(config.get('interval_seconds',3600))
        status['checked_at']=iso()
        previous=root/'service-status.json'
        old=json.loads(previous.read_text()) if previous.exists() else {}
        old_codes={a['code'] for a in old.get('alerts',[])}
        new_codes={a['code'] for a in status['alerts']}
        if old_codes!=new_codes:
            event={'at':iso(),'active_alerts':sorted(new_codes),'resolved_alerts':sorted(old_codes-new_codes)}
            with (root/'alert-events.jsonl').open('a') as log:
                log.write(json.dumps(event)+'\n');log.flush();os.fsync(log.fileno())
        atomic_write(previous,json_bytes(status))
        projection={k:v for k,v in status.items() if k!='backup'}
        projection['backup']={k:v for k,v in status['backup'].items() if k in ['status','created_at','run_id','error_type']}
        atomic_write(public/'operations.json',json_bytes(projection));(public/'operations.json').chmod(0o644)
        return status


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);args=parser.parse_args()
    config=json.loads(args.config.read_text())
    if not 1<=int(config.get('backup_copies',7))<=30:parser.error('backup_copies must be between 1 and 30')
    try:result=run_once(config)
    except BlockingIOError:result={'status':'skipped','reason':'Another maintenance cycle owns the lock'}
    print(json.dumps(result),flush=True)
