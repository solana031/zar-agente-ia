"""One bounded identification pass over unresolved historical Reels only."""
import base64
import json
import re
import time
from copy import deepcopy
from . import holdings, reposnews as rn
from .reposnews_entity_evidence import GENERIC, hints, normalized

ROUND='evidence-identification-v2'
GROUP_KEY='expanded-identification-v1'


def start(scope):
    with holdings.transaction('reposnews-editorial'):
        data=rn.read()
        if data.get('owner')!=scope:raise ValueError('OWNER_REQUIRED')
        old=data.get('ambiguous_reprocessing',{})
        if old.get('round')==ROUND:return old
        ids=[]
        frozen=data.get('reel_recovery_118',{}).get('ambiguous_ids')
        if frozen is not None:
            ids=[r['id'] for r in data.get('instagram_inbox',[]) if r['id'] in frozen and r.get('status')=='NEEDS_DISAMBIGUATION']
        for entry in data.get('historical_reel_index',[]):
            if frozen is not None or entry.get('decision')!='NEEDS_DISAMBIGUATION':continue
            rows=[r for r in data.get('instagram_inbox',[]) if r['id'] in entry.get('item_ids',[]) and r.get('status')=='NEEDS_DISAMBIGUATION']
            row=next((r for r in rows if r['id']==entry.get('active_item_id')),None) or next(iter(rows),None)
            if row:ids.append(row['id'])
        job={'round':ROUND,'ids':ids,'completed':[],'identified':[],'started_at':holdings._now(),'enabled':True}
        if old:data.setdefault('ambiguous_reprocessing_history',[]).append(old)
        data['ambiguous_reprocessing']=job;rn.write(data);return job


def identify(data,row):
    from .reposnews_identification import identify as identify_evidence
    return identify_evidence(data,row)


def tick():
    with holdings.transaction('reposnews-editorial'):
        data=rn.read();job=data.get('ambiguous_reprocessing',{})
        if not job.get('enabled') or job.get('lease_until',0)>time.time():return
        item=next((i for i in job['ids'] if i not in job['completed']),None)
        if not item:
            job['enabled']=False;job['completed_at']=holdings._now();rn.write(data)
            return
        row=next((r for r in data['instagram_inbox'] if r['id']==item),None)
        job['lease_until']=time.time()+600;rn.write(data);snapshot=deepcopy(data)
    try:
        result=identify(snapshot,deepcopy(row)) if row and row.get('status')=='NEEDS_DISAMBIGUATION' else {'status':'ALREADY_RESOLVED'}
    except (ValueError,OSError,TypeError):
        result={'status':'NEEDS_DISAMBIGUATION','candidates':[],'provider_error':'IDENTIFICATION_PROVIDER_UNAVAILABLE'}
    with holdings.transaction('reposnews-editorial'):
        data=rn.read();job=data['ambiguous_reprocessing'];row=next((r for r in data['instagram_inbox'] if r['id']==item),None)
        job['completed']=list(dict.fromkeys(job['completed']+[item]));job['lease_until']=0
        if result.get('provider_error'):job['provider_retry_after']=time.time()+3600
        if row and row.get('status')=='NEEDS_DISAMBIGUATION':
            row['expanded_identification']=result
            if result['status']=='AUTO_IDENTIFIED':
                resolution=result['resolution'];row.update(automatic_project=resolution['name'],automatic_repo=resolution.get('repo'),
                    status='RECEIVED',processing_state='IDENTIFYING',retry_after=0,run_attempts=0,attempt_limit=row.get('attempts',0)+2)
                row.setdefault('analysis',{})['official_entity_sources']=resolution.get('sources',[])
                job['identified'].append(item)
                for entry in data.get('historical_reel_index',[]):
                    if item in entry.get('item_ids',[]):entry.update(state='PROCESSING',decision=None,active_item_id=item)
                data.setdefault('historical_backfill',{})['enabled']=True
        rn.write(data)


def grouped(scope,data):
    """Ask only after every targeted Reel has completed its automatic pass."""
    job=data.get('ambiguous_reprocessing',{})
    if not job or len(job.get('completed',[]))<len(job.get('ids',[])):return None
    rows=[r for r in data.get('instagram_inbox',[]) if r['id'] in job['ids'] and r.get('status')=='NEEDS_DISAMBIGUATION']
    if not rows:return None
    from .notification_center import emit
    items=[{'id':r['id'],'date':r.get('meta_timestamp') or r.get('received_at'),'thumbnail':next((a.get('url') for a in r.get('visual_assets',[]) if a.get('url')),None),
        'caption':str((r.get('public_metadata') or {}).get('text') or '')[:240],'candidates':r.get('expanded_identification',{}).get('candidates',[])[:3]} for r in rows]
    note=emit(scope,'ARTICLE_IDENTIFICATION_REQUIRED','ambiguous-group:'+GROUP_KEY,str(len(rows))+' Reels requieren identificación',
        'Se han revisado las señales disponibles. Falta confirmar el proyecto de estos Reels.',
        '/?zar_workspace=sites#reposnewsEditor',entity_id=GROUP_KEY,entity_type='REEL_GROUP',details={'items':items})
    from . import identity_center
    with holdings.transaction(scope):
        saved=holdings.read(scope)
        current=next(n for n in identity_center.ensure(saved)['human_actions'] if n['id']==note['id'])
        if current.get('status')=='DONE' and current.get('outcome')=='IDENTIFICATION_RESOLVED' and not current.get('dismissed_at'):
            current.update(status='ACTION_REQUIRED',read_at=None,outcome=None,completed_at=None)
        current.update(title=str(len(rows))+' Reels requieren identificación',details={'items':items})
        holdings.write(scope,saved)
    return note
