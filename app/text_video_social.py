"""One exact-video confirmation over ZAR's existing social connectors."""
import hashlib
import json
import os
import secrets
import subprocess
import time
from urllib.parse import quote
import requests
from flask import current_app,jsonify,request
from itsdangerous import URLSafeTimedSerializer,BadSignature
from . import holdings,media_company as media,social_publish as social,text_video as video

PLATFORMS={'instagram','tiktok','youtube'}
OPERATIONAL_EMAIL='zaragente031@gmail.com'


def _provider_connections(scope,only=None):
    """Existing credentials only. Provider operations here are identity/status reads."""
    from . import cloud_auth,identity_center
    results={}
    for platform in sorted(PLATFORMS if only is None else PLATFORMS.intersection(only)):
        item={'status':'UNKNOWN','ready':False,'account':None,'permissions':[], 'last_verified':holdings._now()}
        try:
            if platform=='instagram':
                check=social.scoped_instagram_readiness(scope)
                item.update(check,ready=check.get('publish_capability')=='AUTHORIZED_NOT_TESTED')
                item['status']=check.get('status') or ('CONNECTED' if item['ready'] else 'AUTH_REQUIRED')
                item.update(connect_url='/api/reposnews/instagram/connect?publishing=1',human_action='Reconectar Instagram @zaragente031')
            elif platform=='tiktok':
                # The existing connector is backend-token based; there is no TikTok OAuth route.
                check=social.publishing_readiness('tiktok')
                item.update(check,permissions=['video.publish'] if check.get('connected') else [],
                            status=check.get('status') or ('CONNECTED' if check.get('connected') else 'DISCONNECTED'),
                            ready=bool(check.get('connected') and check.get('privacy_options')),
                            connect_url='https://developers.tiktok.com/apps/',
                            human_action='Conectar cuenta operacional ZAR en la app TikTok existente y guardar TIKTOK_ACCESS_TOKEN en Railway principal; autorizar video.publish. No existe OAuth TikTok en ZAR.')
                if check.get('connected') and check.get('account_id')!='zaragente031':
                    item.update(status='ERROR',ready=False,blocker='TIKTOK_OPERATIONAL_IDENTITY_NOT_VERIFIED')
            else:
                item.update(connect_url=identity_center.connect_url(OPERATIONAL_EMAIL,'youtube'),
                            human_action='Autorizar YouTube con '+OPERATIONAL_EMAIL+' (lectura del canal y youtube.upload).',status='AUTH_REQUIRED')
                creds=cloud_auth.get_credentials(user_id=cloud_auth.youtube_user_id(scope)) or cloud_auth.get_credentials(user_id=scope)
                if creds:
                    actual=cloud_auth.get_account_email(creds)
                    if actual!=OPERATIONAL_EMAIL:
                        item.update(status='ERROR',blocker='YOUTUBE_OPERATIONAL_IDENTITY_MISMATCH')
                    else:
                        granted=set(creds.scopes or []);item.update(account=actual,permissions=sorted(granted.intersection({identity_center.PREFIX+'youtube.readonly',identity_center.PREFIX+'youtube.upload'})))
                        if identity_center.PREFIX+'youtube.readonly' not in granted:
                            item['status']='PERMISSION_REQUIRED'
                        else:
                            response=requests.get('https://www.googleapis.com/youtube/v3/channels',
                                params={'mine':'true','part':'id,snippet'},headers={'Authorization':'Bearer '+creds.token},timeout=20,allow_redirects=False)
                            if not response.ok:
                                item.update(status='REAUTH_REQUIRED' if response.status_code==401 else 'ERROR',blocker='YOUTUBE_CHANNEL_HTTP_'+str(response.status_code))
                            else:
                                rows=response.json().get('items',[])
                                channels=[{'id':r['id'],'title':r.get('snippet',{}).get('title'),'handle':r.get('snippet',{}).get('customUrl')} for r in rows]
                                ready=bool(channels and identity_center.PREFIX+'youtube.upload' in granted)
                                item.update(channel=channels[0] if channels else None,ready=ready,
                                            status='CONNECTED' if ready else 'CHANNEL_REQUIRED' if not channels else 'PERMISSION_REQUIRED')
                                if not channels:item.update(connect_url='https://www.youtube.com/account',human_action='Crear/verificar personalmente el canal operacional de '+OPERATIONAL_EMAIL+' y volver a verificar.')
        except Exception:
            item.update(status='ERROR',ready=False,blocker=platform.upper()+'_READ_ONLY_VERIFICATION_FAILED')
        item['upload_ready']=item['ready']
        if item['ready']:item['human_action']=None
        results[platform]=item
    # Legacy readers keep the same safe observations; actions belong to the registry.
    with holdings.transaction(scope):
        data=holdings.read(scope);data.setdefault('social_connections',{}).update(results)
        holdings.write(scope,data)
    return results


