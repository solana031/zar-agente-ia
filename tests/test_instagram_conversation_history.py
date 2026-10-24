"""Official history pagination, privacy, deduplication and durable checkpoints."""
from unittest.mock import Mock,patch
import pytest
from app import reposnews as rn,reposnews_inbox as inbox,instagram_conversation_history as history

@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(inbox,'credentials',lambda:{'access_token':'fixture-canonical','user_id':'account'})
    monkeypatch.setattr(inbox,'sender_ids',lambda:{'authorized'})
    rn.write({'owner':'owner','articles':[],'instagram_inbox':[]})

def message(mid,reel=None,sender='authorized'):
    return {'id':mid,'created_time':'2026-10-24T12:00:00+0000','from':{'id':sender},
            'message':'Reel evidence' if reel else 'unrelated private text MUST NOT persist',
            **({'shares':{'data':[{'link':'https://www.instagram.com/reel/'+reel+'/'}]}} if reel else {})}

def conversation():
    return {'data':[{'id':'conversation','participants':{'data':[{'id':'authorized','username':'solana031'}]}}]}

def page(rows,after=None):
    return {'data':rows,**({'paging':{'cursors':{'after':after},'next':'https://graph.instagram.com/ignored?after='+after+'&access_token=never-follow'}} if after else {})}

def test_all_pages_and_incremental_cursor_without_private_messages_or_duplicate_jobs(store):
    pages=[page([message('m'+str(i),'r'+str(i)) for i in range(n,n+25)],'p'+str(n+25) if n<50 else None) for n in (0,25,50)]
    pages[-1]['data'] += [message('repeat','r0'),message('private'),message('other','unrelated','stranger')]
    with patch.object(history,'_read',side_effect=[conversation()]+pages) as read:
        result=history.sync('owner',force=True)
    assert result['history_exhausted'] and result['reels_found']==75
    assert result['messages_scanned']==78
    assert len(rn.read()['instagram_inbox'])==75
    assert len(rn.read()['instagram_conversation_reel_index'])==76
    assert rn.read()['owner']=='owner'
    assert read.call_count==4
    assert read.call_args_list[0].args[2]['user_id']=='authorized'
    assert read.call_args_list[2].args[2]['after']=='p25'
    assert 'unrelated private text' not in str(rn.read())
    with patch.object(history,'_read') as read:history.sync('owner')
    read.assert_not_called()
    with patch.object(history,'_read',side_effect=[conversation(),page([message('new','new'),message('m0','r0'),message('older','must-not-rescan')],'unused')]) as read:
        result=history.sync('owner',force=True)
    assert result['reels_found']==76 and read.call_count==2
    checkpoint=rn.read()['instagram_conversation_sync']['checkpoints']['conversation']
    assert checkpoint['last_message_id']=='new' and checkpoint['history_exhausted']
    with patch.object(history,'_read',side_effect=[conversation(),page([message('new','new')])]):history.sync('owner',force=True)
    assert rn.read()['instagram_conversation_sync']['checkpoints']['conversation']['last_message_id']=='new'

def test_checkpoint_resumes_after_rate_limit_and_preserves_previous_associations(store):
    data=rn.read();data['instagram_inbox']=[{'id':'existing','external_id':'legacy','sender':'authorized','source_url':'https://www.instagram.com/reel/known/','status':'NO_CHANGE','article_id':'article'}];rn.write(data)
    with patch.object(history,'_read',side_effect=[conversation(),page([message('m1','known')],'resume'),ValueError('META_HISTORY_RETRYABLE_HTTP_429')]):
        result=history.sync('owner',force=True)
    assert result['error']=='META_HISTORY_RETRYABLE_HTTP_429'
    assert rn.read()['instagram_conversation_sync']['checkpoints']['conversation']['pagination_cursor']=='resume'
    with patch.object(history,'_read',side_effect=[conversation(),page([message('m2','new')])]) as read:
        result=history.sync('owner',force=True)
    assert result['history_exhausted'] and result['previously_known']==1
    assert read.call_args_list[1].args[2]['after']=='resume'
    existing=next(r for r in rn.read()['instagram_inbox'] if r['id']=='existing')
    assert existing['status']=='NO_CHANGE' and existing['article_id']=='article'

def test_unverified_sender_conversation_is_never_read(store):
    with patch.object(history,'_read',return_value={'data':[{'id':'wrong','participants':{'data':[{'id':'authorized','username':'someone_else'}]}}]}) as read:
        result=history.sync('owner',force=True)
    assert not result['conversation_found'] and read.call_count==1
    assert not rn.read()['instagram_inbox']

def test_share_edge_pagination_and_token_never_forwarded_to_next_host(store):
    msg=message('m','one');msg['shares']['paging']={'next':'https://evil.invalid/leak','cursors':{'after':'safe-cursor'}}
    with patch.object(history,'_read',return_value=page([{'link':'https://www.instagram.com/reel/two/'}])) as read:
        urls=history._reels(msg,'fixture')
    assert len(urls)==2
    assert read.call_args.args[0]=='m/shares'
    assert read.call_args.args[2]['after']=='safe-cursor'
    with patch.object(history.requests,'get',return_value=Mock(ok=True,json=lambda:page([]))) as get:
        history._read('m/shares','fixture',{'after':'safe-cursor'})
    assert get.call_args.args[0]=='https://graph.instagram.com/v26.0/m/shares'
    assert get.call_args.kwargs['allow_redirects'] is False

