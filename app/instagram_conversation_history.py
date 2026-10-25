"""Official, sender-scoped conversation reconciliation into the existing Reel pipeline.

Stores only Reel evidence/metadata. Pagination URLs are never followed with credentials;
only cursors are carried onto fixed Instagram Graph endpoints. No publishing operations.
"""
import hashlib
import re
import time
from urllib.parse import urlsplit,parse_qs
import requests
from . import holdings,reposnews as rn
from .instagram_local_queue import reel_url,same_reel

BASE='https://graph.instagram.com/v26.0/'
DAY=86400


class HistoryReadError(ValueError):
    def __init__(self,code,detail,retry_after=0):
        super().__init__(code);self.detail=detail;self.retry_after=retry_after


def _owned(scope):
    data=rn.read()
    if data.get('owner')!=scope:raise ValueError('OWNER_REQUIRED')
    return data


def _read(path,token,params):
    if not re.fullmatch(r'[A-Za-z0-9_.:-]+(?:/(?:conversations|messages|shares))?',path):raise ValueError('INVALID_GRAPH_PATH')
    r=requests.get(BASE+path,params=params,headers={'Authorization':'Bearer '+token},timeout=25,allow_redirects=False)
    if not r.ok:
        from .reposnews_inbox import safe_meta_error
        detail=safe_meta_error(r,token)
        if r.status_code==429 or detail.get('code') in {4,17,32,613}:
            value=str(r.headers.get('Retry-After',''))
            delay=max(600,min(DAY,int(value))) if value.isdigit() else 3600
            raise HistoryReadError('META_HISTORY_RATE_LIMITED',detail,delay)
        if detail.get('code')==100 and re.search('cursor|paging|pagination',detail.get('message',''),re.I):
            raise HistoryReadError('PAGINATION_CURSOR_INVALID',detail,3600)
        if r.status_code in (429,500,502,503,504):raise ValueError('META_HISTORY_RETRYABLE_HTTP_'+str(r.status_code))
        raise HistoryReadError('META_HISTORY_HTTP_'+str(r.status_code),detail)
    b=r.json()
    if isinstance(b,dict) and isinstance(b.get('messages'),dict) and str(params.get('fields','')).startswith('messages.'):
        b=b['messages']
    if not isinstance(b,dict) or not isinstance(b.get('data'),list):raise ValueError('META_HISTORY_INVALID_RESPONSE')
    return b


def _after(body):
    paging=body.get('paging') or {}
    if not paging.get('next'):return None
    # Only the opaque cursor is reused; ignore any host, token or other next params.
    cursor=(paging.get('cursors') or {}).get('after')
    if not cursor:
        u=urlsplit(paging['next'])
        if u.scheme!='https' or u.hostname!='graph.instagram.com':raise ValueError('META_HISTORY_UNSAFE_PAGINATION')
        cursor=parse_qs(u.query).get('after',[None])[0]
    if not isinstance(cursor,str) or not cursor or len(cursor)>4096:raise ValueError('META_HISTORY_CURSOR_MISSING')
    return cursor


def _pages(path,token,params,after=None,progress=None):
    progress=progress if progress is not None else {}
    seen=set(progress.get('seen_cursors',[]));ids=set(progress.get('seen_message_ids',[]));requests_made=0
    while True:
        if requests_made>=10:raise HistoryReadError('PAGINATION_PAGE_BUDGET',{'edge':path.rsplit('/',1)[-1]},60)
        body=_read(path,token,dict(params,**({'after':after} if after else {})))
        requests_made+=1;seen.add(after)
        cursor=_after(body);rows=body['data'];page_ids=[str(m.get('id') or m.get('link') or '') for m in rows]
        new=sum(bool(mid) and mid not in ids for mid in page_ids);ids.update(page_ids)
        repeated=cursor is not None and cursor in seen
        times=sorted(str(m.get('created_time')) for m in rows if m.get('created_time'))
        pattern='EMPTY_PAGE_WITH_NEXT_CURSOR' if not rows and cursor else 'DUPLICATE_BOUNDARY_MESSAGE' if new<len(page_ids) else 'PROGRESS'
        if repeated:pattern='SAME_CURSOR_RETURNED' if cursor==after else 'CURSOR_CYCLE'
        progress.update(cursor_in=after,cursor_out=cursor,first_message_id=page_ids[0] if page_ids else None,
            last_message_id=page_ids[-1] if page_ids else None,count=len(rows),new_message_count=new,
            cursor_repeat=repeated,pages_completed=progress.get('pages_completed',0)+1,
            oldest_timestamp=times[0] if times else None,newest_timestamp=times[-1] if times else None,
            pattern=pattern,seen_cursors=list(seen),seen_message_ids=sorted(ids))
        if repeated and not new and not rows:
            progress.update(provider_exhausted=True,pattern='EMPTY_PAGE_WITH_SELF_NEXT' if cursor==after else 'EMPTY_CURSOR_CYCLE')
        yield rows,cursor
        # Empty self-referential end pages are an observed provider limit, not proof
        # that all historical content exists locally. A repeated cursor with NEW
        # messages may be read again; dedup and the request budget bound that case.
        if progress.get('provider_exhausted'):return
        if repeated and not new:raise HistoryReadError('PAGINATION_CURSOR_REPEAT',{'edge':path.rsplit('/',1)[-1],'pattern':pattern},3600)
        if cursor is None:return
        after=cursor