def connections(scope,only=None):
    from .account_connections import social_connections
    return social_connections(scope,only)


def validate_video(path):
    if not path.is_file() or not path.stat().st_size:raise ValueError('VIDEO_FILE_REQUIRED')
    try:response=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,timeout=20)
    except (OSError,subprocess.TimeoutExpired):raise ValueError('VIDEO_PROBE_UNAVAILABLE')
    if response.returncode:raise ValueError('VIDEO_INVALID')
    info=json.loads(response.stdout);streams=info.get('streams',[])
    stream=next((s for s in streams if s.get('codec_type')=='video'),{})
    audio=next((s for s in streams if s.get('codec_type')=='audio'),{})
    result={'duration':float(info.get('format',{}).get('duration',0)), 'width':stream.get('width',0),'height':stream.get('height',0),
            'codec':stream.get('codec_name'),'audio_codec':audio.get('codec_name'),'size':path.stat().st_size}
    if result['duration']<=0 or not result['width'] or not result['height']:raise ValueError('VIDEO_INVALID')
    valid=(result['codec']=='h264' and result['audio_codec']=='aac' and result['width']==1080 and result['height']==1920)
    result['platforms']={p:('INVALID' if result['duration']>180 or result['size']>video.MAX_VIDEO else 'SUPPORTED' if valid else 'NEEDS_TRANSCODE') for p in PLATFORMS}
    return result


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
    description=str(data.get('description',caption)).strip();hashtags=data.get('hashtags',[])
    if len(description)>5000 or not isinstance(hashtags,list) or any(not isinstance(h,str) or len(h)>100 for h in hashtags) or len(hashtags)>30:raise ValueError('SOCIAL_METADATA_INVALID')
    if data.get('schedule'):raise ValueError('SCHEDULE_NOT_SUPPORTED_BY_ALL_SELECTED_ADAPTERS')
    caption=' '.join([caption]+['#'+h.lstrip('#') for h in hashtags]).strip()
    if len(caption)>2200:raise ValueError('SOCIAL_CAPTION_TOO_LONG')
    return {'platforms':sorted(set(platforms)),'title':title,'caption':caption,'description':description,'hashtags':hashtags,'youtube_privacy':youtube_privacy,'tiktok_privacy':tiktok_privacy}


def prepared(scope,identifier,data):
    record=video.view(scope,identifier)
    if record.get('video_state')!='READY_PRIVATE' or not record.get('artifact'):raise ValueError('VERIFIED_PRIVATE_VIDEO_REQUIRED')
    options=payload(data);checks={};file=media.video_path(scope,identifier);validation=validate_video(file)
    verified=connections(scope,options['platforms'])
    for platform in options['platforms']:
        try:
            if platform=='youtube':
                check=verified[platform]
                ready=check.get('ready') is True
                checks[platform]={'ready':ready,'account':check.get('channel'),'blocker':None if ready else 'YOUTUBE_CHANNEL_OR_UPLOAD_PERMISSION_NOT_VERIFIED','privacy':options['youtube_privacy']}
            elif platform=='instagram':
                check=verified[platform]
                checks[platform]={'ready':check.get('publish_capability')=='AUTHORIZED_NOT_TESTED','account':check.get('account'),'account_id':check.get('account_id'),'blocker':check.get('blocker'),'privacy':'PUBLIC_REEL'}
            else:
                check=verified[platform];privacy=options['tiktok_privacy']
                ready=bool(check.get('ready') and privacy and privacy in check.get('privacy_options',[]) and validation['duration']<=float(check.get('max_video_post_duration_sec') or 0))
                checks[platform]={'ready':ready,'account':check.get('account'),'account_id':check.get('account_id'),'privacy_options':check.get('privacy_options',[]),'privacy':privacy,'blocker':None if ready else 'TIKTOK_NOT_CONNECTED' if not check.get('connected') else 'SELECT_AUTHORIZED_TIKTOK_PRIVACY_OR_REVIEW_DURATION'}
        except Exception:checks[platform]={'ready':False,'account':None,'blocker':platform.upper()+'_READ_ONLY_VERIFICATION_FAILED'}
        checks[platform].update(status=verified[platform]['status'],human_action=verified[platform].get('human_action'),connect_url=verified[platform].get('connect_url'))
        if validation['platforms'][platform]!='SUPPORTED':checks[platform].update(ready=False,blocker=validation['platforms'][platform])
        checks[platform]['validation']=validation['platforms'][platform] if checks[platform]['ready'] else 'AUTH_REQUIRED' if validation['platforms'][platform]=='SUPPORTED' else validation['platforms'][platform]
        if platform in record.get('publication',{}) and record['publication'][platform].get('status') not in {'BLOCKED','FAILED'}:checks[platform].update(ready=False,blocker='PUBLICATION_ALREADY_REQUESTED_CHECK_EXISTING_RESULT')
    plan={'id':identifier,'revision':record.get('video_revision',0),'video_digest':digest(media.video_path(scope,identifier)),
          'options':options,'checks':checks,'validation':validation,'ready_to_publish':all(c['ready'] for c in checks.values()),'created_at':time.time(),'dry_run':True,'publication_mode':'CONFIRM_ONCE'}
    plan['platform_payloads']={p:({'snippet':{'title':options['title'],'description':options['description'],'tags':options['hashtags']},'status':{'privacyStatus':options['youtube_privacy']}} if p=='youtube' else {'media_type':'REELS','caption':options['caption']} if p=='instagram' else {'post_info':{'title':options['caption'],'privacy_level':options['tiktok_privacy'],'is_aigc':True}}) for p in options['platforms']}
    plan['approval_request']=URLSafeTimedSerializer(current_app.secret_key,salt='text-video-publish-v1').dumps({'scope':scope,**plan})
    with media._job_lock(scope,identifier) as locked:
        if not locked:raise ValueError('VIDEO_PROJECT_BUSY')
        current=video.view(scope,identifier)
        if current.get('video_revision',0)!=plan['revision'] or digest(file)!=plan['video_digest']:raise ValueError('VIDEO_CHANGED_DURING_PREFLIGHT')
        current['last_social_dry_run']={k:v for k,v in plan.items() if k!='approval_request'};media._save(scope,identifier,current)
    return plan


