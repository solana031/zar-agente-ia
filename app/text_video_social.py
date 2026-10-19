"""One exact-video confirmation over ZAR's existing social connectors."""
import hashlib
import json
import os
import time
from urllib.parse import quote
import requests
from flask import current_app,jsonify,request
from itsdangerous import URLSafeTimedSerializer,BadSignature
from . import holdings,media_company as media,social_publish as social,text_video as video

PLATFORMS={'instagram','tiktok','youtube'}


def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()


def payload(data):
    platforms=data.get('platforms',[])
    if not isinstance(platforms,list) or not platforms or len(platforms)>3 or any(p not in PLATFORMS for p in platforms):raise ValueError('SELECT_VALID_SOCIAL_PLATFORMS')
    title=str(data.get('title') or '').strip();caption=str(data.get('caption') or '').strip()
    if not 1<=len(title)<=100 or len(caption)>2200:raise ValueError('SOCIAL_TITLE_OR_CAPTION_INVALID')
    youtube_privacy=data.get('youtube_privacy','private');tiktok_privacy=data.get('tiktok_privacy','')
    if youtube_privacy not in {'private','unlisted','public'}:raise ValueError('YOUTUBE_PRIVACY_INVALID')
    if tiktok_privacy not in {'','PUBLIC_TO_EVERYONE','MUTUAL_FOLLOW_FRIENDS','FOLLOWER_OF_CREATOR','SELF_ONLY'}:raise ValueError('TIKTOK_PRIVACY_INVALID')
    return {'platforms':list(dict.fromkeys(platforms)),'title':title,'caption':caption,'youtube_privacy':youtube_privacy,'tiktok_privacy':tiktok_privacy}


def prepared(scope,identifier,data):
    record=video.view(scope,identifier)
    if record.get('video_state')!='READY_PRIVATE' or not record.get('artifact'):raise ValueError('VERIFIED_PRIVATE_VIDEO_REQUIRED')
    options=payload(data);checks={}
    for platform in options['platforms']:
        try:
            if platform=='youtube':
                from .media_adapters import PublishingAdapter
                check=PublishingAdapter().prepare_youtube(scope,options['title'],options['caption'],privacy=options['youtube_privacy'])
                ready=check.get('upload_capability') is True
                checks[platform]={'ready':ready,'account':check.get('channel'),'blocker':None if ready else 'YOUTUBE_CHANNEL_OR_UPLOAD_PERMISSION_NOT_VERIFIED','privacy':options['youtube_privacy']}
            elif platform=='instagram':
                check=social.scoped_instagram_readiness(scope)
                checks[platform]={'ready':check.get('publish_capability')=='AUTHORIZED_NOT_TESTED','account':check.get('account'),'account_id':check.get('account_id'),'blocker':check.get('blocker'),'privacy':'PUBLIC_REEL'}
            else:
                check=social.publishing_readiness('tiktok');privacy=options['tiktok_privacy']
                ready=bool(check.get('connected') and privacy and privacy in check.get('privacy_options',[]) and record['render']['duration']<=float(check.get('max_video_post_duration_sec') or 0))
                checks[platform]={'ready':ready,'account':check.get('account'),'account_id':check.get('account_id'),'privacy_options':check.get('privacy_options',[]),'privacy':privacy,'blocker':None if ready else 'TIKTOK_NOT_CONNECTED' if not check.get('connected') else 'SELECT_AUTHORIZED_TIKTOK_PRIVACY_OR_REVIEW_DURATION'}
        except Exception:checks[platform]={'ready':False,'account':None,'blocker':platform.upper()+'_READ_ONLY_VERIFICATION_FAILED'}
        if platform in record.get('publication',{}):checks[platform].update(ready=False,blocker='PUBLICATION_ALREADY_REQUESTED_CHECK_EXISTING_RESULT')
    plan={'id':identifier,'revision':record.get('video_revision',0),'video_digest':digest(media.video_path(scope,identifier)),
          'options':options,'checks':checks,'ready_to_publish':all(c['ready'] for c in checks.values()),'created_at':time.time(),'dry_run':True,'publication_mode':'CONFIRM_ONCE'}
    plan['approval_request']=URLSafeTimedSerializer(current_app.secret_key,salt='text-video-publish-v1').dumps({'scope':scope,**plan})
    with media._job_lock(scope,identifier) as locked:
        if not locked:raise ValueError('VIDEO_PROJECT_BUSY')
        current=video.view(scope,identifier);current['last_social_dry_run']={k:v for k,v in plan.items() if k!='approval_request'};media._save(scope,identifier,current)
    return plan


