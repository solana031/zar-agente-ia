"""Notification view over the existing persistent Human Action Center."""
import secrets
import re
from flask import jsonify, request, session
from . import holdings, identity_center

TYPES={'ARTICLE_READY','ARTICLE_UPDATE_READY','ARTICLE_NEEDS_DISAMBIGUATION','ARTICLE_FAILED','DOC_READY','SLIDES_READY','SHEET_READY','FORM_READY','VIDEO_READY','PUBLISH_SUCCESS','PUBLISH_FAILED','WORKER_OFFLINE','WORKER_SESSION_EXPIRED','SYSTEM_ACTION_REQUIRED'}
TYPES.update({'ACCOUNT_CONNECTION','MIRROR_SYNC_SUCCESS','MIRROR_SYNC_FAILED','MIRROR_OUTDATED'})
TYPES.update({'INSTAGRAM_HISTORY_SYNC','SOCIAL_ACCOUNT_READY','SOCIAL_ACCOUNT_BLOCKED'})
TYPES.update({'ARTICLE_COVER_GENERATED','ARTICLE_COVER_FAILED'})
TYPES.add('ARTICLE_IDENTIFICATION_REQUIRED')


def reconcile_actions(rows,editorial,connections=None):
    """Resolve proven obsolete actions, retaining their history and real blockers."""
    seen={};resolved=0;connections=connections or {}
    inbox={r['id']:r for r in editorial.get('instagram_inbox',[])}
    job=editorial.get('ambiguous_reprocessing',{})
    grouped_ids=set(job.get('ids',[])) if len(job.get('completed',[]))==len(job.get('ids',[])) and job.get('ids') else set()
    grouped_sources={inbox[i].get('source_url') for i in grouped_ids if i in inbox}
    for row in reversed(rows):
        if row.get('status') in {'DONE','COMPLETED','CANCELLED','PUBLISHED','IGNORED'}:continue
        details=row.get('editorial') or row.get('details') or {}
        kind=row.get('type') or row.get('action','')
        item=inbox.get(row.get('inbox_item_id') or details.get('inbox_item_id') or row.get('entity_id'))
        reason=None
        if item and kind in {'ARTICLE_FAILED','ARTICLE_NEEDS_DISAMBIGUATION'}:
            if item.get('status') in {'READY_PRIVATE','ARTICLE_UPDATE_DRAFT','NO_CHANGE','PUBLISHED','CANCELLED','DISCARDED'}:reason='SOURCE_RESOLVED'
            elif item['id'] in grouped_ids or item.get('source_url') and item.get('source_url') in grouped_sources:reason='GROUPED_IDENTIFICATION'
        if kind=='ARTICLE_IDENTIFICATION_REQUIRED' and not any(inbox.get(i,{}).get('status')=='NEEDS_DISAMBIGUATION' for i in grouped_ids):reason='IDENTIFICATION_RESOLVED'
        account=row.get('entity_id') if kind in {'ACCOUNT_CONNECTION','SOCIAL_ACCOUNT_BLOCKED'} else str(row.get('service','')).lower()
        cached=connections.get(account,{})
        if cached.get('status') in {'CONNECTED','UPLOAD_READY'} and not cached.get('human_action') and str(cached.get('last_verified') or '')>=str(row.get('created_at') or ''):
            if kind in {'ACCOUNT_CONNECTION','SOCIAL_ACCOUNT_BLOCKED'} or row.get('action') in {'CONNECT','AUTHORIZE','RECONNECT','VERIFY','REAUTH_REQUIRED','PERMISSION_REQUIRED'}:reason='ACCOUNT_VERIFIED'
        key=row.get('notification_key')
        if not key and kind.startswith('ARTICLE'):
            key=(kind,row.get('article_id') or details.get('article_id') or row.get('inbox_item_id') or row.get('entity_id'),details.get('revision'))
        if key and key in seen:reason='DUPLICATE'
        if key:seen[key]=row['id']
        if reason:
            row.update(status='DONE',outcome=reason,completed_at=holdings._now());resolved+=1
    return resolved


def category(item):
    kind=item.get('type','')
    if kind.startswith('ARTICLE') or kind=='INSTAGRAM_HISTORY_SYNC' or item.get('service')=='REPOSNEWS':return 'REPOSNEWS'
    if kind.startswith('SOCIAL') or kind=='VIDEO_READY':return 'SOCIAL'
    if kind in {'ACCOUNT_CONNECTION','ACCOUNT_READY'} or item.get('service') in {'GOOGLE','INSTAGRAM','YOUTUBE','TIKTOK'}:return 'CUENTAS'
    return 'SISTEMA'


