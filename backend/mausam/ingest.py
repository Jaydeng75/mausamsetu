"""Authorized source manifests are configured by operators, never inferred from a model name."""
import hashlib,time
from datetime import datetime,timezone
from pathlib import Path
import httpx
from .contracts import SourceMetadata

def ingest_file(url,expected_sha256,archive,allowed_hosts,max_bytes=512_000_000,retries=3):
    from urllib.parse import urlparse
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname not in allowed_hosts:raise ValueError('Source URL must be an explicitly allowed HTTPS provider')
    for attempt in range(retries):
        try:
            with httpx.stream('GET',url,timeout=120,follow_redirects=False) as response:
                response.raise_for_status();data=bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data)>max_bytes:raise ValueError('Input exceeds configured size bound')
            if hashlib.sha256(data).hexdigest()!=expected_sha256:raise ValueError('Checksum mismatch; quarantine source input')
            return archive.put_raw(bytes(data))
        except (httpx.TransportError,httpx.HTTPStatusError):
            if attempt==retries-1:raise
            time.sleep(2**attempt)

def eligible(metadata:SourceMetadata,decision_time:datetime,required_members:int,received_members:int):
    if metadata.provider_publication_time>decision_time or metadata.ingested_at>decision_time:return False,'Unavailable at decision time'
    if metadata.quality_flags:return False,', '.join(metadata.quality_flags)
    if received_members<required_members:return False,'Incomplete ensemble; unsupported fallback'
    return True,'complete'
