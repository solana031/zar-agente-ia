"""Notification view over the existing persistent Human Action Center."""
import secrets
from flask import jsonify, request, session
from . import holdings, identity_center

TYPES={'ARTICLE_READY','ARTICLE_UPDATE_READY','ARTICLE_NEEDS_DISAMBIGUATION','ARTICLE_FAILED','DOC_READY','SLIDES_READY','SHEET_READY','FORM_READY','VIDEO_READY','PUBLISH_SUCCESS','PUBLISH_FAILED','WORKER_OFFLINE','WORKER_SESSION_EXPIRED','SYSTEM_ACTION_REQUIRED'}
TYPES.update({'ACCOUNT_CONNECTION','MIRROR_SYNC_SUCCESS','MIRROR_SYNC_FAILED','MIRROR_OUTDATED'})


def emit(scope,kind,key,title,message,deep_link,entity_id='',entity_type='',actions=None,details=None,status='ACTION_REQUIRED',priority='P1'):
    if kind not in TYPES:raise ValueError('INVALID_NOTIFICATION_TYPE')
    with holdings.transaction(scope):
        data=holdings.read(scope);center=identity_center.ensure(data)
        row=next((x for x in center['human_actions'] if x.get('notification_key')==key),None)
        if row:return row
        row=identity_center.queue(center,'REPOSNEWS' if kind.startswith('ARTICLE') else 'WORKSPACE' if kind.endswith('_READY') else 'ZAR',kind,message,deep_link,[],plan_id=key)
        row.update(notification_key=key,type=kind,title=title,message=message,read_at=None,status=status,priority=priority,
                   entity_type=entity_type,entity_id=entity_id,actions=actions or [{'label':'VER','url':deep_link}],deep_link=deep_link,details=details or {})
        holdings.write(scope,data);return row


