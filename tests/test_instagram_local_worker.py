"""Focused offline transport, identity, extraction and same-item continuation tests."""
import io
import json
import time
from unittest.mock import Mock, patch

import pytest
from flask import Flask
from app import instagram_local_queue as q, instagram_local_worker as w, reposnews as rn, reposnews_inbox as inbox


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('INSTAGRAM_REPOSNEWS_SENDERS', 'sender')
    rn.write({'owner':'owner','articles':[], 'instagram_inbox':[{'id':'same-item','external_id':'original','sender':'sender',
        'source_url':'https://www.instagram.com/reel/fixture/', 'status':'NEEDS_DISAMBIGUATION', 'attempts':5}]})
    monkeypatch.setattr(q.holdings,'read',lambda scope:{})
    monkeypatch.setattr(inbox,'start_worker',lambda:None)
    app = Flask(__name__); app.secret_key='fixture'
    q.register(app)
    token = q.pair('owner')['token']
    c = app.test_client(); c.environ_base['HTTP_AUTHORIZATION']='Bearer '+token
    return c


def claim(client):
    r=client.post('/api/reposnews/local-worker/poll',json={'session':'CONNECTED'})
    assert r.status_code==200
    return r.json['job']


@pytest.mark.parametrize('url', ['http://instagram.com/reel/a/', 'https://instagram.com.evil.org/reel/a/',
    'https://user@instagram.com/reel/a/', 'https://instagram.com:443/reel/a/', 'https://instagram.com/accounts/login/',
    'https://127.0.0.1/reel/a/', 'https://instagram.com/reel/../p/a/', 'file:///reel/a'])
def test_url_allowlist(url):
    for validate in (q.reel_url,w.reel_url):
        with pytest.raises(ValueError):validate(url)


def test_worker_token_and_owner_scope(client):
    assert client.post('/api/reposnews/local-worker/poll',json={},headers={'Authorization':'Bearer wrong'}).status_code==401
    with pytest.raises(ValueError):q.pair('different-owner')
    old=client.environ_base['HTTP_AUTHORIZATION']
    q.pair('owner')
    assert client.post('/api/reposnews/local-worker/poll',json={},headers={'Authorization':old}).status_code==401


def test_same_item_recovery_and_exclusive_claim(client):
    job=claim(client)
    assert job['inbox_item_id']=='same-item';assert job['kind']=='FETCH_INSTAGRAM_REEL'
    assert claim(client) is None
    rows=rn.read()['instagram_inbox'];assert len(rows)==1
    assert rows[0]['external_id']=='original';assert rows[0]['attempts']==5
    assert q.status()['state']=='ONLINE';assert q.status()['account']=='@zaragente031'


def test_heartbeat_never_claims_or_changes_inbox_items(client):
    before=rn.read()['instagram_inbox']
    r=client.post('/api/reposnews/local-worker/heartbeat',json={'session':'CONNECTED'})
    assert r.status_code==200;assert q.status()['state']=='ONLINE'
    assert rn.read()['instagram_inbox']==before


def test_forged_or_expired_lease_cannot_upload(client):
    job=claim(client)
    endpoint='/api/reposnews/local-worker/jobs/same-item/result'
    assert client.post(endpoint,data={'manifest':'{"status":"METADATA_ONLY"}'}).status_code==409
    inbox.update('same-item',local_lease=time.time()-1)
    assert client.post(endpoint,data={'manifest':'{"status":"METADATA_ONLY"}'},headers={'X-ZAR-Job-Lease':job['lease']}).status_code==409


def test_session_expiration_keeps_item_and_requests_manual_login(client):
    job=claim(client)
    r=client.post('/api/reposnews/local-worker/jobs/same-item/result',data={'manifest':json.dumps({'status':'LOGIN_REQUIRED'})},headers={'X-ZAR-Job-Lease':job['lease']})
    assert r.status_code==200
    row=rn.read()['instagram_inbox'][0]
    assert row['status']=='WAITING_LOCAL_WORKER';assert row['error']=='SESSION_EXPIRED'
    assert row['external_id']=='original';assert q.status()['session']=='EXPIRED'
    assert claim(client) is None # Bounded backoff, not a tight authentication loop.


def test_full_media_required_and_mime_checked(client):
    job=claim(client);headers={'X-ZAR-Job-Lease':job['lease']}
    endpoint='/api/reposnews/local-worker/jobs/same-item/result'
    assert client.post(endpoint,data={'manifest':'{"status":"FULL_MEDIA"}'},headers=headers).status_code==400
    assert client.post(endpoint,data={'manifest':'{"status":"FULL_MEDIA"}','video':(io.BytesIO(b'not-video'),'x.mp4','video/mp4')},headers=headers).status_code==400


def test_metadata_and_local_transcript_resume_article_on_same_item(client):
    job=claim(client)
    manifest={'status':'METADATA_ONLY','caption':'Example','analysis':{'transcript':'https://github.com/org/tool','cookies':'never return'}}
    r=client.post('/api/reposnews/local-worker/jobs/same-item/result',data={'manifest':json.dumps(manifest)},headers={'X-ZAR-Job-Lease':job['lease']})
    assert r.status_code==200
    row=rn.read()['instagram_inbox'][0]
    assert row['status']=='RECEIVED';assert row['attempt_limit']==13;assert 'cookies' not in row['analysis']
    assert row['analysis']['transcript']=='https://github.com/org/tool'
    with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'research',return_value={'repo':'org/tool','name':'tool'}),patch.object(inbox,'build',return_value={'id':'draft','published':False}),patch.object(inbox,'store_ready') as store,patch('app.instagram_browser.discovery') as cloud:
        inbox.process('same-item')
    store.assert_called_once();cloud.assert_not_called()
    assert rn.read()['instagram_inbox'][0]['id']=='same-item'


