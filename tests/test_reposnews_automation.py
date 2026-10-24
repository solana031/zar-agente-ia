import json
from pathlib import Path
from unittest.mock import patch
import pytest
from flask import Flask
from app import reposnews as rn, reposnews_inbox as inbox, reposnews_automation as auto, reposnews_editorial as editorial


def draft():
    a={'id':'example-tool','repo':'example/tool','website':'https://example.org','category':'Tools','language':'Python','license':'MIT',
       'image_asset':'fastapi-official.png','checked_at':'2026-10-18','state':'READY_PRIVATE','published':False,'inbox_item_id':'a'*24,
       'sources':['https://example.org','https://github.com/example/tool'], 'review_kind':'AUTOMATED_SOURCE_REVIEW'}
    for language in ('es','en'):
        a.update({'title_'+language:'Example Tool','summary_'+language:'A source-verified guide','body_'+language:'verified word '*260})
    return rn.article_defaults(a)


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path));monkeypatch.setenv('INSTAGRAM_REPOSNEWS_SENDERS','sender')
    a=draft();rn.write({'owner':'owner','articles':[a],'instagram_inbox':[{'id':'a'*24,'external_id':'same-message','sender':'sender',
        'source_url':'https://www.instagram.com/reel/example/','status':'READY_PRIVATE','article_id':a['id'],'attempts':2,
        'local_worker_done':True,'research_package':{'repo':'example/tool','readme':'verified facts','metadata':{},'sources':a['sources'],'verified_at':'2026-10-18'}}],
        'legal':{'controller':'Fixture','privacy_contact':'fixture@example.test','activity_mode':'NONCOMMERCIAL','entity_type':'PERSON','processing_basis':'Fixture','retention':'Fixture','providers_reviewed':True},'legal_reviewed':True})
    app=Flask(__name__,template_folder=str(Path('app/templates').resolve()));app.secret_key='fixture-session'
    editorial.register(app,lambda:'owner');rn.register(app,lambda:'owner')
    client=app.test_client()
    with client.session_transaction() as s:s.update(zar_auth=True,business_csrf='fixture-csrf')
    return app,client


def decision(client,value='PUBLICAR',token=None):
    return client.post('/api/reposnews/editorial/decision',json={'id':'example-tool','decision':value,
        'approval_request':token or rn.state('owner')['articles'][0].get('approval_request')},headers={'X-ZAR-Business-CSRF':'fixture-csrf'})


def test_publish_endpoint_rejects_ready_and_confirmed_without_approval(setup):
    _,client=setup
    r=client.post('/api/reposnews/editorial/publish',json={'id':'example-tool','confirmed':True,'approval_status':'APPROVED_BY_USER'},headers={'X-ZAR-Business-CSRF':'fixture-csrf'})
    assert r.status_code==400;assert 'EXPLICIT_USER_APPROVAL_REQUIRED' in r.json['error']
    assert not rn.read()['articles'][0]['published']


def test_worker_bearer_cannot_approve_publication(setup):
    app,_=setup;c=app.test_client()
    r=decision(c)
    assert r.status_code==401;assert not rn.read()['articles'][0]['published']


def test_explicit_user_click_publishes_both_languages_without_second_confirmation(setup):
    _,client=setup
    with patch('app.jev_decision.proposal',return_value={'id':'fixture','decision':'ALLOW'}),patch('app.jev_decision.decision_state'):
        r=decision(client)
    assert r.status_code==200
    a=rn.read()['articles'][0];assert a['state']=='PUBLISHED';assert a['approval_status']=='APPROVED_BY_USER'
    assert a['published_snapshot']['body_es'];assert a['published_snapshot']['body_en']


def test_stale_revision_and_forged_token_are_rejected(setup):
    _,client=setup;token=rn.state('owner')['articles'][0]['approval_request']
    data=rn.read();data['articles'][0]['title_es']='Changed';rn.write(data)
    assert decision(client,token=token).status_code==400
    assert decision(client,token='forged').status_code==400
    assert not rn.read()['articles'][0]['published']


def test_notification_persists_once_and_has_required_review_fields(setup):
    auto.notify('a'*24);auto.notify('a'*24)
    note=rn.read()['editorial_notifications'][0]
    assert len(rn.read()['editorial_notifications'])==1
    for key in ('title','project','reel','image','preview_es','preview_en','sources','seo'):assert note[key]
    assert note['status']=='AWAITING_APPROVAL'
    from app import holdings
    actions=holdings.read('owner')['identity_center']['human_actions']
    assert len(actions)==1;assert actions[0]['service']=='REPOSNEWS'


def test_modify_and_cancel_preserve_history_and_revoke_approval(setup):
    _,client=setup;auto.notify('a'*24)
    assert decision(client,'MODIFICAR').status_code==200
    data=rn.read();a=data['articles'][0];assert a['state']=='MODIFYING';assert a['approval_status']=='PENDING'
    # A modification must be completed before there is a new publication request.
    rn.operate('owner','save',{'id':a['id'],'title_es':'Updated title','state':'READY_PRIVATE'})
    assert rn.read()['articles'][0]['state']=='READY_PRIVATE'
    assert decision(client,'CANCELAR').status_code==200
    data=rn.read();assert data['articles'][0]['state']=='CANCELLED';assert data['articles'][0]['history']
    assert data['instagram_inbox'][0]['status']=='CANCELLED';assert not data['articles'][0]['published']


def test_full_draft_from_persistent_checkpoint_notifies_without_codex(setup):
    data=rn.read();data['articles']=[];data['instagram_inbox'][0].update(status='RECEIVED',attempt_limit=8)
    data['instagram_inbox'][0].pop('article_id');rn.write(data)
    with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'build',return_value=draft()),patch('app.reposnews_discovery.official_image',return_value={}):
        inbox.process('a'*24)
    data=rn.read();assert data['instagram_inbox'][0]['status']=='READY_PRIVATE'
    assert data['articles'][0]['published'] is False;assert data['editorial_notifications'][0]['status']=='AWAITING_APPROVAL'


def test_provider_failure_is_retryable_and_never_creates_fake_ready_note(setup):
    data=rn.read();data['articles']=[];row=data['instagram_inbox'][0];row.update(status='RECEIVED',attempt_limit=8);row.pop('article_id');rn.write(data)
    with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'build',side_effect=ValueError('AI_PROVIDER_503')):
        inbox.process('a'*24)
    data=rn.read();assert data['articles']==[];assert data['instagram_inbox'][0]['status']=='FAILED_RETRYABLE'
    assert data['instagram_inbox'][0]['retry_after']>0;assert not data.get('editorial_notifications')


def test_modification_request_is_persistent_and_does_not_publish(setup):
    with patch.object(inbox,'start_worker'):
        editorial.modify_request('owner',{'id':'example-tool','instruction':'Hazlo más técnico y explica la instalación'})
    data=rn.read();assert data['articles'][0]['state']=='MODIFYING'
    assert data['instagram_inbox'][0]['modification_request'];assert data['instagram_inbox'][0]['status']=='RECEIVED'
    assert not data['articles'][0]['published']


def test_multiple_reel_notifications_are_not_grouped_into_one(setup):
    from app.identity_center import human_action_groups
    state={'human_actions':[{'id':str(n),'service':'REPOSNEWS','action':'ARTICLE_READY','status':'AWAITING_APPROVAL',
        'account':'Pablo','plan_id':'article:'+str(n),'reason':'Review','instructions':[]} for n in range(2)]}
    assert len(human_action_groups(state))==2