def confirm(scope,identifier,data):
    if data.get('confirmed') is not True or data.get('rights_confirmed') is not True:raise ValueError('ONE_EXPLICIT_CONFIRMATION_AND_RIGHTS_REVIEW_REQUIRED')
    try:plan=URLSafeTimedSerializer(current_app.secret_key,salt='text-video-publish-v1').loads(str(data.get('approval_request','')),max_age=900)
    except BadSignature:raise ValueError('SOCIAL_APPROVAL_EXPIRED_OR_INVALID')
    if plan.get('scope')!=scope or plan.get('id')!=identifier or not plan.get('ready_to_publish'):raise ValueError('SOCIAL_DRY_RUN_NOT_READY')
    with media._job_lock(scope,identifier) as locked:
        if not locked:raise ValueError('VIDEO_PROJECT_BUSY')
        record=video.view(scope,identifier)
        if holdings.read(scope).get('global_stop'):raise ValueError('GLOBAL_STOP_ACTIVE')
        if record.get('video_state')!='READY_PRIVATE' or plan['revision']!=record.get('video_revision',0) or plan['video_digest']!=digest(media.video_path(scope,identifier)):raise ValueError('VIDEO_CHANGED_REVIEW_EXACT_RENDER_AGAIN')
        posts=record.setdefault('publication',{})
        if any(p in posts for p in plan['options']['platforms']):return video.summary(identifier,record)['publication']
        signed=URLSafeTimedSerializer(current_app.secret_key,salt='media-export-v1').dumps({'scope':scope,'task':identifier,'project':(record.get('checkpoint') or {}).get('project_id'),'digest':plan['video_digest']})
        for platform in plan['options']['platforms']:
            posts[platform]={'platform':platform,'idempotency_key':hashlib.sha256((identifier+':'+platform).encode()).hexdigest(),'status':'QUEUED','external_id':None,'url':None,'published_at':None,'error':None,
                'options':plan['options'],'account':plan['checks'][platform].get('account_id') or plan['checks'][platform].get('account'),
                'public_video_url':'https://web-production-a9565.up.railway.app/media-public/'+signed+'.mp4','approved_at':holdings._now(),'rights_confirmed':True,'video_digest':plan['video_digest']}
        record['review_approved']=True;media._save(scope,identifier,record)
    video.start_worker(scope)
    return video.summary(identifier,record)['publication']


def notify(scope,identifier,post):
    from .notification_center import emit
    success=post['status'] in {'PUBLISHED','UPLOADED_PRIVATE','UPLOADED_UNLISTED'}
    message={'PUBLISHED':'La red confirma la publicación.','UPLOADED_PRIVATE':'Subida completada como vídeo privado.','UPLOADED_UNLISTED':'Subida completada como vídeo no listado.'}.get(post['status'],'Comprueba el estado en la cuenta antes de repetir el envío.')
    emit(scope,'PUBLISH_SUCCESS' if success else 'PUBLISH_FAILED','video-publication:'+identifier+':'+post['platform']+':'+post['status'],
         ('Publicación completada · ' if success else 'Revisar publicación · ')+post['platform'].title(),message,
         post.get('url') or '/video-project/'+identifier,identifier,'VIDEO_PROJECT',details={'platform':post['platform'],'status':post['status'],'external_id':post.get('external_id')},status='COMPLETED' if success else 'ACTION_REQUIRED')