def clean(value,depth=0):
    """Bounded diagnostic view; never expose credentials or raw provider traces."""
    if depth>4:return None
    if isinstance(value,dict):return {k:clean(v,depth+1) for k,v in list(value.items())[:20] if not re.search(r'token|secret|password|credential|headers|stack|trace|authorization',k,re.I)}
    if isinstance(value,list):return [clean(v,depth+1) for v in value[:15]]
    if isinstance(value,str):
        value=re.sub(r'https?://\S+[?]\S+','[enlace omitido]',value)
        return re.sub(r'(?i)(?:bearer\s+\S+|(?:sk-|AIza|ghp_|github_pat_|IGQ)[\w-]{8,}|(?:token|password|secret|api[_ -]?key)\s*[:=]\s*\S+)','[oculto]',value)[:1200]
    return value


def article_card(scope,article):
    from .reposnews_automation import request_token,revision
    from .reposnews_covers import CURATED
    item={k:clean(article.get(k)) for k in ('id','title_es','title_en','summary_es','summary_en','repo','state','cover_status','image_kind')}
    item.update(revision=revision(article),languages=[lang.upper() for lang in ('es','en') if article.get('body_'+lang)],
        cover=article.get('cover_thumb') or article.get('cover_url') or ('/media/reposnews/'+(article.get('image_asset') or CURATED[article['id']]) if article.get('image_asset') or article['id'] in CURATED else ''),
        preview='/?zar_workspace=sites&edit_article='+article['id']+'#reposnewsEditor')
    if not article.get('published') and article.get('state') in {'READY','READY_PRIVATE','AWAITING_APPROVAL'}:item['approval_request']=request_token(scope,article)
    return item


