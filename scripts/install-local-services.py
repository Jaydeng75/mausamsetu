"""Install user-owned macOS services. No public port or paid resource is created."""
import argparse,json,os,plistlib,shutil,subprocess,sys
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--python',required=True,type=Path)
parser.add_argument('--runtime',required=True,type=Path)
parser.add_argument('--cache',required=True,type=Path)
parser.add_argument('--install',action='store_true')
args=parser.parse_args();repo=Path(__file__).resolve().parents[1]
if sys.platform!='darwin':parser.error('This installer is for macOS; use the deployment runbook on Linux.')
if not (repo/'.next/BUILD_ID').exists():parser.error('Build the application first.')
if not args.python.is_file():parser.error('Configured Python executable not found.')
node=shutil.which('node')
if not node:parser.error('Node is not available.')
runtime=args.runtime.resolve();runtime.mkdir(parents=True,exist_ok=True);runtime.chmod(0o700)
config={'runtime':str(runtime),'repository':str(repo),'public':str(repo/'public/data/products'),
        'cache':str(args.cache.resolve()),'compose_project':'mausamsetu-audit',
        'api_url':'http://127.0.0.1:8000','interval_seconds':3600,'backup_copies':7,
        'minimum_free_bytes':5000000000,'stale_after_hours':30}
configuration=runtime/'service-config.json';configuration.write_text(json.dumps(config,indent=2));configuration.chmod(0o600)
agents=Path.home()/'Library/LaunchAgents';agents.mkdir(parents=True,exist_ok=True)
profiles={
 'in.mausamsetu.web':{'ProgramArguments':[node,str(repo/'scripts/start-standalone.mjs'),'--hostname','127.0.0.1','--port','4173'],
  'KeepAlive':True,'ThrottleInterval':15,'EnvironmentVariables':{'MAUSAM_PUBLIC_BACKEND_URL':'http://127.0.0.1:8000','NODE_ENV':'production'}},
 'in.mausamsetu.operations':{'ProgramArguments':[os.path.abspath(args.python),'-m','mausam.operations','--config',str(configuration)],
  'RunAtLoad':True,'StartInterval':3600,'ProcessType':'Background','EnvironmentVariables':{'PYTHONPATH':str(repo/'backend'),'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'}}}
destination=agents if args.install else runtime/'launchd-preview';destination.mkdir(parents=True,exist_ok=True)
for label,profile in profiles.items():
    profile.update(Label=label,WorkingDirectory=str(repo),
                   StandardOutPath=str(runtime/(label+'.out.log')),StandardErrorPath=str(runtime/(label+'.err.log')))
    path=destination/(label+'.plist')
    if path.exists():
        old=plistlib.loads(path.read_bytes())
        if old.get('WorkingDirectory')!=str(repo):parser.error('Existing service belongs to another checkout: '+label)
    if args.install:
        subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{label}'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    path.write_bytes(plistlib.dumps(profile));path.chmod(0o600)
    if args.install:
        subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(path)],check=True)
    print(('Installed ' if args.install else 'Prepared ')+label+' at '+str(path))
print('Frontend: http://127.0.0.1:4173')
print('Scope: this Mac while powered on and logged in; not an always-on public deployment.')
print('Runtime configuration: '+str(configuration))
