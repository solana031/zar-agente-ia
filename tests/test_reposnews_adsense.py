"""Offline AdSense preparation: no account creation, ads, submissions or real PII."""
import json,re
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from flask import Flask,session
from app import reposnews as rn,reposnews_adsense as ads,holdings,identity_center

@pytest.fixture
def site(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path))
    source=json.loads(Path('app/reposnews_content.json').read_text(encoding='utf-8'))
    articles=[rn.article_defaults(a) for a in source[:3]]
    articles[0]['published']=True;articles[0]['published_at']='2026-10-20T10:00:00Z'
    data={'owner':'owner','articles':articles,'domain_status':'ACTIVE','publisher':'pub-0000000000000001',
        'legal':{'controller':'Fixture owner','privacy_contact':'fixture@example.test','activity_mode':'NONCOMMERCIAL','entity_type':'PERSON',
                 'processing_basis':'Fixture basis','retention':'Fixture retention','providers_reviewed':True},'legal_reviewed':True}
    rn.write(data)
    app=Flask(__name__,template_folder=str(Path('app/templates').resolve()));app.secret_key='offline-fixture'
    app.before_request(rn.public_dispatch);rn.register(app,lambda:'owner')
    return app,app.test_client(),data

def get(site,path):return site[1].get(path,base_url=rn.ORIGIN)

def test_ads_txt_only_current_valid_authorized_publisher(site):
    r=get(site,'/ads.txt');assert r.status_code==200
    assert r.text=='google.com, pub-0000000000000001, DIRECT, f08c47fec0942fa0\n'
    d=rn.read();d['publisher']='not-a-publisher';rn.write(d)
    assert get(site,'/ads.txt').status_code==404
    assert 'pub-' not in get(site,'/ads.txt').text

@pytest.mark.parametrize('path',['/es/','/en/','/es/about/','/en/privacy/','/es/cookies/','/es/repositorios/uv/'])
def test_prepared_head_code_and_nonce_do_not_enable_ads(site,path):
    r=get(site,path);assert r.status_code==200
    head=r.text.split('</head>')[0]
    assert head.count('name="google-adsense-account"')==1 and head.count('adsbygoogle.js?client=ca-pub-0000000000000001')==1
    assert re.search(r'<script[^>]*type="text/plain"[^>]*src="https://pagead2',head)
    assert "ad_storage:'denied'" in head and "ad_user_data:'denied'" in head and "ad_personalization:'denied'" in head
    nonce=re.search(r"'nonce-([^']+)'",r.headers['Content-Security-Policy']).group(1)
    assert all('nonce="'+nonce+'"' in tag for tag in re.findall(r'<script\b[^>]*>',r.text))
    assert "'strict-dynamic'" in r.headers['Content-Security-Policy']
    assert 'adsbygoogle.push' not in r.text and '<ins ' not in r.text
    assert nonce not in get(site,path).headers['Content-Security-Policy']

def test_verification_requires_known_publisher_and_never_appears_in_preview(site):
    r=site[1].get('/reposnews-preview/es/')
    assert r.status_code==200 and r.headers['X-Robots-Tag']=='noindex, nofollow'
    assert 'google-adsense-account' not in r.text and 'adsbygoogle.js' not in r.text
    d=rn.read();d.pop('publisher');rn.write(d)
    assert 'google-adsense-account' not in get(site,'/es/').text

def test_robots_sitemap_and_utility_indexing_preserve_public_private_boundary(site):
    robots=get(site,'/robots.txt').text
    assert 'Allow: /' in robots and 'Disallow: /reposnews-preview/' in robots
    assert 'Disallow: /api/' in robots and 'Disallow: /mirror/' in robots
    sitemap=get(site,'/sitemap.xml').text
    assert '/es/repositorios/uv/' in sitemap
    assert '/trends/' not in sitemap and 'reposnews-preview' not in sitemap
    for a in site[2]['articles'][1:]:assert '/'+a['id']+'/' not in sitemap
    for path in ('/es/trends/','/es/?q=tool','/es/?category=Tools'):
        assert 'content="noindex,follow"' in get(site,path).text
    assert 'content="index,follow"' in get(site,'/es/').text
    assert get(site,'/reposnews-preview/es/').status_code==404
    assert get(site,'/api/notifications').status_code==404

@pytest.mark.parametrize('lang',['es','en'])
def test_legal_pages_disclose_google_and_keep_real_privacy_options(site,lang):
    privacy=get(site,'/'+lang+'/privacy/').text;cookies=get(site,'/'+lang+'/cookies/').text
    assert 'Google AdSense' in privacy and 'myadcenter.google.com' in privacy
    assert 'policies.google.com/technologies/partner-sites' in privacy
    assert 'id="options"' in cookies and 'CMP' in cookies and 'AdSense' in cookies
    assert 'Fixture owner' in privacy and 'fixture@example.test' not in privacy
    assert 'Google AdSense' not in get(site,'/'+lang+'/about/').text

def test_readiness_requires_current_audit_and_human_data_review(site):
    assert ads.view('other')['status']=='UNKNOWN'
    r=ads.view('owner');assert r['checklist']['SITE LIVE']=='UNKNOWN' and not r['ready_for_resubmission']
    ads.record_public_audit('owner',{k:'READY' for k in ads.LABELS},{'checked_urls':155,'secret':'not-kept'})
    r=ads.view('owner');assert r['audit_current'] and r['checklist']['SITE LIVE']=='READY'
    assert r['checklist']['CMP']=='ACTION_REQUIRED' and r['checklist']['ACCOUNT INFO']=='ACTION_REQUIRED'
    stored=holdings.read('owner')['reposnews_adsense'];assert 'secret' not in stored['site_audit']['summary']
    actions=identity_center.ensure(holdings.read('owner'))['human_actions']
    assert sum(x.get('notification_key')=='reposnews-adsense-account-information' for x in actions)==1
    ads.ensure_actions('owner')
    assert len(identity_center.ensure(holdings.read('owner'))['human_actions'])==len(actions)
    d=rn.read();d['articles'][0]['body_es']+=' Changed public content';rn.write(d)
    assert not ads.view('owner')['audit_current']