def _page_audit(state,key,progress):
    safe={k:v for k,v in progress.items() if k not in {'seen_message_ids','seen_cursors'}}
    safe['conversation_id']=key.split(':',1)[1] if key.startswith('messages:') else None
    safe['page_number']=state.get('api_pages_total',0)+1;safe['message_count']=safe.get('count',0)
    state['api_pages_total']=safe['page_number']
    state.setdefault('page_history',[]).append(dict(safe,edge=key,at=holdings._now()))
    state['page_history']=state['page_history'][-60:]
    state.setdefault('page_diagnostics',{})[key]=safe


def _reels(message,token,fetch=True):
    from .reposnews_history import links
    found=set(links(message.get('message','')))
    shared=message.get('shares') or {}
    if isinstance(shared,dict):
        found.update(links(shared.get('data',[])))
        after=_after(shared)
        if after and fetch:
            for rows,_ in _pages(message['id']+'/shares',token,{'fields':'link','limit':100},after):found.update(links(rows))
    # Some official message attachments contain a permalink rather than a share edge.
    found.update(links(message.get('attachments',{})))
    return sorted(found)


def _drain_shares(scope,token,senders):
    """Complete secondary edges after the outer conversation pages are checkpointed."""
    from .reposnews_history import links
    pending=dict(rn.read()['instagram_conversation_sync'].get('pending_share_pages',{}))
    for mid,record in list(pending.items())[:10]:
        if record['sender'] not in senders:raise ValueError('AUTHORIZED_SENDER_REQUIRED')
        message={'id':mid,'from':{'id':record['sender']},'created_time':record.get('timestamp')}
        progress={'seen_message_ids':record.get('seen_links',[]),'seen_cursors':record.get('seen_cursors',[])}
        after=(record.get('last_successful_cursor') or record['cursor']) if record.get('cursor_recovery_required') else record['cursor']
        for rows,cursor in _pages(mid+'/shares',token,{'fields':'link','limit':25 if record.get('cursor_recovery_required') else 100},after,progress):
            urls=sorted(set(links(rows)))
            if urls:_ingest(scope,record['conversation_id'],message,urls)
            with holdings.transaction('reposnews-editorial'):
                data=_owned(scope);state=data['instagram_conversation_sync']
                if progress.get('provider_exhausted'):
                    state.setdefault('share_provider_limits',{})[mid]=dict(record,reason=progress['pattern'],checked_at=holdings._now())
                    state['pending_share_pages'].pop(mid,None)
                elif cursor and progress.get('new_message_count'):
                    state['pending_share_pages'][mid].update(cursor=cursor,last_successful_cursor=progress.get('cursor_in'),cursor_recovery_required=False,
                        seen_links=progress.get('seen_message_ids',[]),seen_cursors=progress.get('seen_cursors',[]))
                elif cursor:state['pending_share_pages'][mid].update(pagination_error='PAGINATION_CURSOR_REPEAT',cursor_recovery_required=True)
                else:state['pending_share_pages'].pop(mid,None)
                _page_audit(state,'shares:'+mid,progress)
                state['lease_until']=time.time()+1800;rn.write(data)
    if len(pending)>10:raise HistoryReadError('PAGINATION_PAGE_BUDGET',{'edge':'shares'},60)