def confirm(scope,identifier,data):
    if data.get('confirmed') is not True or data.get('rights_confirmed') is not True:raise ValueError('ONE_EXPLICIT_CONFIRMATION_AND_RIGHTS_REVIEW_REQUIRED')
    try:plan=URLSafeTimedSerializer(current_app.secret_key,salt='text-video-publish-v1').loads(str(data.get('approval_request','')),max_age=900)
    except BadSignature:raise ValueError('SOCIAL_APPROVAL_EXPIRED_OR_INVALID')
    if plan.get('scope')!=scope or plan.get('id')!=identifier or not plan.get('ready_to_publish'):raise ValueError('SOCIAL_DRY_RUN_NOT_READY')
    with media._job_lock(scope,identifier) as locked:
        if not locked:raise ValueError('VIDEO_PROJECT_BUSY')
        record=video.view(scope,identifier)
        if record.get('last_social_dry_run',{}).get('options')!=plan['options'] or ('options' in data and payload(data['options'])!=plan['options']):raise ValueError('PUBLICATION_METADATA_CHANGED_REVIEW_AGAIN')
        if holdings.read(scope).get('global_stop'):raise ValueError('GLOBAL_STOP_ACTIVE')
        if record.get('video_state')!='READY_PRIVATE' or plan['revision']!=record.get('video_revision',0) or plan['video_digest']!=digest(media.video_path(scope,identifier)):raise ValueError('VIDEO_CHANGED_REVIEW_EXACT_RENDER_AGAIN')
        posts=record.setdefault('publication',{})
        if any(p in posts and posts[p].get('status') not in {'BLOCKED','FAILED'} for p in plan['options']['platforms']):return video.summary(identifier,record)['publication']
        approval={'approval_id':secrets.token_hex(16),'approval_status':'APPROVED_BY_USER','video_revision_id':plan['revision'],
                  'selected_platforms':plan['options']['platforms'],'approved_at':holdings._now(),'approved_by_user':scope,'options':plan['options'],'video_digest':plan['video_digest']}
        record.setdefault('social_approvals',[]).append(approval)
        signed=URLSafeTimedSerializer(current_app.secret_key,salt='media-export-v1').dumps({'scope':scope,'task':identifier,'project':(record.get('checkpoint') or {}).get('project_id'),'digest':plan['video_digest']})
        for platform in plan['options']['platforms']:
            previous=posts.get(platform,{})
            if previous:record.setdefault('publication_history',[]).append(previous.copy())
            posts[platform]={'platform':platform,'approval_id':approval['approval_id'],'video_revision_id':plan['revision'],'attempt_count':previous.get('attempt_count',0),'idempotency_key':hashlib.sha256((identifier+':'+str(plan['revision'])+':'+platform).encode()).hexdigest(),'status':'QUEUED','external_id':None,'url':None,'published_at':None,'error':None,
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
    posts=video.view(scope,identifier).get('publication',{})
    if posts and all(p['status'] not in {'QUEUED','REQUESTED','PENDING'} for p in posts.values()):
        completed=[p for p in posts.values() if p['status'] in {'PUBLISHED','UPLOADED_PRIVATE','UPLOADED_UNLISTED'}]
        failed=[p for p in posts.values() if p['status'] in {'BLOCKED','FAILED'}]
        actions=[{'label':'VER '+p['platform'].upper(),'url':p['url']} for p in completed if p.get('url')]
        actions += [{'label':'REINTENTAR '+p['platform'].upper(),'url':'/video-project/'+identifier+'#publish'} for p in failed]
        key='social-result:'+identifier+':'+hashlib.sha256(json.dumps({p:r['status'] for p,r in posts.items()},sort_keys=True).encode()).hexdigest()
        emit(scope,'PUBLISH_SUCCESS' if len(completed)==len(posts) else 'PUBLISH_FAILED',key,
             'PUBLICACIÓN COMPLETADA' if len(completed)==len(posts) else 'PUBLICACIÓN PARCIAL' if completed else 'PUBLICACIÓN BLOQUEADA',
             str(len(completed))+'/'+str(len(posts))+' destinos completados. Reintentar solo destinos fallidos tras revisión.',
             '/video-project/'+identifier+'#publish',identifier,'VIDEO_PROJECT',actions or None)


def advance(scope,task,record):
    if holdings.read(scope).get('global_stop'):return
    for platform,post in record.get('publication',{}).items():
        state=post['status']
        if state not in {'QUEUED','REQUESTED','PENDING'}:continue
        if post.get('next_poll',0)>time.time():continue
        try:
            if state=='REQUESTED':post.update(status='UNKNOWN',error='SUBMISSION_OUTCOME_UNKNOWN_CHECK_ACCOUNT_BEFORE_RETRY')
            elif state=='QUEUED':
                approval=next((a for a in record.get('social_approvals',[]) if a.get('approval_id')==post.get('approval_id')),None)
                if not approval or approval.get('approval_status')!='APPROVED_BY_USER' or platform not in approval['selected_platforms'] or approval['video_revision_id']!=record.get('video_revision',0) or approval['options']!=post['options'] or approval['video_digest']!=post['video_digest'] or record.get('last_social_dry_run',{}).get('options')!=post['options']:raise ValueError('EXACT_USER_APPROVAL_REQUIRED')
                if record.get('video_state')!='READY_PRIVATE' or post['video_digest']!=digest(media.video_path(scope,task['id'])):raise ValueError('APPROVED_VIDEO_CHANGED_OR_CANCELLED')
                if platform=='instagram' and str(social.instagram_context(scope)['user'])!=str(post.get('account')):raise ValueError('INSTAGRAM_TARGET_ACCOUNT_CHANGED')
                if platform=='youtube':
                    from .media_adapters import PublishingAdapter
                    check=PublishingAdapter().prepare_youtube(scope,post['options']['title'],post['options']['caption'],privacy=post['options']['youtube_privacy'])
                    if not check.get('upload_capability') or (check.get('channel') or {}).get('id')!=(post.get('account') or {}).get('id'):raise ValueError('YOUTUBE_TARGET_ACCOUNT_OR_PERMISSION_CHANGED')
                if platform=='tiktok':
                    check=social.publishing_readiness('tiktok')
                    if not check.get('connected') or check.get('account_id')!=post.get('account'):raise ValueError('TIKTOK_TARGET_ACCOUNT_CHANGED')
                post['status']='REQUESTED';post['attempt_count']=post.get('attempt_count',0)+1;media._save(scope,task['id'],record)
                options=post['options']
                if platform=='youtube':
                    from .media_adapters import PublishingAdapter
                    result=PublishingAdapter().youtube(media.video_path(scope,task['id']),options['title'],options['description'],scope_id=scope,privacy=options['youtube_privacy'],tags=options['hashtags'])
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
        post['last_error']=post.get('error');post['public_url']=post.get('url');media._save(scope,task['id'],record)
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
        approval=next((a for a in record.get('social_approvals',[]) if a.get('approval_id')==post.get('approval_id')),None)
        if not approval or approval.get('approval_status')!='APPROVED_BY_USER' or approval.get('video_revision_id')!=record.get('video_revision',0) or approval.get('options')!=post.get('options') or approval.get('video_digest')!=digest(media.video_path(scope,task['id'])):
            post.update(status='BLOCKED',error='EXACT_USER_APPROVAL_REQUIRED');return
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
    @app.post('/api/social/connections/readiness')
    def social_connections_api():
        scope=csrf_owner()
        return jsonify(ok=True,result=connections(scope))
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