def advance(scope,task,record):
    if holdings.read(scope).get('global_stop'):return
    for platform,post in record.get('publication',{}).items():
        state=post['status']
        if state not in {'QUEUED','REQUESTED','PENDING'}:continue
        if post.get('next_poll',0)>time.time():continue
        try:
            if state=='REQUESTED':post.update(status='UNKNOWN',error='SUBMISSION_OUTCOME_UNKNOWN_CHECK_ACCOUNT_BEFORE_RETRY')
            elif state=='QUEUED':
                if record.get('video_state')!='READY_PRIVATE' or post['video_digest']!=digest(media.video_path(scope,task['id'])):raise ValueError('APPROVED_VIDEO_CHANGED_OR_CANCELLED')
                if platform=='instagram' and str(social.instagram_context(scope)['user'])!=str(post.get('account')):raise ValueError('INSTAGRAM_TARGET_ACCOUNT_CHANGED')
                if platform=='youtube':
                    from .media_adapters import PublishingAdapter
                    check=PublishingAdapter().prepare_youtube(scope,post['options']['title'],post['options']['caption'],privacy=post['options']['youtube_privacy'])
                    if not check.get('upload_capability') or (check.get('channel') or {}).get('id')!=(post.get('account') or {}).get('id'):raise ValueError('YOUTUBE_TARGET_ACCOUNT_OR_PERMISSION_CHANGED')
                if platform=='tiktok':
                    check=social.publishing_readiness('tiktok')
                    if not check.get('connected') or check.get('account_id')!=post.get('account'):raise ValueError('TIKTOK_TARGET_ACCOUNT_CHANGED')
                post['status']='REQUESTED';media._save(scope,task['id'],record)
                options=post['options']
                if platform=='youtube':
                    from .media_adapters import PublishingAdapter
                    result=PublishingAdapter().youtube(media.video_path(scope,task['id']),options['title'],options['caption'],scope_id=scope,privacy=options['youtube_privacy'])
                    if not result.get('id'):raise ValueError('YOUTUBE_UPLOAD_ID_UNVERIFIED')
                    post.update(status='PENDING',external_id=result['id'],url=result.get('url'))
                elif platform=='tiktok':
                    result=social.tiktok_direct_post(post['public_video_url'],options['caption'],privacy=options['tiktok_privacy'],confirmed=True)
                    publish_id=(result.get('data') or {}).get('publish_id')
                    if not publish_id:raise ValueError('TIKTOK_PUBLISH_ID_UNVERIFIED')
                    post.update(status='PENDING',publish_id=publish_id,external_id=publish_id)
                else:
                    result=social.instagram_reel(post['public_video_url'],options['caption'],confirmed=True,scope_id=scope)
                    identifier=result.get('id') or (result.get('media') or {}).get('id')
                    if identifier:
                        post.update(status='PUBLISHED',external_id=identifier,published_at=holdings._now());media._save(scope,task['id'],record)
                        post['url']=social.instagram_permalink(scope,identifier)
                    elif result.get('container_id') and result.get('pending_publish'):post.update(status='PENDING',container_id=result['container_id'])
                    else:raise ValueError('INSTAGRAM_SUBMISSION_UNVERIFIED')
            else:poll(scope,task,record,post)
            post['next_poll']=time.time()+20
        except Exception as exc:
            # The persisted intent is authoritative. Never turn a timeout into a repost.
            if post['status']=='PUBLISHED' and post.get('external_id'):post['error']='PERMALINK_NOT_VERIFIED'
            elif state=='PENDING' and not post.get('commit_intent'):
                post['read_errors']=post.get('read_errors',0)+1;post['next_poll']=time.time()+min(300,20*2**min(post['read_errors'],4))
            elif post['status']=='QUEUED':post.update(status='BLOCKED',error=str(exc) if isinstance(exc,ValueError) else 'SOCIAL_READINESS_CHANGED')
            else:post.update(status='UNKNOWN',error='PROVIDER_DID_NOT_CONFIRM_CHECK_ACCOUNT_BEFORE_RETRY')
        media._save(scope,task['id'],record)
        if post['status'] not in {'QUEUED','REQUESTED','PENDING','CANCELLED'}:notify(scope,task['id'],post)
        return


