"""Offline regressions for the requested historical recovery scope."""
import io
import random
import time
from copy import deepcopy
from unittest.mock import patch
import pytest
from PIL import Image
from app import reposnews as rn,instagram_conversation_history as h,reposnews_inbox as inbox
from app import reposnews_identification as identity,reposnews_ambiguity as ambiguity,reposnews_recovery as recovery


@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(inbox,'credentials',lambda:{'access_token':'fixture-token'})
    monkeypatch.setattr(inbox,'sender_ids',lambda:{'sender'})
    rn.write({'owner':'owner','articles':[],'instagram_inbox':[]})


def page(ids,cursor):return {'data':[{'id':i,'created_time':'2026-10-25T00:00:00Z','from':{'id':'other'}} for i in ids],**({'paging':{'cursors':{'after':cursor},'next':'https://graph.instagram.com/next'}} if cursor else {})}


def test_empty_self_next_preserves_checkpoint_and_drains_secondary_edges(store):
    original={'last_message_id':'newest','last_timestamp':'2026-10-25T00:00:00Z','pagination_cursor':'oldest-cursor',
              'last_successful_cursor':'prior-good','messages_seen':91,'seen_message_ids':['existing'], 'pages_completed':8}
    d=rn.read();d['instagram_conversation_sync']={'requested':True,'conversation_ids':['verified'],
        'checkpoints':{'verified':deepcopy(original)},'messages_scanned':91,
        'pending_share_pages':{'share':{'sender':'sender','conversation_id':'verified','cursor':'share-end'}}};rn.write(d)
    with patch.object(h,'_read',side_effect=[page([],'oldest-cursor'),page([],None),page([],'share-end')]) as read:result=h.sync('owner')
    assert read.call_count==3 and read.call_args_list[0].args[2]['after']=='oldest-cursor'
    assert read.call_args_list[1].args[0]=='verified' and 'after(oldest-cursor)' in read.call_args_list[1].args[2]['fields']
    assert read.call_args_list[2].args[0]=='share/shares'
    c=rn.read()['instagram_conversation_sync']['checkpoints']['verified']
    assert all(c[k]==v for k,v in original.items())
    assert c['provider_exhausted'] and c['provider_end_confirmed'] and result['completion_state']=='PAGINATION_EXHAUSTED_BY_PROVIDER'
    assert not result['history_exhausted'] and not result['share_pages_pending']
    assert result['messages_scanned']==91
    assert len(rn.read()['instagram_conversation_sync']['page_history'])==2


def test_legacy_null_checkpoint_uses_recorded_cursor_without_reset(store):
    d=rn.read();d['instagram_conversation_sync']={'requested':True,'conversation_ids':['verified'],
        'checkpoints':{'verified':{'pagination_cursor':None,'last_successful_cursor':None,'cursor_recovery_required':True,'messages_seen':91}},
        'page_diagnostics':{'messages:verified':{'cursor_in':'legacy-end'}}};rn.write(d)
    with patch.object(h,'_read',return_value=page([],'legacy-end')) as read:result=h.sync('owner')
    assert read.call_count==2 and read.call_args_list[0].args[2]['after']=='legacy-end'
    assert set(read.call_args_list[0].args[2])=={'fields','limit','after'}  # No invented until/before timestamps.
    assert result['completion_state']=='PAGINATION_EXHAUSTED_BY_PROVIDER'


def test_omitted_optional_reference_preserves_checkpoint_and_drains_shares(store):
    original={'pagination_cursor':'end','last_successful_cursor':'good','messages_seen':91}
    d=rn.read();d['instagram_conversation_sync']={'requested':True,'conversation_ids':['verified'],
        'checkpoints':{'verified':dict(original)},'messages_scanned':91,
        'pending_share_pages':{'share':{'sender':'sender','conversation_id':'verified','cursor':'share-end'}}};rn.write(d)
    with patch.object(h,'_read',side_effect=[page([],'end'),ValueError('META_HISTORY_REFERENCE_OMITTED'),page([],'share-end')]):
        result=h.sync('owner')
    c=rn.read()['instagram_conversation_sync']['checkpoints']['verified']
    assert all(c[k]==v for k,v in original.items())
    assert c['provider_end_confirmed'] is None and c['provider_confirmation_status']=='REFERENCE_FIELD_OMITTED'
    assert result['completion_state']=='PAGINATION_EXHAUSTED_BY_PROVIDER'
    assert not result['history_exhausted'] and not result['share_pages_pending']


@pytest.mark.parametrize('failure',[ValueError('META_HISTORY_INVALID_RESPONSE'),h.HistoryReadError('META_HISTORY_RATE_LIMITED',{'code':4},3600),h.HistoryReadError('META_HISTORY_HTTP_401',{'code':190})])
def test_optional_reference_does_not_hide_invalid_auth_or_rate_errors(store,failure):
    d=rn.read();d['instagram_conversation_sync']={'requested':True,'conversation_ids':['verified'],'checkpoints':{'verified':{'pagination_cursor':'end'}}};rn.write(d)
    with patch.object(h,'_read',side_effect=[page([],'end'),failure]):result=h.sync('owner')
    s=rn.read()['instagram_conversation_sync']
    assert s['error']==str(failure) and not s['checkpoints']['verified'].get('provider_exhausted')
    if isinstance(failure,h.HistoryReadError) and failure.retry_after:assert s['retry_after']>time.time()+3500


