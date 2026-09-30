"""Durable replay queue worker. Run separately from the API."""
import json,time,os
from datetime import datetime
from sqlalchemy import select
from .api import Session,Record,manifest,ROOT

def run_once():
    from .observation_inbox import process_inbox
    try:process_inbox(ROOT)
    except BlockingIOError:pass
    with Session.begin() as db:
        # PostgreSQL locks prevent competing workers from taking the same record.
        for job in db.scalars(select(Record).where(Record.kind=='replay').with_for_update(skip_locked=True)):
            data=json.loads(job.payload)
            if data['status']!='queued':continue
            try:
                m=manifest(data['run_id']);data.update(status='completed',forecast_manifest=m,observation_status='not_available')
                # Observations are never silently substituted by reanalysis or current data.
                p=ROOT/'observations'/f"{data['run_id']}.json"
                if p.exists():
                    observation=json.loads(p.read_text())
                    available=observation.get('available_at')
                    if available and datetime.fromisoformat(available)<=datetime.fromisoformat(data['as_of']):
                        data.update(observation_status='available',observation=observation)
                    else:data.update(observation_status='not_available_as_of')
            except Exception as e:data.update(status='failed',error=str(e))
            job.payload=json.dumps(data)
if __name__=='__main__':
    while True:run_once();time.sleep(10)