def poll(scope,task,record,post):
    platform=post['platform']
    if platform=='youtube':
        from .youtube import _service
        response=_service(user_id=scope).videos().list(part='status,processingDetails',id=post['external_id']).execute()
        row=next(iter(response.get('items',[])),{});state=row.get('status',{});processing=row.get('processingDetails',{}).get('processingStatus')
        if state.get('uploadStatus') in {'failed','rejected','deleted'} or processing in {'failed','terminated'}:post.update(status='FAILED',error='YOUTUBE_PROCESSING_FAILED')
        elif state.get('uploadStatus')=='processed' or processing=='succeeded':
            privacy=state.get('privacyStatus')
            if privacy in {'private','unlisted','public'}:post.update(status='PUBLISHED' if privacy=='public' else 'UPLOADED_'+privacy.upper(),published_at=holdings._now())
        return
    if platform=='tiktok':
        response=requests.post('https://open.tiktokapis.com/v2/post/publish/status/fetch/',headers={'Authorization':'Bearer '+os.environ.get('TIKTOK_ACCESS_TOKEN','')},json={'publish_id':post['publish_id']},timeout=20,allow_redirects=False)
        if not response.ok:return
        data=response.json().get('data') or {}
        if data.get('status')=='FAILED':post.update(status='FAILED',error='TIKTOK_PROVIDER_REPORTED_FAILURE')
        elif data.get('status')=='PUBLISH_COMPLETE':
            ids=data.get('publicaly_available_post_id') or [];external=str(ids[0]) if ids else post['publish_id']
            post.update(status='PUBLISHED',external_id=external,published_at=holdings._now())
            if ids and isinstance(post.get('account'),str):post['url']='https://www.tiktok.com/@'+quote(post['account'],safe='')+'/video/'+quote(external,safe='')
        return
    context=social.instagram_context(scope);base=context['base'];headers={'Authorization':'Bearer '+context['token']}
    response=requests.get(base+'/'+post['container_id'],params={'fields':'status_code'},headers=headers,timeout=20,allow_redirects=False)
    if not response.ok:return
    status=response.json().get('status_code')
    if status in {'ERROR','EXPIRED'}:post.update(status='FAILED',error='INSTAGRAM_CONTAINER_'+status)
    elif status=='FINISHED' and not post.get('commit_intent'):
        if post.get('cancel_requested'):post.update(status='CANCELLED',error=None);return
        post['commit_intent']=True;media._save(scope,task['id'],record)
        result=requests.post(base+'/'+context['user']+'/media_publish',data={'creation_id':post['container_id']},headers=headers,timeout=25,allow_redirects=False)
        if not result.ok:raise ValueError('INSTAGRAM_PUBLISH_UNCONFIRMED')
        identifier=result.json().get('id')
        if not identifier:raise ValueError('INSTAGRAM_PUBLISH_ID_UNVERIFIED')
        post.update(status='PUBLISHED',external_id=identifier,published_at=holdings._now())
        link=requests.get(base+'/'+identifier,params={'fields':'permalink'},headers=headers,timeout=15,allow_redirects=False)
        if link.ok:
            url=link.json().get('permalink')
            if isinstance(url,str) and url.startswith('https://www.instagram.com/'):post['url']=url
    elif status=='PUBLISHED' and post.get('commit_intent'):post.update(status='UNKNOWN',error='INSTAGRAM_POST_EXISTS_ID_REQUIRES_RECONCILIATION')


def register(app,scope_fn,csrf_owner):
    @app.post('/api/video-projects/<identifier>/social/<action>')
    def video_social_api(identifier,action):
        scope=csrf_owner()
        try:
            data=request.get_json(silent=True) or {}
            if action=='prepare':result=prepared(scope,identifier,data)
            elif action=='confirm':result=confirm(scope,identifier,data)
            else:raise ValueError('INVALID_SOCIAL_ACTION')
            return jsonify(ok=True,result=result)
        except ValueError as exc:return jsonify(ok=False,error=str(exc)),400
