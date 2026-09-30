import hashlib,json
from datetime import datetime,timezone
from mausam.india_sources import (parse_erddap_catalog,probe_imd,probe_imd_realtime,probe_incois,
    probe_neps,probe_ncum,probe_imd_grid,IMD_REALTIME_BYTES)

class Response:
    def __init__(self,status_code,text='',content=None,headers=None):
        self.status_code=status_code;self.text=text;self.content=content if content is not None else text.encode();self.headers=headers or {}
    def raise_for_status(self):
        if self.status_code>=400:
            import httpx
            request=httpx.Request('GET','https://example.test')
            response=httpx.Response(self.status_code,request=request)
            raise httpx.HTTPStatusError('bad status',request=request,response=response)
    def json(self):return json.loads(self.text)

class Client:
    def __init__(self,responses):self.responses=list(responses)
    def get(self,url,**kwargs):return self.responses.pop(0)
    def post(self,url,**kwargs):return self.responses.pop(0)
    def close(self):pass

def test_erddap_active_catalog_is_parsed():
    text='datasetID,title,institution,dataStructure,cdm_data_type\nallDatasets,All,INCOIS,table,Other\nascat_daily_datasets,ASCAT,ifremer,grid,Grid\nincois_tmi_3day_datasets,TMI,INCOIS,grid,Grid\n'
    rows=parse_erddap_catalog(text)
    assert set(rows)=={'ascat_daily_datasets','incois_tmi_3day_datasets'}
    report=probe_incois(Client([Response(200,text)]))
    assert report['status']=='catalogue_ready'
def test_imd_denied_endpoint_is_not_called_live():
    report=probe_imd(Client([Response(200,'portal'),Response(401,'denied')]))
    assert report['status']=='access_required'
    assert report['http_status']==401

def test_neps_sample_and_missing_ncum_are_distinct(tmp_path):
    neps=tmp_path/'research'/'neps';neps.mkdir(parents=True)
    (neps/'manifest.json').write_text(json.dumps({'provider':'NCMRWF via TIGGE/ECDS','retrieved_at':'2026-09-26T00:00:00Z'}))
    assert probe_neps(neps)['status']=='local_research_sample_ready'
    assert probe_ncum(None)['status']=='access_required'
    assert probe_ncum(tmp_path/'missing')['status']=='access_required'

def test_ncum_requires_real_authorized_import_manifest(tmp_path):
    root=tmp_path/'ncum';root.mkdir();body=b'numerical-fixture'
    data=root/'abc.grib2';data.write_bytes(body);digest=hashlib.sha256(body).hexdigest()
    meta={'file':data.name,'sha256':digest,'status':'staged_requires_product_specific_normalization',
          'authorization_reference':'SIH-test-authorization','licence':'test-research-use'}
    (root/'abc.json').write_text(json.dumps(meta))
    report=probe_ncum(root)
    assert report['status']=='authorized_file_staged' and report['numerical_files']==1
    meta['sha256']='0'*64;(root/'abc.json').write_text(json.dumps(meta))
    assert probe_ncum(root)['status']=='access_required'
def test_imd_grid_requires_checksum_matching_manifest(tmp_path):
    raw=tmp_path/'imd';raw.mkdir();data=raw/'ind2020_rfp25.nc';data.write_bytes(b'fixture')
    digest=hashlib.sha256(data.read_bytes()).hexdigest()
    meta={'file':data.name,'sha256':digest,'year':2020,'product':'0.25 degree daily gridded rainfall',
          'units':'mm','blocking_issue':'interval review required'}
    (raw/'ind2020_rfp25.manifest.json').write_text(json.dumps(meta))
    report=probe_imd_grid(raw)
    assert report['status']=='historical_grid_staged' and report['year']==2020
    data.write_bytes(b'changed')
    assert probe_imd_grid(raw)['status']=='staged_integrity_failed'

def test_empty_erddap_catalog_does_not_claim_context():
    text='datasetID,title,institution,dataStructure,cdm_data_type\nother,Other,X,grid,Grid\n'
    report=probe_incois(Client([Response(200,text)]))
    assert report['status']=='catalogue_changed'
    assert report['datasets']==[]


def test_imd_realtime_grid_requires_binary_contract():
    now=datetime(2026,9,27,12,tzinfo=timezone.utc)
    body=b'\0'*IMD_REALTIME_BYTES
    good=Response(200,content=body,headers={
        'content-type':'application/octet-stream',
        'content-disposition':'attachment; filename=rain_ind0.25_26_09_27.grd'
    })
    report=probe_imd_realtime(Client([Response(200,'form'),good]),now=now)
    assert report['status']=='realtime_grid_ready'
    assert report['latest_valid_interval']=='2026-09-26T03:00:00Z/2026-09-27T03:00:00Z'

    bad=Response(200,text='<html>error</html>',headers={'content-type':'text/html'})
    report=probe_imd_realtime(Client([Response(200,'form'),bad]),now=now)
    assert report['status']=='schema_changed'
