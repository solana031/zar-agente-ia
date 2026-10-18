"""Editorial decisions and notifications. Worker results never grant publication."""
import hashlib
import json
import secrets
from flask import has_request_context, session
from itsdangerous import URLSafeTimedSerializer, BadSignature
from . import holdings, reposnews as rn, identity_center, oauth_vault

READY = 'READY_PRIVATE'
CONTENT_FIELDS = ('title_es','title_en','summary_es','summary_en','body_es','body_en','sources','seo','image_asset','assets','cover_url','source_reels','reel_content','asset_status')


def revision(article):
    return hashlib.sha256(json.dumps({k:article.get(k) for k in CONTENT_FIELDS},sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def signer():
    root=rn._path().parent
    oauth_vault.cipher(root)
    return URLSafeTimedSerializer((root/'oauth_vault.key').read_bytes(),salt='reposnews-user-publication-v1')


def request_token(scope,article):
    return signer().dumps({'owner':scope,'article':article['id'],'revision':revision(article)})


def complete(article):
    return (article.get('review_kind')!='DETERMINISTIC_LIMITED_SOURCE_NOTE'
        and all(isinstance(article.get(k),str) and article[k].strip() for k in CONTENT_FIELDS[:6])
        and all(len(article['body_'+lang].split())>=250 for lang in ('es','en'))
        and len(article.get('sources') or [])>=2)


def gate(article,scope):
    approval=article.get('approval') or {}
    if (article.get('approval_status')!='APPROVED_BY_USER' or approval.get('owner')!=scope
            or approval.get('revision')!=revision(article) or not approval.get('at')):
        raise ValueError('EXPLICIT_USER_APPROVAL_REQUIRED')
    if article.get('state')=='CANCELLED':raise ValueError('ARTICLE_CANCELLED')


def revoke(article):
    article.update(approval_status='PENDING',approval={})


def decorate(scope,data):
    # Tokens authorize a specific authenticated UI decision, not worker preparation.
    for article in data.get('articles',[]):
        if not article.get('published') and article.get('state') in {'READY',READY,'AWAITING_APPROVAL'}:
            article['approval_request']=request_token(scope,article)
    return data


def notify(item_id,kind='READY_PRIVATE'):
    with holdings.transaction('reposnews-editorial'):
        data=rn.read();row=next((r for r in data.get('instagram_inbox',[]) if r['id']==item_id),None)
        if not row or not data.get('owner'):return
        article=next((a for a in data.get('articles',[]) if a['id']==row.get('article_id')),None)
        if kind==READY and (not article or not complete(article)):return
        if kind!=READY:article=None
        scope=data['owner'];key='article:'+article['id'] if article else 'reel:'+item_id
        name=article.get('title_es') if article else 'Proyecto sin identificar'
        notification={'key':key,'kind':kind,'inbox_item_id':item_id,'article_id':article['id'] if article else None,
            'project':article.get('repo') if article else None,'title':'Artículo listo: '+name if article else 'No he podido identificar con seguridad el proyecto del Reel.',
            'message':'He analizado el Reel y preparado el artículo completo ES/EN. ¿Quieres publicarlo, modificarlo o cancelarlo?' if article else 'Indica solo el nombre de la herramienta o proyecto. No hace falta reenviar el Reel.',
            'reel':row.get('source_url'),'image':'/media/reposnews/'+(article.get('image_asset') or 'home.png') if article else None,
            'preview_es':'/reposnews-preview/es/'+article['id'] if article else None,'preview_en':'/reposnews-preview/en/'+article['id'] if article else None,
            'sources':article.get('sources',[]) if article else [],'seo':article.get('seo',{}) if article else {},
            'status':'AWAITING_APPROVAL' if article else 'NEEDS_DISAMBIGUATION','created_at':holdings._now()}
        if kind=='FAILED_RETRYABLE':notification.update(title='No se ha podido completar el artículo del Reel',message='El proveedor no ha permitido terminar un artículo completo. ZAR conserva el Reel, el análisis y el trabajo; no se ha publicado nada.',status='FAILED_RETRYABLE')
        if article:notification['revision']=revision(article)
        if article:
            for note in data.get('editorial_notifications',[]):
                if note.get('inbox_item_id')==item_id and note.get('kind')!=READY:note['status']='DONE'
        old=next((n for n in data.setdefault('editorial_notifications',[]) if n['key']==key and n.get('status') not in {'CANCELLED','PUBLISHED'}),None)
        if old and old.get('revision')==notification.get('revision') and old.get('kind')==kind:return
        if old:old.update(notification)
        else:data['editorial_notifications'].append(notification)
        if article:row.update(status=READY,processing_state=READY,approval_status='PENDING')
        rn.write(data)
    with holdings.transaction(scope):
        state=holdings.read(scope);center=identity_center.ensure(state)
        if article:
            for previous in center['human_actions']:
                if previous.get('service')=='REPOSNEWS' and previous.get('inbox_item_id')==item_id and previous.get('action')!='ARTICLE_READY':previous['status']='DONE'
        action=identity_center.queue(center,'REPOSNEWS','ARTICLE_READY' if article else 'IDENTIFY_REEL',notification['message'],
            '/?zar_workspace=sites#reposnewsEditor',[],plan_id=key)
        action.update(title=notification['title'],editorial=notification,article_id=notification['article_id'],inbox_item_id=item_id,
            status=notification['status'],account='Pablo')
        holdings.write(scope,state)


def close_notification(scope,article_id,status):
    with holdings.transaction(scope):
        state=holdings.read(scope)
        for action in identity_center.ensure(state)['human_actions']:
            if action.get('service')=='REPOSNEWS' and action.get('article_id')==article_id:
                action.update(status='DONE',outcome=status,completed_at=holdings._now())
        holdings.write(scope,state)


def publish_article(data,article,scope):
    gate(article,scope)
    if holdings.read(scope).get('global_stop'):raise ValueError('STOP GLOBAL activo.')
    if rn.legal_status(data)['status']!='LEGAL_READY':raise ValueError('Revisión legal pendiente.')
    if article.get('state') not in {'READY',READY,'AWAITING_APPROVAL'} or not complete(article):raise ValueError('COMPLETE_BILINGUAL_DRAFT_REQUIRED')
    from . import jev_decision
    proposal=jev_decision.proposal(scope,{'source_agent':'ReposNewsPublicationAction','task':'Publicación aprobada por el titular','action':'publish article','resources':[rn.ORIGIN],'expected_cost':0,'risk':.3,'urgency':.5})
    if proposal['decision']=='REJECT':raise ValueError('JEV rechazó publicación.')
    article.update(state='PUBLISHING',status='PUBLISHING')
    article['history']=(article.get('history',[])+[{'at':holdings._now(),'fields':['state'],'reason':'PUBLISHING · APPROVED_BY_USER · '+revision(article)}])[-60:]
    article.update(published=True,published_at=holdings._now(),state='PUBLISHED',status='PUBLISHED')
    article['published_snapshot']={k:v for k,v in article.items() if k not in {'published_snapshot','history','approval_request'}}
    if article.get('image_asset'):article['published_snapshot']['cover_url']='/media/reposnews/'+article['image_asset']
    for row in data.get('instagram_inbox',[]):
        if row.get('article_id')==article['id']:row.update(status='PUBLISHED',processing_state='PUBLISHED')
    for note in data.get('editorial_notifications',[]):
        if note.get('article_id')==article['id']:note['status']='PUBLISHED'
    jev_decision.decision_state(scope,proposal['id'],'USER_CONFIRMED_EDITORIAL_CHANGE')


def decide(scope,payload):
    if not has_request_context() or session.get('zar_auth') is not True:raise ValueError('AUTHENTICATED_USER_DECISION_REQUIRED')
    decision=payload.get('decision')
    if decision not in {'PUBLICAR','MODIFICAR','CANCELAR'}:raise ValueError('INVALID_EDITORIAL_DECISION')
    with holdings.transaction('reposnews-editorial'):
        rn.state(scope);data=rn.read();article=next((a for a in data.get('articles',[]) if a['id']==payload.get('id')),None)
        if not article or article.get('published'):raise ValueError('PRIVATE_DRAFT_REQUIRED')
        try:record=signer().loads(str(payload.get('approval_request') or ''),max_age=86400)
        except BadSignature:raise ValueError('CURRENT_DRAFT_DECISION_REQUIRED')
        if record!={'owner':scope,'article':article['id'],'revision':revision(article)}:raise ValueError('DRAFT_CHANGED_REVIEW_AGAIN')
        if article.get('state')=='CANCELLED':raise ValueError('ARTICLE_CANCELLED')
        if decision=='PUBLICAR':
            article.update(approval_status='APPROVED_BY_USER',approval={'owner':scope,'revision':revision(article),'at':holdings._now()})
            publish_article(data,article,scope)
        else:
            revoke(article)
            article.update(state='MODIFYING' if decision=='MODIFICAR' else 'CANCELLED',status='MODIFYING' if decision=='MODIFICAR' else 'CANCELLED')
            if decision=='CANCELAR':
                for row in data.get('instagram_inbox',[]):
                    if row.get('article_id')==article['id']:row.update(status='CANCELLED',processing_state='CANCELLED')
            for note in data.get('editorial_notifications',[]):
                if note.get('article_id')==article['id']:note['status']=article['state']
        article['history']=(article.get('history',[])+[{'at':holdings._now(),'fields':['state','approval_status'],'reason':'Decisión del titular: '+decision}])[-60:]
        rn.write(data)
    if decision!='MODIFICAR':close_notification(scope,article['id'],article['state'])
    if decision=='PUBLICAR':
        from .notification_center import emit
        emit(scope,'PUBLISH_SUCCESS','published:'+article['id']+':'+revision(article),'Artículo publicado: '+article['title_es'],
             'Publicación ES/EN aprobada por el titular.',article['seo']['es']['canonical'],article['id'],'ARTICLE',
             [{'label':'VER ES','url':article['seo']['es']['canonical']},{'label':'VER EN','url':article['seo']['en']['canonical']}],status='COMPLETED')
    return rn.state(scope)


def approve_batch(scope,payload):
    if not has_request_context() or session.get('zar_auth') is not True or payload.get('decision')!='PUBLICAR':raise ValueError('AUTHENTICATED_USER_DECISION_REQUIRED')
    ids=payload.get('ids') or []
    with holdings.transaction('reposnews-editorial'):
        rn.state(scope);data=rn.read();plan=rn.publication_plan(data,ids)
        if plan['digest']!=payload.get('approved_digest') or not plan['ready_to_publish']:raise ValueError('CURRENT_PUBLICATION_PLAN_REQUIRED')
        for article in data['articles']:
            if article['id'] not in ids:continue
            try:record=signer().loads((payload.get('approvals') or {}).get(article['id'],''),max_age=86400)
            except BadSignature:raise ValueError('CURRENT_DRAFT_DECISION_REQUIRED')
            if record!={'owner':scope,'article':article['id'],'revision':revision(article)}:raise ValueError('DRAFT_CHANGED_REVIEW_AGAIN')
            article.update(approval_status='APPROVED_BY_USER',approval={'owner':scope,'revision':revision(article),'at':holdings._now()})
            publish_article(data,article,scope)
        rn.write(data)
    for article_id in ids:close_notification(scope,article_id,'PUBLISHED')
    return rn.state(scope)


def migrate():
    """Retire untouched automatic source notes; never overwrite human manuscripts."""
    notifications=[]
    with holdings.transaction('reposnews-editorial'):
        data=rn.read()
        if not data.get('owner'):return
        for row in data.get('instagram_inbox',[]):
            article=next((a for a in data.get('articles',[]) if a['id']==row.get('article_id')),None)
            if not article or article.get('published') or row.get('editorial_automation_v1'):continue
            row['editorial_automation_v1']=True
            if article.get('review_kind')=='DETERMINISTIC_LIMITED_SOURCE_NOTE':
                human=any(h.get('reason','').startswith(('Edición','Corrección','Decisión')) for h in article.get('history',[]))
                if human:continue
                article.update(state='DRAFT',status='DRAFT',approval_status='PENDING')
                row.update(status='RECEIVED',processing_state='DRAFTING_ES',retry_after=0,attempt_limit=row.get('attempts',0)+8,upgrade_article_id=article['id'])
            elif complete(article):
                article.update(state=READY,status=READY,approval_status='PENDING');notifications.append(row['id'])
        rn.write(data)
    for item_id in notifications:notify(item_id)
