import hashlib
import io
import json
from urllib.error import HTTPError
import pytest
from tools.zar_deploy_check import check


class Response(io.BytesIO):
    status=200


def transport(version='33.3.104',failure=False,commit=None):
    calls=[]
    def open_request(request,timeout):
        calls.append(request)
        if request.method=='GET':return Response(json.dumps({'ok':True,'version':version,'commit':commit}).encode())
        if failure:raise HTTPError(request.full_url,401,'fixture-key-must-not-appear',{},None)
        return Response(b'provider body not read')
    return open_request,calls


@pytest.mark.parametrize('version',['33.3.100','bad-version',None])
def test_no_inference_before_target_deployment(version):
    opener,calls=transport(version)
    result=check('https://zar.test','33.3.104',smoke=True,env={'OPENROUTER_API_KEY':'fixture-replacement'},opener=opener)
    assert not result['deployment_ready'] and len(calls)==1
    assert result['openrouter']['status']=='BLOCKED_DEPLOYMENT'


def test_key_absence_and_wrong_replacement_never_send_provider_request():
    for env,fingerprint,expected in [({},None,'KEY_UNAVAILABLE'),({'OPENROUTER_API_KEY':'fixture-obsolete'},'b8853071ed65','REPLACEMENT_NOT_ACTIVE'),({'OPENROUTER_API_KEY':'fixture-new'},None,'EXPECTED_REPLACEMENT_FINGERPRINT_REQUIRED')]:
        opener,calls=transport()
        result=check('https://zar.test','33.3.104',smoke=True,env=env,key_fingerprint=fingerprint,opener=opener)
        assert result['openrouter']['status']==expected and len(calls)==1


@pytest.mark.parametrize('failure',[False,True])
def test_exactly_one_free_tiny_request_and_no_secrets_or_error_bodies(failure):
    key='fixture-replacement-not-a-real-provider-key';opener,calls=transport(failure=failure)
    result=check('https://zar.test','33.3.104',smoke=True,env={'OPENROUTER_API_KEY':key},key_fingerprint=hashlib.sha256(key.encode()).hexdigest()[:12],opener=opener)
    assert len(calls)==2 and calls[1].method=='POST'
    assert json.loads(calls[1].data)['model']=='openrouter/free'
    assert json.loads(calls[1].data)['max_tokens']==4
    assert result['openrouter']['requests']==1
    assert result['openrouter']['status']==('HTTP_ERROR' if failure else 'OK')
    assert key not in json.dumps(result) and 'fixture-key-must-not-appear' not in json.dumps(result)


def test_health_commit_mismatch_blocks_smoke_and_missing_commit_is_explicit():
    opener,calls=transport(commit='aaaaaaaa')
    result=check('https://zar.test','33.3.104',expected_commit='bbbbbbbb',smoke=True,opener=opener)
    assert result['commit_match'] is False and not result['deployment_ready'] and len(calls)==1
    opener,_=transport();result=check('https://zar.test','33.3.104',expected_commit='bbbbbbbb',opener=opener)
    assert result['commit'] is None and result['commit_match'] is None


def test_semantic_version_and_no_credentials_in_target():
    opener,_=transport(version='33.3.110')
    assert check('https://zar.test','33.3.104',opener=opener)['deployment_ready']
    with pytest.raises(ValueError):check('https://user:fixture-password@zar.test','33.3.104',opener=opener)
