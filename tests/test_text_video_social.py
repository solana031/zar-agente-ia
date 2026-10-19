"""Social approval and uncertain delivery: all provider calls are mocked."""
import json
from contextlib import contextmanager
from unittest.mock import Mock,patch
import pytest
from flask import Flask
from app import holdings,media_company as media,reposnews as rn,text_video as video,text_video_social as social
from app.media_adapters import PublishingAdapter


@pytest.fixture
def project(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path));rn.write({'owner':'owner','articles':[]})
    app=Flask(__name__);app.secret_key='offline-fixture-key'
    with app.test_request_context(),patch.object(video,'start_worker'),patch('app.jev_decision.proposal',return_value={'decision':'ACCEPT'}),patch.object(social.subprocess,'run',return_value=Mock(returncode=0,stdout=json.dumps({'streams':[{'codec_type':'video','codec_name':'h264','width':1080,'height':1920},{'codec_type':'audio','codec_name':'aac'}],'format':{'duration':45}}))):
        identifier=video.queue('owner',{'topic':'Guía original para revisar un vídeo privado','request_id':'social-fixture-request'})['id']
        record=video.view('owner',identifier);output=media._path('owner',identifier).with_suffix('.mp4');output.write_bytes(b'offline-exact-render')
        record.update(artifact=output.name,status='PRODUCED',video_state='READY_PRIVATE',render={'duration':45,'width':1080,'height':1920});media._save('owner',identifier,record)
        yield identifier


OPTIONS={'platforms':['instagram','tiktok','youtube'],'title':'Guía original','caption':'Revisado antes de compartir','tiktok_privacy':'SELF_ONLY','youtube_privacy':'private'}


@contextmanager
def ready_connections():
    def checks(scope,only=None):
        ig=social.social.scoped_instagram_readiness(scope)
        return {'instagram':dict(ig,status='CONNECTED',ready=ig.get('publish_capability')=='AUTHORIZED_NOT_TESTED'),
                'tiktok':dict(social.social.publishing_readiness('tiktok'),status='CONNECTED',ready=True),
                'youtube':{'status':'CONNECTED','ready':True,'channel':{'id':'fixture-yt'}}}
    with patch.object(social,'connections',side_effect=checks),patch.object(social.social,'scoped_instagram_readiness',return_value={'publish_capability':'AUTHORIZED_NOT_TESTED','account':'zaragente031','account_id':'123'}),patch.object(social.social,'publishing_readiness',return_value={'connected':True,'account':'Fixture TikTok','account_id':'fixture-tt','privacy_options':['SELF_ONLY'],'max_video_post_duration_sec':60}),patch.object(PublishingAdapter,'prepare_youtube',return_value={'upload_capability':True,'channel':{'id':'fixture-yt'}}),patch.object(social.social,'instagram_context',return_value={'user':'123','token':'fixture-only','base':'https://graph.instagram.com/v26.0'}):
        yield


def approve(identifier):
    plan=social.prepared('owner',identifier,OPTIONS)
    return social.confirm('owner',identifier,{'approval_request':plan['approval_request'],'confirmed':True,'rights_confirmed':True})


def test_dry_run_checks_all_targets_without_upload(project):
    with ready_connections(),patch.object(social.social,'instagram_reel') as ig,patch.object(social.social,'tiktok_direct_post') as tt,patch.object(PublishingAdapter,'youtube') as yt:
        plan=social.prepared('owner',project,OPTIONS)
    assert plan['dry_run'] and plan['ready_to_publish'];assert plan['checks']['youtube']['privacy']=='private'
    assert video.view('owner',project)['publication']=={}
    ig.assert_not_called();tt.assert_not_called();yt.assert_not_called()


def test_legacy_publisher_cannot_bypass_exact_render_approval(project):
    with patch.object(social.social,'instagram_reel') as provider:
        with pytest.raises(ValueError,match='confirmación del proyecto'):media.publish('owner',project,'https://fixture.test/video.mp4','instagram',confirmed=True)
    provider.assert_not_called()


def test_dm_connection_is_not_publication_permission(project):
    with ready_connections(),patch.object(social.social,'scoped_instagram_readiness',return_value={'publish_capability':'BLOCKED','account':'fixture-ig','blocker':'MISSING_OR_UNVERIFIED_INSTAGRAM_BUSINESS_CONTENT_PUBLISH'}):
        plan=social.prepared('owner',project,OPTIONS)
        assert not plan['ready_to_publish']
        with pytest.raises(ValueError,match='DRY_RUN_NOT_READY'):social.confirm('owner',project,{'approval_request':plan['approval_request'],'confirmed':True,'rights_confirmed':True})
    assert video.view('owner',project)['publication']=={}


