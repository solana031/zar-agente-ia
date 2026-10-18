"""HistoricalReelIndex over existing editorial persistence; sequential limited backfill."""
import hashlib
import re
from . import holdings,reposnews as rn
from .instagram_local_queue import reel_url

TERMINAL={'READY_PRIVATE','NO_CHANGE','ARTICLE_UPDATE_DRAFT','NEEDS_DISAMBIGUATION','FAILED_SOURCE','CANCELLED','DISCARDED','PUBLISHED'}


def links(value):
    if isinstance(value,dict):
        for item in value.values():yield from links(item)
    elif isinstance(value,list):
        for item in value:yield from links(item)
    elif isinstance(value,str):
        for url in re.findall(r'https://(?:www\.)?instagram\.com/(?:reel|p)/[A-Za-z0-9_-]+/?',value):
            try:yield 'https://www.instagram.com/reel/'+reel_url(url).rstrip('/').rsplit('/',1)[-1]+'/'
            except ValueError:pass


def index(data):
    found={}
    # Do not scan credentials, arbitrary user files or unrelated providers.
    for source in ('instagram_inbox','articles','editorial_notifications','instagram_event_history','instagram_local_worker_history','article_revisions'):
        for url in links(data.get(source,[])):
            found.setdefault(url,{'id':hashlib.sha256(url.encode()).hexdigest()[:24],'permalink':url,'origins':[]})['origins'].append(source)
    old={}
    for r in data.get('historical_reel_index',[]):
        key=next(links(r['permalink']),r['permalink'])
        if key not in old or r.get('state')=='COMPLETED':old[key]=r
    for url,entry in found.items():
        previous=old.get(url,{})
        entry.update({k:v for k,v in previous.items() if k not in {'origins','item_ids'}})
        entry['permalink']=url
        entry['origins']=sorted(set(entry['origins']))
        entry['item_ids']=[r['id'] for r in data.get('instagram_inbox',[]) if url in list(links(r.get('source_url','')))]
        related=[a for a in data.get('articles',[]) if url in list(links([a.get('discovery_source'),a.get('source_reels',[])]))]
        entry['linked_article_ids']=[a['id'] for a in related]
        entry['indexed_at']=previous.get('indexed_at') or holdings._now()
    data['historical_reel_index']=list(found.values())
    return data['historical_reel_index']


def summary(data):
    entries=data.get('historical_reel_index',[]);counts={'TOTAL_REELS':len(entries),'PROCESSED':0,'ARTICLE_CREATED':0,'UPDATE_PROPOSED':0,'NO_CHANGE':0,'NEEDS_DISAMBIGUATION':0,'FAILED':0,'MATCHED_ARTICLES':0,'DUPLICATES_AVOIDED':0}
    for entry in entries:
        if entry.get('state')=='COMPLETED':counts['PROCESSED']+=1
        decision=entry.get('decision')
        if decision in counts:counts[decision]+=1
        if entry.get('linked_article_ids'):counts['MATCHED_ARTICLES']+=1
        counts['DUPLICATES_AVOIDED']+=max(0,len(entry.get('item_ids',[]))-1)
    active=[]
    for entry in entries:
        if entry.get('state')!='PROCESSING':continue
        row=next((r for r in data.get('instagram_inbox',[]) if r['id']==entry.get('active_item_id')),{})
        active.append({'item_id':row.get('id'),'permalink':entry['permalink'],'stage':row.get('processing_state'),'status':row.get('status'),'error':row.get('error'),'attempts':row.get('attempts',0)})
    return dict(counts,active=active,mode='BATCH_LIMITED',concurrency=1,enabled=data.get('historical_backfill',{}).get('enabled',False))


def start(scope):
    with holdings.transaction('reposnews-editorial'):
        rn.state(scope);data=rn.read();index(data)
        data['historical_backfill']={'enabled':True,'mode':'BATCH_LIMITED','concurrency':1,'started_at':holdings._now()}
        rn.write(data)
    from .reposnews_inbox import start_worker
    start_worker()
    return summary(rn.read())