def _ingest(scope,cid,message,urls):
    from .reposnews_inbox import sender_ids,safe_caption
    sender=str((message.get('from') or {}).get('id') or '')
    if sender not in sender_ids():return
    mid=str(message.get('id') or '')
    if not mid:return
    with holdings.transaction('reposnews-editorial'):
        data=_owned(scope);rows=data.setdefault('instagram_inbox',[])
        index=data.setdefault('instagram_conversation_reel_index',[])
        for url in urls:
            url=reel_url(url);key=hashlib.sha256((mid+'|'+url).encode()).hexdigest()[:24]
            if any(x['id']==key for x in index):continue
            existing=next((x for x in rows if same_reel(x.get('source_url'),url)),None)
            known=existing is not None and not existing.get('conversation_discovered')
            if existing:
                existing['external_ids']=list(dict.fromkeys(existing.get('external_ids',[existing['external_id']])+[mid]))
            else:
                item=hashlib.sha256(('conversation:'+url).encode()).hexdigest()[:24]
                existing={'id':item,'external_id':mid,'external_ids':[mid],'sender':sender,'source_url':url,
                          'received_at':holdings._now(),'meta_timestamp':message.get('created_time'),'caption':safe_caption(message.get('message',''))[:1500],
                          'status':'RECEIVED','processing_state':'RECEIVED','attempts':0,'attempt_limit':8,
                          'backfill':True,'discovery_only':True,'access_level':'OFFICIAL_SHARE_PERMALINK',
                          'conversation_id':cid,'conversation_discovered':True,'discovery_metadata':{'source':'OFFICIAL_MESSAGES_API'}}
                rows.append(existing)
                # Direct CDN media, when supplied by Meta, goes through the existing
                # encrypted transient inbox before any dedicated-browser fallback.
                attachments=message.get('attachments',{})
                private=[]
                for attachment in attachments.get('data',[]) if isinstance(attachments,dict) else []:
                    video=attachment.get('video_data') or {}
                    url_value=video.get('url')
                    if isinstance(url_value,str) and url_value.startswith('https://'):private.append({'type':'video','url':url_value})
                if private:
                    import json
                    from . import oauth_vault
                    oauth_vault.persist(rn._path().parent/'inbound'/item,json.dumps(private),rn._path().parent)
                    existing['official_media_available']=True
            index.append({'id':key,'external_message_id':mid,'timestamp':message.get('created_time'),
                          'permalink':url,'media_id':None,'sender':sender,'conversation_id':cid,
                          'processing_status':existing.get('status'),'article_id':existing.get('linked_article_id') or existing.get('article_id'),
                          'source_entity_id':None,'inbox_item_id':existing['id'],'previously_known':known,'last_checked':holdings._now()})
        rn.write(data)


def refresh(data):
    """Project existing pipeline results into the conversation index; no reprocessing."""
    from .reposnews_revisions import identity
    rows={r['id']:r for r in data.get('instagram_inbox',[])}
    articles={a['id']:a for a in data.get('articles',[])}
    for entry in data.get('instagram_conversation_reel_index',[]):
        row=rows.get(entry.get('inbox_item_id'),{})
        entry.update(processing_status=row.get('status','SOURCE_UNAVAILABLE'),article_id=row.get('linked_article_id') or row.get('article_id'),last_checked=holdings._now())
        entry['source_availability']='SOURCE_UNAVAILABLE' if row.get('local_result')=='CONTENT_UNAVAILABLE' or row.get('error') in {'SOURCE_HTTP_404','SOURCE_HTTP_410'} else 'AVAILABLE_OR_UNVERIFIED'
        entry['retry_exhausted']=row.get('status')=='FAILED_RETRYABLE' and row.get('attempts',0)>=row.get('attempt_limit',8)
        article=articles.get(entry['article_id'])
        if article:entry['source_entity_id']=identity(article)['entity_id']