def test_one_confirmation_queues_all_and_is_idempotent_without_capability_leak(project):
    with ready_connections(),patch.object(social.social,'instagram_reel') as provider:
        plan=social.prepared('owner',project,OPTIONS);request={'approval_request':plan['approval_request'],'confirmed':True,'rights_confirmed':True}
        first=social.confirm('owner',project,request);second=social.confirm('owner',project,request)
    assert first==second and len(first)==3;assert {v['status'] for v in first.values()}=={'QUEUED'}
    assert 'media-public' not in json.dumps(first) and 'options' not in json.dumps(first)
    posts=video.view('owner',project)['publication'];assert len({p['idempotency_key'] for p in posts.values()})==3
    assert all(p['video_digest']==plan['video_digest'] for p in posts.values());provider.assert_not_called()


@pytest.mark.parametrize('change',['digest','revision','stop','signature','rights'])
def test_exact_render_scope_signature_and_rights_gate(project,change):
    with ready_connections():plan=social.prepared('owner',project,OPTIONS)
    data={'approval_request':plan['approval_request'],'confirmed':True,'rights_confirmed':True}
    if change=='digest':media.video_path('owner',project).write_bytes(b'changed-after-review')
    if change=='revision':
        record=video.view('owner',project);record['video_revision']=1;media._save('owner',project,record)
    if change=='stop':
        state=holdings.read('owner');state['global_stop']=True;holdings.write('owner',state)
    if change=='signature':data['approval_request']='invalid-signature'
    if change=='rights':data['rights_confirmed']=False
    with pytest.raises(ValueError):social.confirm('owner',project,data)
    assert video.view('owner',project)['publication']=={}


def test_account_changed_blocks_before_any_external_write(project):
    with ready_connections():approve(project)
    record=video.view('owner',project)
    with patch.object(social.social,'instagram_context',return_value={'user':'another-account'}),patch.object(social.social,'instagram_reel') as provider,patch.object(social,'notify'):
        social.advance('owner',media._task('owner',project),record)
    assert record['publication']['instagram']['status']=='BLOCKED';provider.assert_not_called()


def test_timeout_never_repeats_submission(project):
    with ready_connections():approve(project)
    record=video.view('owner',project);record['publication']={'instagram':record['publication']['instagram']}
    with ready_connections(),patch.object(social.social,'instagram_reel',side_effect=TimeoutError) as provider,patch.object(social,'notify'):
        social.advance('owner',media._task('owner',project),record);social.advance('owner',media._task('owner',project),record)
    assert record['publication']['instagram']['status']=='UNKNOWN';assert provider.call_count==1


def test_crash_after_persisted_intent_never_reuploads(project):
    with ready_connections():approve(project)
    record=video.view('owner',project);post=record['publication']['instagram'];post['status']='REQUESTED';record['publication']={'instagram':post}
    with patch.object(social.social,'instagram_reel') as provider,patch.object(social,'notify'):social.advance('owner',media._task('owner',project),record)
    assert post['status']=='UNKNOWN';provider.assert_not_called()


def test_known_instagram_id_survives_permalink_failure(project):
    with ready_connections():approve(project)
    record=video.view('owner',project);record['publication']={'instagram':record['publication']['instagram']}
    with ready_connections(),patch.object(social.social,'instagram_reel',return_value={'id':'987'}),patch.object(social.social,'instagram_permalink',side_effect=TimeoutError),patch.object(social,'notify'):
        social.advance('owner',media._task('owner',project),record)
    post=record['publication']['instagram'];assert post['status']=='PUBLISHED' and post['external_id']=='987'


def test_transient_pending_status_read_does_not_repost(project):
    record=video.view('owner',project);post={'platform':'tiktok','status':'PENDING','publish_id':'tracking-fixture'};record['publication']={'tiktok':post}
    with patch.object(social.requests,'post',side_effect=TimeoutError) as provider:
        social.advance('owner',media._task('owner',project),record)
    assert post['status']=='PENDING' and post['read_errors']==1;assert provider.call_count==1


def test_instagram_pending_cancel_avoids_commit(project):
    record=video.view('owner',project);post={'platform':'instagram','status':'PENDING','container_id':'container-fixture','cancel_requested':True}
    with ready_connections(),patch.object(social.requests,'get',return_value=Mock(ok=True,json=lambda:{'status_code':'FINISHED'})),patch.object(social.requests,'post') as write:
        social.poll('owner',media._task('owner',project),record,post)
    assert post['status']=='CANCELLED';write.assert_not_called()