def view(scope):
    from . import reposnews as rn, instagram_local_queue
    worker=instagram_local_queue.status()
    if rn.read().get('owner')==scope:
        if worker.get('session')=='EXPIRED':emit(scope,'WORKER_SESSION_EXPIRED','worker-session-expired','Instagram requiere iniciar sesión','Abre el perfil exclusivo del worker y renueva la sesión local.','/?zar_workspace=sites#reposnewsEditor',entity_type='WORKER')
        elif worker.get('state')=='OFFLINE':emit(scope,'WORKER_OFFLINE','worker-offline','Worker de Reels desconectado','Los trabajos permanecen en cola hasta que el PC y el worker estén disponibles.','/?zar_workspace=sites#reposnewsEditor',entity_type='WORKER')
    with holdings.transaction(scope):
        data=holdings.read(scope);rows=identity_center.ensure(data)['human_actions']
        result=[]
        for row in rows:
            editorial=row.get('editorial') or {}
            kind=('ARTICLE_FAILED' if editorial.get('status') in {'FAILED_RETRYABLE','FAILED_PERMANENT'} else 'ARTICLE_NEEDS_DISAMBIGUATION' if editorial.get('status')=='NEEDS_DISAMBIGUATION' else 'ARTICLE_READY') if editorial else row.get('type') or 'SYSTEM_ACTION_REQUIRED'
            if editorial:row['type']=kind
            row.setdefault('type',kind);row.setdefault('read_at',None);row.setdefault('priority','P1')
            row.setdefault('entity_id',row.get('article_id') or row.get('inbox_item_id') or row['id'])
            row.setdefault('entity_type','ARTICLE' if editorial else 'SYSTEM')
            row.setdefault('message',row.get('reason',''));row.setdefault('deep_link',row.get('url') or '/?zar_workspace=human')
            if not row.get('notification_key') and not editorial and row.get('status')=='DONE':row['read_at']=row.get('read_at') or row.get('completed_at') or row.get('created_at')
            if row.get('notification_key') in {'worker-offline','worker-session-expired'} and worker.get('state')=='ONLINE' and worker.get('session')=='CONNECTED':row['status']='DONE'
            if row.get('type')=='ARTICLE_UPDATE_READY' and rn.read().get('owner')==scope:
                revision=next((r for r in rn.read().get('article_revisions',[]) if r['article_revision_id']==row.get('entity_id')),None)
                if revision and revision['state']!='ARTICLE_UPDATE_DRAFT':row['status']='DONE'
            item=dict(row,completed=row.get('status') in {'DONE','COMPLETED','PUBLISHED','CANCELLED','IGNORED'})
            if editorial and rn.read().get('owner')==scope:
                inbox=next((r for r in rn.read().get('instagram_inbox',[]) if r['id']==row.get('inbox_item_id')),None)
                if inbox:
                    item['processing']=bool(inbox.get('reprocess_round') and inbox.get('status') in {'WAITING_LOCAL_WORKER','OPENING_INSTAGRAM','FETCHING_VIDEO','VIDEO_DOWNLOADED','TRANSCRIBING','ANALYZING','FETCHING_MEDIA','BROWSING','IDENTIFYING','RESEARCHING','DRAFTING_ES','DRAFTING_EN','ASSETS','SEO','RECEIVED'})
                    if editorial.get('status') in {'NEEDS_DISAMBIGUATION','FAILED_RETRYABLE','FAILED_PERMANENT'} and inbox.get('status') in {'READY_PRIVATE','NO_CHANGE','ARTICLE_UPDATE_DRAFT','PUBLISHED','DISCARDED','CANCELLED'}:
                        row['status']='DONE';item.update(status='DONE',completed=True)
            if editorial.get('article_id') and rn.read().get('owner')==scope:
                article=next((a for a in rn.state(scope).get('articles',[]) if a['id']==editorial['article_id']),None)
                if article:item['article']=article
            if row.get('type')=='ARTICLE_UPDATE_READY' and rn.read().get('owner')==scope:
                from .reposnews_revisions import token
                revision=next((r for r in rn.read().get('article_revisions',[]) if r['article_revision_id']==row.get('entity_id')),None)
                if revision and revision['state']=='ARTICLE_UPDATE_DRAFT':item['approval_request']=token(scope,revision)
            result.append(item)
        holdings.write(scope,data)
    result.sort(key=lambda x:x.get('created_at',''),reverse=True)
    from .reposnews_history import summary
    return {'items':result,'unread':sum(not x.get('read_at') and not x.get('dismissed_at') for x in result),'worker':worker,'historical':summary(rn.read()) if rn.read().get('owner')==scope else {}}


def mark(scope,payload):
    with holdings.transaction(scope):
        data=holdings.read(scope)
        for row in identity_center.ensure(data)['human_actions']:
            if payload.get('all') or row['id']==payload.get('id'):
                if 'dismissed' in payload:
                    row['dismissed_at']=holdings._now() if payload['dismissed'] else None
                    if payload['dismissed']:row['read_at']=row.get('read_at') or holdings._now()
                else:row['read_at']=None if payload.get('unread') else holdings._now()
        holdings.write(scope,data)
    return view(scope)


def register(app,scope_fn):
    @app.get('/api/notifications')
    def notifications_get():
        if session.get('zar_auth') is not True:return jsonify(ok=False,error='AUTH_REQUIRED'),401
        return jsonify(ok=True,csrf=session.setdefault('business_csrf',secrets.token_urlsafe(32)),**view(scope_fn()))

    @app.post('/api/notifications/read')
    def notifications_read():
        if session.get('zar_auth') is not True:return jsonify(ok=False,error='AUTH_REQUIRED'),401
        csrf=session.get('business_csrf','')
        if not csrf or not secrets.compare_digest(csrf,request.headers.get('X-ZAR-Business-CSRF','')):return jsonify(ok=False,error='CSRF_REQUIRED'),403
        return jsonify(ok=True,**mark(scope_fn(),request.get_json(silent=True) or {}))