def summary(data):
    entries=data.get('instagram_conversation_reel_index',[])
    # Counts represent distinct Reels/jobs, while all message associations are retained.
    unique={e['permalink']:e for e in entries}.values()
    terminal={'READY_PRIVATE','ARTICLE_UPDATE_DRAFT','NO_CHANGE','PUBLISHED','NEEDS_DISAMBIGUATION','FAILED_PERMANENT','FAILED_SOURCE','SOURCE_UNAVAILABLE','CANCELLED','DISCARDED'}
    counts={'reels_found':0,'previously_known':0,'newly_discovered':0,'processed':0,'pending':0,'new_drafts':0,'updates_proposed':0,'no_change':0,'ambiguous':0,'failed':0,'articles_matched':0}
    known={e['permalink'] for e in entries if e.get('previously_known')}
    for e in unique:
        counts['reels_found']+=1;counts['previously_known' if e['permalink'] in known else 'newly_discovered']+=1
        state=e.get('processing_status');counts['processed' if state in terminal or e.get('retry_exhausted') else 'pending']+=1
        if e.get('article_id'):counts['articles_matched']+=1
        key={'READY_PRIVATE':'new_drafts','ARTICLE_UPDATE_DRAFT':'updates_proposed','NO_CHANGE':'no_change','NEEDS_DISAMBIGUATION':'ambiguous','FAILED_SOURCE':'failed','FAILED_PERMANENT':'failed','SOURCE_UNAVAILABLE':'failed'}.get(state)
        if key:counts[key]+=1
        elif e.get('retry_exhausted'):counts['failed']+=1
    sync=data.get('instagram_conversation_sync',{})
    return dict(counts,conversation_found=bool(sync.get('conversation_ids')),messages_scanned=sync.get('messages_scanned',0),
                last_sync=sync.get('completed_at'),status=sync.get('status','NOT_STARTED'),error=sync.get('error'),
                history_exhausted=sync.get('history_exhausted',False),cursor_saved=bool(sync.get('checkpoints')),
                daily_reconciliation=True,next_sync=sync.get('next_sync'),retry_after=sync.get('retry_after'),
                provider_error=sync.get('provider_error'),share_pages_pending=len(sync.get('pending_share_pages',{})),concurrency=1,
                completion_state=sync.get('completion_state'),pages_total=sync.get('api_pages_total',0),
                provider_limited=any(c.get('provider_exhausted') for c in sync.get('checkpoints',{}).values()) or bool(sync.get('share_provider_limits')))