def test_instagram_pending_commit_persists_intent_before_write(project):
    with ready_connections():approve(project)
    record=video.view('owner',project);post=record['publication']['instagram'];post.update(status='PENDING',container_id='container-fixture');record['publication']={'instagram':post}
    def accepted(*args,**kwargs):
        assert video.view('owner',project)['publication']['instagram']['commit_intent'] is True
        return Mock(ok=True,json=lambda:{'id':'987'})
    with ready_connections(),patch.object(social.requests,'get',side_effect=[Mock(ok=True,json=lambda:{'status_code':'FINISHED'}),Mock(ok=True,json=lambda:{'permalink':'https://www.instagram.com/reel/fixture/'})]),patch.object(social.requests,'post',side_effect=accepted) as write:
        social.poll('owner',media._task('owner',project),record,post)
    assert post['status']=='PUBLISHED' and post['external_id']=='987';assert write.call_count==1


def test_tiktok_confirmed_processing_tracks_public_result(project):
    post={'platform':'tiktok','status':'PENDING','publish_id':'tracking-fixture','account':'fixture-tt'}
    with patch.object(social.requests,'post',return_value=Mock(ok=True,json=lambda:{'data':{'status':'PUBLISH_COMPLETE','publicaly_available_post_id':['1234']}})):
        social.poll('owner',media._task('owner',project),{},post)
    assert post['status']=='PUBLISHED' and post['external_id']=='1234';assert post['url']=='https://www.tiktok.com/@fixture-tt/video/1234'


@pytest.mark.parametrize('privacy,expected',[('private','UPLOADED_PRIVATE'),('unlisted','UPLOADED_UNLISTED'),('public','PUBLISHED'),(None,'PENDING')])
def test_youtube_status_uses_actual_privacy(project,privacy,expected):
    service=Mock();service.videos.return_value.list.return_value.execute.return_value={'items':[{'status':{'uploadStatus':'processed','privacyStatus':privacy}}]}
    post={'platform':'youtube','status':'PENDING','external_id':'youtube-fixture'}
    with patch('app.youtube._service',return_value=service):social.poll('owner',media._task('owner',project),{},post)
    assert post['status']==expected


def test_existing_instagram_vault_identity_and_publish_permission_checked_separately(project):
    credentials={'access_token':'offline-fixture-token','user_id':'123','username':'zaragente031','requested_permissions':['instagram_business_basic','instagram_business_manage_messages']}
    with patch('app.reposnews_inbox.credentials',return_value=credentials),patch.object(social.social.requests,'get',side_effect=[Mock(ok=True,json=lambda:{'user_id':'123','username':'zaragente031'}),Mock(ok=False,status_code=400)]) as read:
        result=social.social.scoped_instagram_readiness('owner')
    assert result['connected'] and result['publish_capability']=='BLOCKED';assert 'CONTENT_PUBLISH' in result['blocker']
    assert all(call.args[0].startswith('https://graph.instagram.com/') for call in read.call_args_list)
    assert all('access_token' not in call.kwargs.get('params',{}) for call in read.call_args_list)


@pytest.mark.parametrize('subcode,cause',[(None,'PROVIDER_AUTH_ERROR_UNCLASSIFIED'),(463,'EXPIRED_TOKEN'),(467,'INVALID_TOKEN')])
def test_instagram_401_does_not_invent_expiry(project,subcode,cause):
    response=Mock(ok=False,status_code=401,json=lambda:{'error':{'code':190,'error_subcode':subcode,'message':'offline-token-fixture','type':'OAuthException'}})
    with patch.object(social.social,'instagram_context',return_value={'user':'123','token':'offline-token-fixture','base':'https://graph.instagram.com/v26.0'}),patch.object(social.social.requests,'get',return_value=response):
        result=social.social.scoped_instagram_readiness('owner')
    assert result['status']=='REAUTH_REQUIRED' and result['verified_cause']==cause
    assert 'offline-token-fixture' not in json.dumps(result)


def test_instagram_personal_identity_blocked(project):
    with patch.object(social.social,'instagram_context',return_value={'user':'123','token':'fixture','base':'https://graph.instagram.com/v26.0'}),patch.object(social.social.requests,'get',return_value=Mock(ok=True,json=lambda:{'user_id':'123','username':'personal'})):
        assert social.social.scoped_instagram_readiness('owner')['blocker']=='INSTAGRAM_IDENTITY_MISMATCH'


def test_three_real_connection_states_are_not_inferred_from_config(project,monkeypatch):
    monkeypatch.delenv('TIKTOK_ACCESS_TOKEN',raising=False)
    with patch('app.cloud_auth.get_credentials',return_value=None),patch.object(social.social,'scoped_instagram_readiness',return_value={'status':'REAUTH_REQUIRED','publish_capability':'BLOCKED','blocker':'INSTAGRAM_IDENTITY_HTTP_401'}):
        result=social.connections('owner')
    assert [result[p]['status'] for p in ['instagram','tiktok','youtube']]==['REAUTH_REQUIRED','DISCONNECTED','AUTH_REQUIRED']
    assert all(not c['ready'] for c in result.values())