@pytest.mark.parametrize('body,code',[({'id':'verified'},'META_HISTORY_REFERENCE_OMITTED'),({'id':'other'},'META_HISTORY_INVALID_RESPONSE'),({'id':'verified','messages':None},'META_HISTORY_INVALID_RESPONSE'),({'id':'verified','unexpected':True},'META_HISTORY_INVALID_RESPONSE')])
def test_reference_omission_is_distinct_from_empty_or_malformed(body,code):
    from types import SimpleNamespace
    response=SimpleNamespace(ok=True,json=lambda:body)
    with patch.object(h.requests,'get',return_value=response),pytest.raises(ValueError,match=code):
        h._read('verified','fixture',{'fields':'messages.limit(25).after(end){id,created_time}'})


def test_repeated_cursor_with_new_messages_continues_then_stops(store):
    progress={}
    with patch.object(h,'_read',side_effect=[page(['one'],'a'),page(['two'],'a'),page([],'a')]) as read:
        result=list(h._pages('verified/messages','fixture',{},progress=progress))
    assert len(result)==3 and read.call_count==3
    assert set(progress['seen_message_ids'])=={'one','two'} and progress['provider_exhausted']


def test_cursor_cycle_with_no_new_ids_stalls_but_changing_duplicate_pages_continue(store):
    with patch.object(h,'_read',side_effect=[page(['one'],'b'),page(['two'],'a'),page(['one'],'b')]):
        with pytest.raises(h.HistoryReadError,match='PAGINATION_CURSOR_REPEAT'):list(h._pages('verified/messages','fixture',{},after='a'))
    with patch.object(h,'_read',side_effect=[page(['one'],'a'),page(['one'],'b'),page(['two'],None)]):
        assert len(list(h._pages('verified/messages','fixture',{})))==3


def sample(**values):return dict({'id':'a'*24,'source_url':'https://www.instagram.com/reel/fixture/','analysis':{'transcript':'The tool is called ExactTool.','visual_findings':'vendor/ExactTool Public ExactTool'},'visual_assets':[]},**values)


def proof(repo):return {'status':'RESOLVED','name':repo.split('/')[-1],'repo':repo,'sources':['https://github.com/'+repo]}


def test_evidence_aggregation_and_official_confidence(store):
    row=sample();row['analysis']['visual_findings']+='\nvendor/ExactTool Public ExactTool'
    b=identity.bundle(rn.read(),row)
    assert b['signals']['OCR'].count('vendor/ExactTool')==1
    assert b['repositories']==['vendor/ExactTool']
    d=rn.read();d['ambiguous_reprocessing']={'provider_retry_after':time.time()+100}
    with patch.object(identity,'verify_repository',side_effect=lambda repo,b:proof(repo)):
        result=identity.identify(d,row)
    assert result['status']=='AUTO_IDENTIFIED' and result['resolution']['repo']=='vendor/ExactTool'
    assert result['candidates'][0]['official_source'] and result['candidates'][0]['confidence']>=identity.HIGH
    with patch.object(identity,'verify_repository',return_value=None),patch.object(inbox,'resolve_entity',return_value={'status':'NEEDS_DISAMBIGUATION'}):
        assert identity.identify(d,row)['status']!='AUTO_IDENTIFIED'


def test_multiple_official_products_are_reviewed_never_arbitrarily_chosen(store):
    row=sample();row['analysis'].update(repositories=['one/Alpha','two/Beta'],transcript='Alpha and Beta',visual_findings='one/Alpha Public two/Beta Public Alpha Beta')
    d=rn.read();d['ambiguous_reprocessing']={'provider_retry_after':time.time()+100}
    with patch.object(identity,'verify_repository',side_effect=lambda repo,b:proof(repo)),patch.object(inbox,'resolve_entity',return_value={'status':'NEEDS_DISAMBIGUATION'}):result=identity.identify(d,row)
    assert result['status']=='CANDIDATE_REVIEW' and result['resolution'] is None
    assert any(c['conflicts'] for c in result['candidates'])


def test_cluster_and_creator_are_only_hints(store):
    row=sample(creator='same-creator');other=sample(id='b'*24,creator='same-creator',repo='known/Tool')
    d=rn.read();d['instagram_inbox']=[row,other]
    assert all(x['reason']!='CREATOR_ONLY' for x in identity.bundle(d,row)['related_reels'])
    assert identity.bundle(d,row)['entity_index']==[]