def reconcile_ready(scope,data):
    """Also surface legacy standalone drafts, without duplicating existing editorial events."""
    from .reposnews_automation import reviewable,revision
    actions=identity_center.ensure(holdings.read(scope))['human_actions']
    for article in data.get('articles',[]):
        if article.get('published') or article.get('state') not in {'READY_PRIVATE','READY','AWAITING_APPROVAL'} or not reviewable(article):continue
        stamp=revision(article)
        if any((n.get('article_id') or n.get('entity_id'))==article['id'] and (n.get('editorial') or n.get('details') or {}).get('revision')==stamp for n in actions):continue
        emit(scope,'ARTICLE_READY','article-ready:'+article['id']+':'+stamp,'Artículo listo: '+article.get('title_es',article['id']),
            article.get('summary_es',''),'/?zar_workspace=sites&edit_article='+article['id']+'#reposnewsEditor',article['id'],'ARTICLE',
            details={'revision':stamp})


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
    worker=instagram_local_queue.status();editorial_data=rn.read()
    if editorial_data.get('owner')==scope:reconcile_ready(scope,editorial_data)
    if editorial_data.get('owner')==scope:
        from .reposnews_ambiguity import grouped
        grouped(scope,editorial_data)
    if editorial_data.get('owner')==scope:
        if worker.get('session')=='EXPIRED':emit(scope,'WORKER_SESSION_EXPIRED','worker-session-expired','Instagram requiere iniciar sesión','Abre el perfil exclusivo del worker y renueva la sesión local.','/?zar_workspace=sites#reposnewsEditor',entity_type='WORKER')
        elif worker.get('state')=='OFFLINE':emit(scope,'WORKER_OFFLINE','worker-offline','Worker de Reels desconectado','Los trabajos permanecen en cola hasta que el PC y el worker estén disponibles.','/?zar_workspace=sites#reposnewsEditor',entity_type='WORKER')
    with holdings.transaction(scope):
        data=holdings.read(scope);rows=identity_center.ensure(data)['human_actions']
        reconcile_actions(rows,editorial_data if editorial_data.get('owner')==scope else {},data.get('account_connections',{}))
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
            if row.get('type')=='ARTICLE_UPDATE_READY' and editorial_data.get('owner')==scope:
                revision=next((r for r in editorial_data.get('article_revisions',[]) if r['article_revision_id']==row.get('entity_id')),None)
                if revision and revision['state']!='ARTICLE_UPDATE_DRAFT':row['status']='DONE'
            item=dict(row,completed=row.get('status') in {'DONE','COMPLETED','PUBLISHED','CANCELLED','IGNORED'})
            if editorial and editorial_data.get('owner')==scope:
                inbox=next((r for r in editorial_data.get('instagram_inbox',[]) if r['id']==row.get('inbox_item_id')),None)
                if inbox:
                    item['processing']=bool(inbox.get('reprocess_round') and inbox.get('status') in {'WAITING_LOCAL_WORKER','OPENING_INSTAGRAM','FETCHING_VIDEO','VIDEO_DOWNLOADED','TRANSCRIBING','ANALYZING','FETCHING_MEDIA','BROWSING','IDENTIFYING','RESEARCHING','DRAFTING_ES','DRAFTING_EN','ASSETS','SEO','RECEIVED'})
                    if editorial.get('status') in {'NEEDS_DISAMBIGUATION','FAILED_RETRYABLE','FAILED_PERMANENT'} and inbox.get('status') in {'READY_PRIVATE','NO_CHANGE','ARTICLE_UPDATE_DRAFT','PUBLISHED','DISCARDED','CANCELLED'}:
                        row['status']='DONE';item.update(status='DONE',completed=True)
            if editorial.get('article_id') and editorial_data.get('owner')==scope:
                article=next((a for a in editorial_data.get('articles',[]) if a['id']==editorial['article_id']),None)
                if article:item['article']=article_card(scope,article)
            if row.get('type')=='ARTICLE_UPDATE_READY' and editorial_data.get('owner')==scope:
                from .reposnews_revisions import token
                revision=next((r for r in editorial_data.get('article_revisions',[]) if r['article_revision_id']==row.get('entity_id')),None)
                if revision and revision['state']=='ARTICLE_UPDATE_DRAFT':item['approval_request']=token(scope,revision)
            article_id=editorial.get('article_id') or (row.get('entity_id') if row.get('type')=='ARTICLE_READY' else None)
            article=next((a for a in editorial_data.get('articles',[]) if a['id']==article_id),None) if editorial_data.get('owner')==scope else None
            if article:
                item['article']=article_card(scope,article)
                stamp=(editorial or row.get('details') or {}).get('revision')
                if article.get('published') or article.get('state') in {'CANCELLED','MODIFYING','DRAFT'} or stamp and stamp!=item['article']['revision']:
                    row.update(status='DONE',outcome='PUBLISHED' if article.get('published') else article.get('state'));item.update(status='DONE',completed=True,outcome=row.get('outcome'))
            if row.get('type')=='ARTICLE_UPDATE_READY' and editorial_data.get('owner')==scope:
                proposal=next((r for r in editorial_data.get('article_revisions',[]) if r['article_revision_id']==row.get('entity_id')),None)
                if proposal:
                    item.update(article=article_card(scope,proposal['draft']),changes={key:[x['field'] for x in fields if x.get('field')] for key,fields in proposal.get('diff',{}).items() if key in {'ADDED','UPDATED','REMOVED'}},outcome=proposal['state'])
                    item['article'].pop('approval_request',None)
            item['category']=category(item)
            item['requires_action']=bool(not item['completed'] and not item.get('processing') and (item.get('status') in {'ACTION_REQUIRED','AWAITING_APPROVAL','NEEDS_DISAMBIGUATION','FAILED_RETRYABLE','FAILED_PERMANENT','HUMAN_ACTION_REQUIRED'} or item.get('type') in {'ARTICLE_READY','ARTICLE_UPDATE_READY','ARTICLE_COVER_FAILED'}))
            item['repos_filter']='PUBLICADAS' if item.get('outcome') in {'PUBLISHED','APPLIED'} else 'CANCELADAS' if item.get('outcome') in {'CANCELLED','IGNORED'} else 'ERRORES' if re.search('FAILED|ERROR',item.get('type','')+' '+item.get('status','')) else 'ACTUALIZACIONES' if item.get('type')=='ARTICLE_UPDATE_READY' else 'PARA PUBLICAR' if item.get('type')=='ARTICLE_READY' and not item['completed'] and item.get('article',{}).get('approval_request') else 'NECESITAN REVISIÓN'
            for key in ('message','reason','title','details','editorial'):
                if key in item:item[key]=clean(item[key],-3 if key=='details' and item.get('type')=='ARTICLE_IDENTIFICATION_REQUIRED' else 0)
            result.append(item)
        holdings.write(scope,data)
    result.sort(key=lambda x:x.get('created_at',''),reverse=True)
    from .reposnews_history import summary
    counts={key:sum(not x.get('dismissed_at') and (key=='TODAS' or key=='NO LEÍDAS' and not x.get('read_at') or key=='REQUIEREN ACCIÓN' and x.get('requires_action') or x.get('category')==key) for x in result) for key in ('TODAS','NO LEÍDAS','REQUIEREN ACCIÓN','REPOSNEWS','SOCIAL','CUENTAS','SISTEMA')}
    return {'counts':counts,'items':result,'unread':sum(not x.get('read_at') and not x.get('dismissed_at') for x in result),'worker':worker,'historical':summary(editorial_data) if editorial_data.get('owner')==scope else {}}


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