@pytest.mark.parametrize('code,status',[('scope_not_authorized','PERMISSION_REQUIRED'),('access_token_invalid','REAUTH_REQUIRED')])
def test_tiktok_provider_auth_status_is_explicit(project,monkeypatch,code,status):
    monkeypatch.setenv('TIKTOK_ACCESS_TOKEN','offline-fixture-only')
    with patch.object(social.social.requests,'post',return_value=Mock(ok=False,status_code=401,json=lambda:{'error':{'code':code}})) as request:
        result=social.social.publishing_readiness('tiktok')
    assert result['status']==status and not result['connected']
    assert request.call_args.args[0].endswith('/creator_info/query/')


def test_youtube_channel_is_real_and_wrong_google_identity_blocked(project):
    from app import cloud_auth,identity_center
    creds=Mock(scopes=[identity_center.PREFIX+'youtube.readonly',identity_center.PREFIX+'youtube.upload'],token='offline')
    response=Mock(ok=True,json=lambda:{'items':[{'id':'actual-fixture-channel','snippet':{'title':'Operational fixture channel'}}]})
    with patch.object(cloud_auth,'get_credentials',return_value=creds),patch.object(cloud_auth,'get_account_email',return_value=social.OPERATIONAL_EMAIL),patch.object(social.requests,'get',return_value=response) as read:
        result=social.connections('owner',['youtube'])['youtube']
    assert result['ready'] and result['channel']=={'id':'actual-fixture-channel','title':'Operational fixture channel','handle':None}
    assert read.call_args.kwargs['params']['mine']=='true'
    with patch.object(cloud_auth,'get_credentials',return_value=creds),patch.object(cloud_auth,'get_account_email',return_value='personal@example.invalid'),patch.object(social.requests,'get') as read:
        result=social.connections('owner',['youtube'])['youtube']
    assert result['status']=='ERROR' and not result['ready'];read.assert_not_called()


def test_metadata_change_invalidates_older_approval_request(project):
    with ready_connections():
        old=social.prepared('owner',project,OPTIONS)
        social.prepared('owner',project,OPTIONS | {'caption':'Changed after review'})
        with pytest.raises(ValueError,match='METADATA_CHANGED'):
            social.confirm('owner',project,{'approval_request':old['approval_request'],'confirmed':True,'rights_confirmed':True})


def test_queued_record_without_user_approval_cannot_call_adapter(project):
    with ready_connections():approve(project)
    record=video.view('owner',project);record['social_approvals']=[]
    with patch.object(social.social,'instagram_reel') as upload,patch.object(social,'notify'):
        social.advance('owner',media._task('owner',project),record)
    assert record['publication']['instagram']['status']=='BLOCKED';upload.assert_not_called()


def test_partial_success_retries_only_confirmed_failed_target(project):
    with ready_connections():approve(project)
    record=video.view('owner',project)
    record['publication']['instagram'].update(status='PUBLISHED',external_id='ig-existing',url='https://www.instagram.com/reel/existing/')
    record['publication']['youtube'].update(status='UPLOADED_PRIVATE',external_id='yt-existing')
    record['publication']['tiktok'].update(status='FAILED',error='TIKTOK_PROVIDER_REPORTED_FAILURE')
    media._save('owner',project,record)
    with ready_connections():
        plan=social.prepared('owner',project,OPTIONS | {'platforms':['tiktok']})
        social.confirm('owner',project,{'approval_request':plan['approval_request'],'confirmed':True,'rights_confirmed':True})
    posts=video.view('owner',project)['publication']
    assert posts['instagram']['external_id']=='ig-existing' and posts['youtube']['external_id']=='yt-existing'
    assert posts['tiktok']['status']=='QUEUED' and posts['tiktok']['approval_id']!=posts['instagram']['approval_id']


def test_file_validation_rejects_missing_and_classifies_transcode(project,tmp_path):
    with pytest.raises(ValueError,match='FILE_REQUIRED'):social.validate_video(tmp_path/'absent.mp4')
    response=Mock(returncode=0,stdout=json.dumps({'streams':[{'codec_type':'video','codec_name':'vp9','width':720,'height':1280}],'format':{'duration':45}}))
    with patch.object(social.subprocess,'run',return_value=response):
        result=social.validate_video(media.video_path('owner',project))
    assert set(result['platforms'].values())=={'NEEDS_TRANSCODE'}