def sync(scope,force=False):
    from .reposnews_inbox import credentials,sender_ids
    now=time.time()
    with holdings.transaction('reposnews-editorial'):
        data=_owned(scope);state=data.setdefault('instagram_conversation_sync',{})
        if state.get('lease_until',0)>now:return summary(data)
        if state.get('retry_after',0)>now:return summary(data)
        from .instagram_tokens import state_for
        if state_for(credentials(),now)=='REAUTH_REQUIRED':
            state.update(status='AUTH_REQUIRED',error='META_HISTORY_AUTH_REQUIRED',requested=False);rn.write(data)
            return summary(data)
        if not force and not state.get('requested') and state.get('status')!='SYNCING' and state.get('next_sync',0)>now:return summary(data)
        state.update(status='SYNCING',started_at=holdings._now(),lease_until=now+1800,requested=False,next_sync=now+DAY,error=None)
        rn.write(data)
    try:
        auth=credentials();token=auth.get('access_token')
        senders=sender_ids()
        if not token or not senders:raise ValueError('INSTAGRAM_AUTHORIZED_SENDER_OR_TOKEN_REQUIRED')
        conversations=[]
        # Preserve known verified conversations when discovery itself repeats a cursor.
        existing_conversations=rn.read()['instagram_conversation_sync'].get('conversation_ids',[])
        conversations=list(existing_conversations)
        for sender in ([] if conversations else sorted(senders)):
            # Server-side user filter; independently verify the participant identity too.
            progress={}
            for rows,_ in _pages('me/conversations',token,{'platform':'instagram','user_id':sender,'fields':'id,participants,updated_time','limit':100},progress=progress):
                for c in rows:
                    participants=(c.get('participants') or {}).get('data',[])
                    if any(str(p.get('id'))==sender and p.get('username')=='solana031' for p in participants):conversations.append(c['id'])
                with holdings.transaction('reposnews-editorial'):
                    data=rn.read();state=data['instagram_conversation_sync']
                    state['conversation_ids']=list(dict.fromkeys(existing_conversations+conversations))
                    _page_audit(state,'conversations',progress);rn.write(data)
        with holdings.transaction('reposnews-editorial'):
            data=rn.read();state=data['instagram_conversation_sync'];state['conversation_ids']=list(dict.fromkeys(conversations));rn.write(data)
        for cid in dict.fromkeys(conversations):
            checkpoint=rn.read()['instagram_conversation_sync'].get('checkpoints',{}).get(cid,{})
            if checkpoint.get('provider_exhausted') and checkpoint.get('head_check_after',0)>now:continue
            complete=checkpoint.get('history_exhausted',False);anchor=checkpoint.get('last_message_id') if complete else None
            newest=checkpoint.get('last_message_id') if not complete else None
            latest_time=checkpoint.get('last_timestamp') if not complete else None
            after=None if complete else checkpoint.get('pagination_cursor')
            if checkpoint.get('cursor_recovery_required'):
                after=checkpoint.get('last_successful_cursor') or after
                if after is None:
                    # Legacy versions overwrote the checkpoint with null on an
                    # empty repeated page. The recorded request cursor survives.
                    after=rn.read()['instagram_conversation_sync'].get('page_diagnostics',{}).get('messages:'+cid,{}).get('cursor_in')
            progress={'seen_message_ids':checkpoint.get('seen_message_ids',[]),'seen_cursors':checkpoint.get('seen_cursors',[])}
            seen_ids=set(checkpoint.get('seen_message_ids',[]));pages_before=checkpoint.get('pages_completed',0)
            limit=25 if checkpoint.get('cursor_recovery_required') else 100
            for messages,cursor in _pages(cid+'/messages',token,{'fields':'id,created_time,from,message,attachments,shares','limit':limit},after,progress):
                stop=False;scanned=0;share_pages={}
                for message in messages:
                    scanned+=1
                    if not newest:newest=message.get('id');latest_time=message.get('created_time')
                    if message.get('id')==anchor:stop=True;break
                    if message.get('id') in seen_ids:continue
                    seen_ids.add(message.get('id'))
                    if str((message.get('from') or {}).get('id')) in senders:
                        urls=_reels(message,token,fetch=False)
                        if urls:_ingest(scope,cid,message,urls)
                        shared=message.get('shares') or {}
                        share_cursor=_after(shared) if isinstance(shared,dict) else None
                        if share_cursor:share_pages[message['id']]={'cursor':share_cursor,'sender':str(message['from']['id']),'timestamp':message.get('created_time'),'conversation_id':cid}
                end_confirmation=None
                if progress.get('provider_exhausted'):
                    # Meta documents the conversation node's messages field as
                    # the reference listing. Confirm the SAME cursor there; do
                    # not restart at the head or invent time-range parameters.
                    reference=_read(cid,token,{'fields':'messages.limit(25).after('+str(progress['cursor_in'])+'){id,created_time}'})
                    end_confirmation=not reference['data'] and not (reference.get('paging') or {}).get('next')
                with holdings.transaction('reposnews-editorial'):
                    data=rn.read();state=data['instagram_conversation_sync']
                    state['messages_scanned']=state.get('messages_scanned',0)+scanned
                    state.setdefault('pending_share_pages',{}).update(share_pages)
                    repeated=progress.get('cursor_repeat',False)
                    prior=state.setdefault('checkpoints',{}).get(cid,{})
                    # Keep the prior checkpoint intact on an empty/no-progress page.
                    progressed=bool(scanned and progress.get('new_message_count'))
                    saved=dict(prior)
                    if progressed or stop or cursor is None:
                        saved.update({'last_message_id':newest or checkpoint.get('last_message_id'),'last_timestamp':latest_time or checkpoint.get('last_timestamp'),
                        'last_message_timestamp':latest_time or checkpoint.get('last_timestamp'),
                        'pagination_cursor':None if stop else cursor,
                        'last_successful_cursor':progress.get('cursor_in') if progressed else prior.get('last_successful_cursor'),
                        'cursor_recovery_required':repeated and not progressed,'pages_completed':pages_before+progress['pages_completed'],
                        'last_processed_message_id':progress.get('last_message_id'),
                        'last_processed_message_timestamp':messages[-1].get('created_time') if messages else prior.get('last_processed_message_timestamp'),
                        'messages_seen':max(prior.get('messages_seen',0),len(seen_ids)),'seen_message_ids':sorted(x for x in seen_ids if x)[-10000:],
                        'history_exhausted':stop or cursor is None})
                    saved['seen_cursors']=progress.get('seen_cursors',[])
                    if repeated and not progressed:saved['cursor_recovery_required']=True
                    if progress.get('provider_exhausted'):
                        saved.update(provider_exhausted=True,provider_end_confirmed=end_confirmation,
                            provider_limitation='EMPTY_PAGE_WITH_SELF_NEXT',head_check_after=now+DAY)
                    state['checkpoints'][cid]=saved
                    _page_audit(state,'messages:'+cid,progress)
                    state['lease_until']=time.time()+1800;rn.write(data)
                if stop:break
        _drain_shares(scope,token,senders)
        with holdings.transaction('reposnews-editorial'):
            data=rn.read();state=data['instagram_conversation_sync'];refresh(data)
            limited=any(c.get('provider_exhausted') for c in state.get('checkpoints',{}).values()) or bool(state.get('share_provider_limits'))
            exhausted=bool(conversations) and all(c.get('history_exhausted') for c in state.get('checkpoints',{}).values()) and not state.get('pending_share_pages')
            state.update(status='COMPLETED',completion_state='PAGINATION_EXHAUSTED_BY_PROVIDER' if limited else 'HISTORY_COMPLETE' if exhausted else 'PAGINATION_STALLED',
                history_exhausted=exhausted and not limited,completed_at=holdings._now(),lease_until=0,retry_after=0)
            # Add newly discovered Reels to the existing sequential, durable pipeline.
            data.setdefault('historical_backfill',{}).update(enabled=True,mode='BATCH_LIMITED',concurrency=1)
            rn.write(data)
        return summary(data)
    except (ValueError,KeyError,TypeError,OSError,requests.RequestException) as exc:
        # No exception text: provider URLs/payloads can contain credentials or private text.
        with holdings.transaction('reposnews-editorial'):
            code=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'[A-Z0-9_]{1,80}',str(exc)) else 'OFFICIAL_CONVERSATION_SYNC_FAILED'
            data=rn.read();state=data['instagram_conversation_sync'];state.update(status='RATE_LIMITED' if code=='META_HISTORY_RATE_LIMITED' else 'FAILED_RETRYABLE',error=code,lease_until=0)
            if isinstance(exc,HistoryReadError):state['provider_error']=exc.detail
            if code in {'PAGINATION_CURSOR_REPEAT','PAGINATION_CURSOR_INVALID'}:state['completion_state']='PAGINATION_STALLED'
            if code=='PAGINATION_CURSOR_INVALID':
                for checkpoint in state.get('checkpoints',{}).values():
                    if not checkpoint.get('history_exhausted'):checkpoint['cursor_recovery_required']=True
            if getattr(exc,'retry_after',0):state.update(retry_after=time.time()+exc.retry_after,next_sync=time.time()+exc.retry_after)
            rn.write(data)
        return summary(data)