def tick():
    """One active historical item; existing workers perform the actual analysis."""
    from .reposnews_inbox import sender_ids
    with holdings.transaction('reposnews-editorial'):
        data=rn.read()
        if not data.get('historical_backfill',{}).get('enabled'):return
        entries=index(data);rows=data.setdefault('instagram_inbox',[])
        for entry in entries:
            row=next((r for r in rows if r['id'] in entry.get('item_ids',[])),None)
            if row and entry.get('decision')=='NEEDS_DISAMBIGUATION' and row.get('clarified_project') and not row.get('clarification_recovery_v2'):
                entry.update(state='PENDING',decision=None);row['clarification_recovery_v2']=True
            if row and entry.get('decision') in {'UPDATE_PROPOSED','ARTICLE_CREATED'} and row.get('asset_quality_version')!=2 and not row.get('asset_quality_recovery_v2'):
                entry.update(state='PENDING',decision=None);row['asset_quality_recovery_v2']=True
        for entry in entries:
            if entry.get('state')!='PROCESSING':continue
            row=next((r for r in rows if r['id']==entry.get('active_item_id')),None)
            if not row:entry.update(state='COMPLETED',decision='FAILED');continue
            package=row.get('research_package') or {}
            if row.get('error')=='SOURCE_OR_GENERATION_FAILED' and package and not {'repo','metadata','readme','sources','verified_at'}<=set(package) and not row.get('checkpoint_research_repaired'):
                row.update(status='RECEIVED',retry_after=0,run_attempts=0,checkpoint_research_repaired=True)
            exhausted=row.get('attempts',0)>=row.get('attempt_limit',8) and row.get('status')=='FAILED_RETRYABLE'
            if row.get('status') in TERMINAL or exhausted:
                status=row.get('status')
                result='UPDATE_PROPOSED' if status=='ARTICLE_UPDATE_DRAFT' else 'ARTICLE_CREATED' if status=='READY_PRIVATE' and row.get('backfill_decision')=='CREATE_NEW' else 'NO_CHANGE' if status in {'READY_PRIVATE','NO_CHANGE','PUBLISHED','CANCELLED','DISCARDED'} else 'NEEDS_DISAMBIGUATION' if status=='NEEDS_DISAMBIGUATION' else 'FAILED'
                entry.update(state='COMPLETED',decision=result,completed_at=holdings._now())
                if row.get('linked_article_id') or row.get('article_id'):entry['linked_article_ids']=list(dict.fromkeys(entry.get('linked_article_ids',[])+[row.get('linked_article_id') or row['article_id']]))
            else:rn.write(data);return
        entry=next((e for e in entries if e.get('state') not in {'COMPLETED','PROCESSING'}),None)
        if not entry:
            data['historical_backfill']['enabled']=False;rn.write(data);return
        row=next((r for r in rows if r['id'] in entry['item_ids']),None)
        if not row:
            senders=sender_ids()
            if not senders:rn.write(data);return
            row={'id':hashlib.sha256(('history:'+entry['permalink']).encode()).hexdigest()[:24],'external_id':'historical:'+entry['id'],
                 'sender':sorted(senders)[0],'source_url':entry['permalink'],'caption':'','received_at':holdings._now(),'attempts':0,'status':'RECEIVED'}
            rows.append(row);entry['item_ids']=[row['id']]
        if row.get('status') in {'CANCELLED','DISCARDED'}:
            entry.update(state='COMPLETED',decision='NO_CHANGE');rn.write(data);return
        # Preserve prior evidence and manuscripts; reacquire visuals only if they are missing.
        row.update(backfill=True,backfill_decision='UPDATE_EXISTING' if entry.get('linked_article_ids') else 'CREATE_NEW',attempt_limit=row.get('attempts',0)+4,run_attempts=0,retry_after=0)
        if not row.get('visual_assets') or row.get('asset_quality_version')!=2:
            row.update(asset_refresh=True,local_worker_done=False,local_media_received=False,local_job=True,status='WAITING_LOCAL_WORKER',processing_state='WAITING_LOCAL_WORKER',local_lease=0)
        else:row.update(status='RECEIVED',processing_state='RECEIVED')
        entry.update(state='PROCESSING',active_item_id=row['id']);rn.write(data)


def register(app,scope_fn):
    from flask import request,session,jsonify
    import secrets
    @app.post('/api/reposnews/history/start')
    def history_start():
        if session.get('zar_auth') is not True:return jsonify(ok=False,error='AUTH_REQUIRED'),401
        csrf=session.get('business_csrf','')
        if not csrf or not secrets.compare_digest(csrf,request.headers.get('X-ZAR-Business-CSRF','')):return jsonify(ok=False,error='CSRF_REQUIRED'),403
        try:return jsonify(ok=True,result=start(scope_fn()))
        except ValueError as e:return jsonify(ok=False,error=str(e)),403