def test_stale_audit_is_unknown(site):
    ads.record_public_audit('owner',{'CONTENT':'READY'},{})
    d=holdings.read('owner');d['reposnews_adsense']['site_audit']['checked_at']=(datetime.now(timezone.utc)-timedelta(days=4)).isoformat();holdings.write('owner',d)
    assert ads.view('owner')['checklist']['CONTENT']=='UNKNOWN'

def test_account_attestation_accepts_only_owner_booleans_and_does_not_submit(site):
    payload={'checks':{k:True for k in ads.ACCOUNT_FIELDS},'confirmed':True}
    with site[0].test_request_context():
        with pytest.raises(ValueError,match='AUTHENTICATED'):ads.confirm_account_review('owner',payload)
        session['zar_auth']=True
        with pytest.raises(ValueError,match='PERSONAL'):ads.confirm_account_review('owner',{**payload,'address':'private'})
        with pytest.raises(ValueError):ads.confirm_account_review('owner',{'checks':{},'confirmed':True})
        result=ads.confirm_account_review('owner',payload)
    assert result['checklist']['ACCOUNT INFO']=='READY' and result['checklist']['TAX INFO']=='READY'
    assert result['submission']=='NOT_RESUBMITTED' and not result['ready_for_resubmission']
    assert set(holdings.read('owner')['reposnews_adsense']['account_review'])=={'checks','completed_by','completed_at','source'}


def test_public_frame_rights_boundary_preserves_snapshot_and_private_asset(site):
    from copy import deepcopy
    from unittest.mock import patch
    d=rn.read();a=d['articles'][0];name='source-'+'a'*24+'.png'
    asset={'asset':name,'url':'/media/reposnews/'+name,'kind':'REEL_FRAME','source_type':'REEL_FRAME',
           'permission':'REVIEW_REQUIRED','role':'ARTICLE_USAGE','source_url':'https://www.instagram.com/reel/fixture/'}
    a.update(image_kind='REEL_FRAME',image_asset=name,cover_url=asset['url'],cover_thumb=asset['url'],assets=[asset])
    a['published_snapshot']=deepcopy(a);before=deepcopy(a['published_snapshot']);rn.write(d)
    path=rn._path().parent/'media'/name;path.parent.mkdir(exist_ok=True);path.write_bytes(b'private-frame')
    page=get(site,'/es/repositorios/uv/')
    assert name not in page.text and '/media/reposnews/editorial-uv.png' in page.text
    assert 'ilustración editorial propia' in page.text
    assert get(site,'/media/reposnews/'+name).status_code==404
    image=get(site,'/media/reposnews/editorial-uv.png')
    assert image.status_code==200 and image.data.startswith(b'\x89PNG')
    assert rn.read()['articles'][0]['published_snapshot']==before
    with patch('app.user_scope.get_current_user',return_value='owner'):
        assert site[1].get('/media/reposnews/'+name).data==b'private-frame'
    assert get(site,'/media/reposnews/editorial-private-draft.png').status_code==404


def test_explicitly_cleared_frame_is_retained(site):
    from app.reposnews_assets import public_article
    a=site[2]['articles'][0];a.update(image_kind='REEL_FRAME',image_asset='source-licensed.png',
        cover_provenance={'permission':'LICENSE_VERIFIED'},assets=[{'kind':'REEL_FRAME','permission':'RIGHTS_CLEARED','role':'ARTICLE_USAGE'}])
    safe=public_article(a)
    assert safe['image_asset']==a['image_asset'] and safe['assets']==a['assets']


def test_required_public_legal_review_blocks_readiness(site):
    result=ads.record_public_audit('owner',{k:'READY' for k in ads.LABELS},{'privacy_legal_review_required':True})
    assert result['checklist']['PRIVACY']=='ACTION_REQUIRED'
    actions=identity_center.ensure(holdings.read('owner'))['human_actions']
    assert any(x.get('notification_key')=='reposnews-adsense-public-legal-review' for x in actions)


def test_existing_workflow_endpoint_keeps_csrf_auth_and_owner_gates(site):
    from app import business_workflows
    business_workflows.register(site[0],lambda:'owner')
    payload={'checks':{k:True for k in ads.ACCOUNT_FIELDS},'confirmed':True}
    endpoint='/api/holdings/workflows/adsense_account_review'
    assert site[1].post(endpoint,json=payload).status_code==403
    with site[1].session_transaction() as s:s['business_csrf']='fixture-csrf'
    headers={'X-ZAR-Business-CSRF':'fixture-csrf'}
    assert site[1].post(endpoint,json=payload,headers=headers).json['error']=='AUTHENTICATED_OWNER_CONFIRMATION_REQUIRED'
    with site[1].session_transaction() as s:s['zar_auth']=True
    response=site[1].post(endpoint,json=payload,headers=headers)
    assert response.status_code==200 and response.json['result']['submission']=='NOT_RESUBMITTED'
    assert rn.read()['legal']==site[2]['legal']
    assert site[1].post(endpoint,json=payload,headers=headers,base_url=rn.ORIGIN).status_code==404