def tick():
    data=rn.read();scope=data.get('owner')
    if not scope:return
    sync(scope)
    with holdings.transaction('reposnews-editorial'):
        data=rn.read();refresh(data);rn.write(data)
    result=summary(data)
    if result['status']=='RATE_LIMITED':
        from .notification_center import emit
        emit(scope,'INSTAGRAM_HISTORY_SYNC','instagram-history:rate-limit','Historial pausado por límite de Meta',
             'Meta ha limitado las solicitudes de mensajes. El cursor se conserva y ZAR reintentará automáticamente después de la espera.',
             '/accounts#instagram',entity_type='INSTAGRAM_HISTORY',details=result,status='DONE',priority='P2')
    if result['status']=='COMPLETED' and not result['pending']:
        from .notification_center import emit
        emit(scope,'INSTAGRAM_HISTORY_SYNC','instagram-history:'+data['instagram_conversation_sync']['started_at'],
             'Revisión histórica de Instagram completada','Reels encontrados: '+str(result['reels_found'])+'. Procesados: '+str(result['processed'])+'.',
             '/accounts#instagram',entity_type='INSTAGRAM_HISTORY',details=result,status='DONE',priority='P2')


def register(app,scope_fn,csrf_owner):
    from flask import jsonify
    @app.post('/api/reposnews/history/sync')
    def request_sync():
        scope=csrf_owner()
        with holdings.transaction('reposnews-editorial'):
            try:data=_owned(scope)
            except ValueError:return jsonify(ok=False,error='OWNER_REQUIRED'),403
            data.setdefault('instagram_conversation_sync',{})['requested']=True;rn.write(data)
        return jsonify(ok=True,result=summary(data))