def test_one_summary_when_existing_pipeline_finishes(store):
    with patch.object(history,'_read',side_effect=[conversation(),page([message('m','one')])]):history.sync('owner',force=True)
    data=rn.read();data['instagram_inbox'][0]['status']='NO_CHANGE';rn.write(data)
    with patch('app.notification_center.emit') as notify:
        history.tick();history.tick()
    assert notify.call_args.args[1]=='INSTAGRAM_HISTORY_SYNC'
    assert notify.call_args_list[0].args[2]==notify.call_args_list[1].args[2]
    assert history.summary(rn.read())['no_change']==1

def test_owner_and_cursor_guard(store):
    with pytest.raises(ValueError):history.sync('other',force=True)
    with patch.object(history,'_read',return_value=page([],'same')):
        with pytest.raises(ValueError,match='PAGINATION_STALLED'):list(history._pages('conversation/messages','fixture',{}))

def test_official_video_refs_precede_browser_and_are_never_stored_in_metadata(store):
    msg=message('media','video');msg['attachments']={'data':[{'video_data':{'url':'https://cdn.example.fbcdn.net/video.mp4?signature=private'}}]}
    with patch.object(history,'_read',side_effect=[conversation(),page([msg])]):history.sync('owner',force=True)
    row=rn.read()['instagram_inbox'][0]
    assert row['official_media_available']
    assert 'signature=private' not in str(rn.read())
    assert (rn._path().parent/'inbound'/row['id']).exists()
    from app import instagram_local_queue
    data=rn.read();instagram_local_queue.enqueue_pending(data)
    assert data['instagram_inbox'][0]['status']=='RECEIVED'

def test_summary_counts_exhausted_retries_without_claiming_success(store):
    with patch.object(history,'_read',side_effect=[conversation(),page([message('m','one')])]):history.sync('owner',force=True)
    data=rn.read();data['instagram_inbox'][0].update(status='FAILED_RETRYABLE',attempts=8,attempt_limit=8);history.refresh(data)
    result=history.summary(data)
    assert result['failed']==1 and result['pending']==0 and result['new_drafts']==0

def test_sync_endpoint_requires_owner_csrf_and_only_queues_work(store):
    from flask import Flask,request,abort
    app=Flask(__name__)
    def csrf():
        if request.headers.get('X-ZAR-Business-CSRF')!='fixture':abort(403)
        return 'owner'
    history.register(app,lambda:'owner',csrf)
    with patch.object(history.requests,'get') as read:
        assert app.test_client().post('/api/reposnews/history/sync').status_code==403
        assert app.test_client().post('/api/reposnews/history/sync',headers={'X-ZAR-Business-CSRF':'fixture'}).status_code==200
    read.assert_not_called()
    assert rn.read()['instagram_conversation_sync']['requested'] is True

def test_existing_entity_routes_to_no_change_without_duplicate_or_publication(store):
    from app import reposnews_revisions as revisions
    article={'id':'existing','repo':'vendor/tool','repository_url':'https://github.com/vendor/tool','website':'https://tool.example','published':True,'source_reels':['https://www.instagram.com/reel/original/'],'assets':[]}
    data=rn.read();data['articles']=[article]
    row={'id':'item','source_url':'https://www.instagram.com/reel/new/'}
    candidate=dict(article,id='different-title',title_es='Different title',aliases=['Tool'])
    with patch('app.reposnews_generation.generate_json',return_value={'relevant':False}):
        assert revisions.consider(data,row,candidate)
    assert row['status']=='NO_CHANGE' and row['linked_article_id']=='existing'
    assert len(data['articles'])==1 and data['articles'][0]==article

def test_meta_rate_limit_403_code4_is_retryable_and_secret_free(store):
    response=Mock(ok=False,status_code=403,headers={'Retry-After':'1200'},json=lambda:{'error':{'code':4,'error_subcode':1349210,'message':'Application request limit reached fixture-canonical','type':'OAuthException'}})
    with patch.object(history.requests,'get',return_value=response):
        with pytest.raises(history.HistoryReadError) as failure:history._read('conversation/messages','fixture-canonical',{})
    assert str(failure.value)=='META_HISTORY_RATE_LIMITED' and failure.value.retry_after==1200
    assert failure.value.detail['code']==4 and failure.value.detail['subcode']==1349210
    assert 'fixture-canonical' not in str(failure.value.detail)

def test_primary_reels_checkpoint_before_secondary_rate_limit_and_resume_without_full_rescan(store):
    first=message('newest','one');first['shares']['paging']={'cursors':{'after':'share2'},'next':'https://graph.instagram.com/newest/shares'}
    rate=history.HistoryReadError('META_HISTORY_RATE_LIMITED',{'http':403,'code':4,'subcode':1349210},3600)
    with patch.object(history.time,'time',return_value=1000),patch.object(history,'_read',side_effect=[conversation(),page([first],'older'),page([message('older','two')]),rate]):
        result=history.sync('owner',force=True)
    assert result['status']=='RATE_LIMITED' and result['reels_found']==2
    assert result['share_pages_pending']==1 and result['retry_after']==4600
    checkpoint=rn.read()['instagram_conversation_sync']['checkpoints']['conversation']
    assert checkpoint['history_exhausted'] and checkpoint['last_message_id']=='newest'
    with patch.object(history.time,'time',return_value=2000),patch.object(history,'_read') as read:
        history.sync('owner',force=True)
    read.assert_not_called()  # Even a manual button cannot bypass provider backoff.
    with patch.object(history.time,'time',return_value=4601),patch.object(history,'_read',side_effect=[conversation(),page([first]),page([{'link':'https://www.instagram.com/reel/three/'}])]) as read:
        result=history.sync('owner')
    assert result['history_exhausted'] and result['reels_found']==3 and result['share_pages_pending']==0
    assert read.call_count==3 and read.call_args_list[-1].args[0]=='newest/shares'
    assert read.call_args_list[-1].args[2]['after']=='share2'
