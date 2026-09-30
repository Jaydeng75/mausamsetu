import io,importlib,json,tarfile,time
from types import SimpleNamespace
import jwt,numpy as np,pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from mausam.backup import snapshot,restore
from mausam.golden import generate
from mausam.adaptive import predict_weights


@pytest.fixture
def authenticated(tmp_path,monkeypatch):
    monkeypatch.setenv('MAUSAM_DATA_DIR',str(tmp_path));monkeypatch.setenv('MAUSAM_ALLOW_ANONYMOUS_READ','false')
    monkeypatch.setenv('OIDC_ISSUER','https://identity.example.test/realm')
    monkeypatch.setenv('OIDC_AUDIENCE','mausamsetu');monkeypatch.delenv('MAUSAM_ENV',raising=False)
    import mausam.api as api
    api=importlib.reload(api);generate(tmp_path)
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    monkeypatch.setattr(api,'jwks_client',lambda:SimpleNamespace(get_signing_key_from_jwt=lambda token:SimpleNamespace(key=key.public_key())))
    def token(roles,**changes):
        claims={'sub':'test-user','iss':'https://identity.example.test/realm','aud':'mausamsetu',
                'iat':int(time.time()),'exp':int(time.time())+300,'realm_access':{'roles':roles},**changes}
        return {'Authorization':'Bearer '+jwt.encode(claims,key,algorithm='RS256')}
    with TestClient(api.app) as client:yield client,token


def test_signed_viewer_is_read_only(authenticated):
    client,token=authenticated
    assert client.get('/v1/runs/latest',headers=token(['viewer'])).status_code==200
    body={'run_id':'golden-20260926-00-v1','text':'Review fixture','status':'draft','lat':13,'lng':80}
    assert client.post('/v1/reviews',json=body,headers=token(['viewer'])).status_code==403
    assert client.post('/v1/reviews',json=body,headers=token(['reviewer'])).status_code==201
    body['status']='approved'
    assert client.post('/v1/reviews',json=body,headers=token(['reviewer'])).status_code==403
    assert client.post('/v1/reviews',json=body,headers=token(['reviewer','approver'])).status_code==201


def test_expired_wrong_audience_and_unprivileged_tokens_fail(authenticated):
    client,token=authenticated
    for headers in [token(['viewer'],exp=int(time.time())-10),token(['viewer'],aud='other'),token([])]:
        assert client.get('/v1/runs/latest',headers=headers).status_code==401
    assert client.get('/v1/runs/latest').status_code==401


def test_backup_restores_verified_products(tmp_path):
    root=tmp_path/'source';original=generate(root);buffer=io.BytesIO();snapshot(root,buffer)
    archive=tmp_path/'snapshot.tar.gz';archive.write_bytes(buffer.getvalue())
    result=restore(archive,tmp_path/'restored')
    assert result==original
    with pytest.raises(ValueError,match='empty'):restore(archive,tmp_path/'restored')


def test_restore_rejects_path_traversal(tmp_path):
    archive=tmp_path/'bad.tar.gz'
    with tarfile.open(archive,'w:gz') as stream:
        info=tarfile.TarInfo('../escaped');info.size=3;stream.addfile(info,io.BytesIO(b'bad'))
    with pytest.raises(ValueError,match='Unsafe'):restore(archive,tmp_path/'restore')
    assert not (tmp_path/'escaped').exists()


def test_unavailable_source_features_are_not_used():
    model={'schema_version':1,'method':'linear-softmax-crps','feature_count':2,'source_count':2,
      'mean':[0,0],'scale':[1,1],'coefficients':[[0,0],[2,-2],[-2,2]],
      'feature_names':['source_0_mean','source_1_mean']}
    first=predict_weights(model,[[10,100000]],[True,False])
    second=predict_weights(model,[[10,-100000]],[True,False])
    assert np.array_equal(first,second) and np.array_equal(first,[[1,0]])
    with pytest.raises(ValueError):predict_weights(model,[[10,20]],[False,False])


def test_snapshot_refuses_symlinks(tmp_path):
    generate(tmp_path/'source')
    (tmp_path/'source'/'raw'/'untrusted-link').symlink_to(tmp_path/'outside')
    with pytest.raises(ValueError,match='Symlinks'):snapshot(tmp_path/'source',io.BytesIO())