def test_frozen_cohort_does_not_reprocess_the_other_26(store):
    d=rn.read();ids=[f'{n:024x}' for n in range(66)]
    d['instagram_inbox']=[{'id':i,'status':'NEEDS_DISAMBIGUATION' if n<40 else 'PUBLISHED'} for n,i in enumerate(ids)]
    d['reel_recovery_118']={'ambiguous_ids':ids[:40],'failed_ids':[],'excluded_ids':ids[40:]};rn.write(d)
    assert ambiguity.start('owner')['ids']==ids[:40]
    with patch.object(ambiguity,'identify',return_value={'status':'CANDIDATE_REVIEW','candidates':[]} ) as identify:
        for _ in range(41):ambiguity.tick()
    assert identify.call_count==40
    assert all(r=={'id':i,'status':'PUBLISHED'} for r,i in zip(rn.read()['instagram_inbox'][40:],ids[40:]))
    assert not ambiguity.start('owner')['enabled']


@pytest.mark.parametrize('code,kind,permanent',[('META_HTTP_401','AUTH_FAILED',False),('HTTP_429','PROVIDER_RATE_LIMIT',False),('SOURCE_HTTP_410','DELETED_SOURCE',True),('INVALID_REEL','INVALID_REEL',True),('UNVERIFIED_COMMAND','UNKNOWN',False),('UPSTREAM_REPOSITORY_REQUIRED','UNKNOWN',False)])
def test_failed_classification_does_not_mislabel_editorial_errors(code,kind,permanent):
    result=recovery.classify({'error':code,'source_url':'https://www.instagram.com/reel/fixture/'})
    assert result['classification']==kind and result['permanent']==permanent
    assert result['original_code']==code


def test_no_change_links_source_without_mutating_published_snapshot(store):
    from app import reposnews_revisions as revisions
    article={'id':'tool','repo':'vendor/ExactTool','repository_url':'https://github.com/vendor/ExactTool','published':True,
             'source_reels':['https://www.instagram.com/reel/old/'],'published_snapshot':{'body_es':'Public content','state':'PUBLISHED'}}
    baseline=deepcopy(article['published_snapshot']);data={'articles':[article]};row={'id':'row','source_url':'https://www.instagram.com/reel/new/'}
    with patch('app.reposnews_generation.generate_json',return_value={'relevant':False}):assert revisions.consider(data,row,dict(article))
    assert row['status']=='NO_CHANGE' and row['linked_article_id']=='tool'
    assert article['published_snapshot']==baseline and len(data['articles'])==1
    assert row['source_url'] in article['source_reels']


def test_informative_frames_reject_blank_and_identical_images():
    from app.reel_frames import informative_indices
    def encode(image):
        out=io.BytesIO();image.save(out,format='JPEG');return out.getvalue()
    blank=encode(Image.new('RGB',(64,64),'black'));rng=random.Random(1)
    images=[encode(Image.frombytes('L',(64,64),bytes(rng.randrange(256) for _ in range(4096)))) for _ in range(14)]
    indices=informative_indices([blank,images[0],images[0]]+images[1:],12)
    assert len(indices)==12 and 0 not in indices and not ({1,2}<=set(indices))


def test_grouped_identification_retains_all_forty_items():
    from app.notification_center import clean
    details={'items':[{'id':str(i),'caption':'Public caption','candidates':[{'candidate':'Tool','confidence':.5}]} for i in range(40)]}
    assert len(clean(details,-3)['items'])==40
    assert len(clean({'generic':list(range(40))})['generic'])==15


def test_running_identification_does_not_resolve_previous_group():
    from app.notification_center import reconcile_actions
    note={'id':'group','type':'ARTICLE_IDENTIFICATION_REQUIRED','status':'ACTION_REQUIRED'}
    data={'ambiguous_reprocessing':{'ids':['reel'],'completed':[]},'instagram_inbox':[{'id':'reel','status':'NEEDS_DISAMBIGUATION'}]}
    reconcile_actions([note],data)
    assert note['status']=='ACTION_REQUIRED'
    data['ambiguous_reprocessing']['completed']=['reel']
    reconcile_actions([note],data)
    assert note['status']=='ACTION_REQUIRED'
    data['instagram_inbox'][0]['status']='NO_CHANGE'
    reconcile_actions([note],data)
    assert note['status']=='DONE' and note['outcome']=='IDENTIFICATION_RESOLVED'


@pytest.mark.parametrize('dismissed',[None,'2026-10-25T00:00:00Z'])
def test_group_reopens_automatic_resolution_but_preserves_user_archive(store,dismissed):
    from app import identity_center,holdings,notification_center
    data=rn.read();data.update(ambiguous_reprocessing={'ids':['reel'],'completed':['reel']},
        instagram_inbox=[{'id':'reel','status':'NEEDS_DISAMBIGUATION'}])
    with holdings.transaction('owner'):
        saved=holdings.read('owner');center=identity_center.ensure(saved)
        center['human_actions'].append({'id':'group','notification_key':'ambiguous-group:'+ambiguity.GROUP_KEY,
            'type':'ARTICLE_IDENTIFICATION_REQUIRED','status':'DONE','outcome':'IDENTIFICATION_RESOLVED','dismissed_at':dismissed})
        holdings.write('owner',saved)
    ambiguity.grouped('owner',data)
    note=next(x for x in identity_center.ensure(holdings.read('owner'))['human_actions'] if x['id']=='group')
    assert note['status']==('DONE' if dismissed else 'ACTION_REQUIRED')
    assert note['dismissed_at']==dismissed and len(note['details']['items'])==1