def test_wrong_instagram_identity_is_rejected():
    context=Mock();page=context.new_page.return_value
    context.cookies.return_value=[{'name':'sessionid','value':'fixture'}]
    page.locator.return_value.first.is_visible.return_value=False
    assert not w.verify_session(context)
    page.close.assert_called_once()


def test_playwright_captures_only_media_from_reel_page(tmp_path):
    context=Mock();page=context.new_page.return_value
    page.url='https://www.instagram.com/reel/fixture/'
    response=Mock(url='https://media.cdninstagram.com/video.mp4',headers={'content-type':'video/mp4'})
    response.request.frame=page.main_frame
    page.evaluate.return_value=response.url
    page.locator.return_value.count.return_value=0
    def navigate(*args,**kwargs):page.on.call_args.args[1](response)
    page.goto.side_effect=navigate
    with patch.object(w,'media_url',side_effect=lambda u:u),patch.object(w,'download',return_value=tmp_path/'v.mp4') as download:
        video,_=w.playwright_fetch(context,page.url,tmp_path)
    assert video==tmp_path/'v.mp4';download.assert_called_once()
    response.request.frame=Mock()
    with patch.object(w,'download') as download:
        assert w.playwright_fetch(context,page.url,tmp_path)[0] is None
    download.assert_not_called()
    response.request.frame=page.main_frame
    page.url='https://www.instagram.com/reels/fixture/'
    page.evaluate.return_value='https://media.cdninstagram.com/other-reel.mp4'
    with patch.object(w,'download') as download:
        assert w.playwright_fetch(context,'https://www.instagram.com/reel/fixture/',tmp_path)[0] is None
    download.assert_not_called() # Same-page prefetch is not evidence for this Reel.


def test_ytdlp_uses_only_dedicated_jar_no_password(tmp_path):
    with patch.object(w,'run',return_value=Mock(returncode=1)) as run:
        w.ytdlp('https://www.instagram.com/reel/fixture/',tmp_path,tmp_path/'cookies.txt')
    args=run.call_args.args[0]
    assert '--ignore-config' in args;assert '--cookies' in args
    assert '--username' not in args;assert '--password' not in args;assert '--cookies-from-browser' not in args


def test_public_download_precedes_browser(tmp_path):
    with patch.object(w,'ytdlp',return_value=(tmp_path/'reel.mp4',{})),patch.object(w,'analyze',return_value={}),patch.object(w,'browser') as browser:
        result,video=w.fetch({'kind':'FETCH_INSTAGRAM_REEL','url':'https://www.instagram.com/reel/fixture/'},tmp_path,lambda stage:None)
    assert result['extractor']=='yt-dlp-public';assert result['status']=='FULL_MEDIA';browser.assert_not_called()


def test_forbidden_jobs_never_execute(tmp_path):
    with pytest.raises(ValueError):w.fetch({'kind':'shell','url':'https://www.instagram.com/reel/a/'},tmp_path,Mock())


def test_bounded_process_rejects_forbidden_job_without_network(tmp_path):
    result,video=w.fetch_bounded({'kind':'shell','url':'https://www.instagram.com/reel/a/'},tmp_path,Mock())
    assert result['status']=='EXTRACTOR_FAILED';assert video is None


def test_only_one_worker_owns_local_profile(tmp_path,monkeypatch):
    monkeypatch.setattr(w,'LOCAL',tmp_path)
    with w.single_worker():
        with pytest.raises(OSError):
            with w.single_worker():
                pytest.fail('Duplicate local worker was allowed')


def test_visual_owner_typo_requires_official_website_corroboration():
    candidate={'full_name':'example/tool','name':'tool','homepage':'https://example.org'}
    with patch.object(rn,'github',side_effect=[{'items':[candidate]},candidate]),patch.object(inbox,'homepage_confirms_repository',return_value=True) as backlink:
        assert inbox.repair_visual_repository('examp1e/tool')==candidate
    backlink.assert_called_once_with('https://example.org','example/tool')
    with patch.object(rn,'github',return_value={'items':[candidate]}),patch.object(inbox,'homepage_confirms_repository',return_value=False):
        with pytest.raises(ValueError,match='OFFICIAL_REPOSITORY_UNRESOLVED'):inbox.repair_visual_repository('examp1e/tool')


def test_visual_owner_typo_never_selects_fork_or_multiple_candidates():
    candidates=[{'full_name':'example/tool','homepage':'https://example.org'}, {'full_name':'examp1f/tool','homepage':'https://example.net'}]
    with patch.object(rn,'github',return_value={'items':candidates}),patch.object(inbox,'homepage_confirms_repository',return_value=True):
        with pytest.raises(ValueError):inbox.repair_visual_repository('examp1e/tool')
    with patch.object(rn,'github',return_value={'items':[dict(candidates[0],fork=True)]}),patch.object(inbox,'homepage_confirms_repository') as backlink:
        with pytest.raises(ValueError):inbox.repair_visual_repository('examp1e/tool')
    backlink.assert_not_called()


def test_local_media_recovery_never_sets_limit_below_preserved_attempt_count(client):
    inbox.update('same-item',status='FAILED_SOURCE',local_worker_done=True,attempts=6)
    inbox.recover_existing('same-item')
    row=rn.read()['instagram_inbox'][0]
    assert row['attempts']==6;assert row['attempt_limit']==8;assert row['status']=='RECEIVED'
    inbox.update('same-item',status='FAILED_SOURCE')
    with pytest.raises(ValueError):inbox.recover_existing('same-item')
