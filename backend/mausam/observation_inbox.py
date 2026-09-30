"""Process authorized, normalized observation batches without guessing metadata."""
import hashlib,json
from pathlib import Path
from datetime import datetime,timezone
from .storage import atomic_write,file_lock,json_bytes
from .verify import verify_run,utc


def process_inbox(root,limit=10):
    root=Path(root);inbox=root/'observation-inbox';inbox.mkdir(parents=True,exist_ok=True)
    receipts=inbox/'receipts';receipts.mkdir(exist_ok=True);results=[]
    with file_lock(inbox/'.inbox.lock',blocking=False):
        for path in sorted(inbox.glob('*.json')):
            if len(results)>=limit:break
            if path.is_symlink() or path.stat().st_size>65536:continue
            body=path.read_bytes();identifier=hashlib.sha256(body).hexdigest()
            receipt=receipts/(identifier+'.json')
            if receipt.exists():continue
            try:
                meta=json.loads(body)
                if not isinstance(meta,dict):raise ValueError("Observation metadata must be an object")
                if meta.get('ready') is not True:continue
                if utc(meta['available_at'])>datetime.now(timezone.utc):continue
                filename=meta['file']
                if Path(filename).name!=filename or not filename.endswith('.npy'):
                    raise ValueError('Observation file must be a local NPY basename')
                numerical=inbox/filename
                if not numerical.exists():continue
                if numerical.is_symlink() or numerical.stat().st_size>128000000:
                    raise ValueError('Unsafe or oversized observation file')
                report=verify_run(root,meta['run_id'],numerical,path)
                result={'status':'verified','batch_sha256':identifier,'verification_id':report['verification']['id']}
            except FileNotFoundError:
                continue
            except (ValueError,KeyError,OSError,TypeError,AttributeError) as error:
                result={'status':'quarantined','batch_sha256':identifier,'error_type':type(error).__name__}
            atomic_write(receipt,json_bytes(result));results.append(result)
    return results
