"""Persistent draft modifications and private Reel assets."""
import base64
import hashlib
from pathlib import Path
import re
from flask import request, abort, send_file, jsonify, session
import secrets
from . import holdings, reposnews as rn


def keep_frames(item_id,parts,permalink,duration=0,frame_timestamps=None):
    if not re.fullmatch(r'[a-f0-9]{24}',item_id):return []
    folder=rn._path().parent/'private-assets'/item_id
    rows=[]
    for part in parts:
        media=part.get('inlineData') or {}
        if media.get('mimeType')!='image/jpeg' or len(rows)>=12:continue
        content=base64.b64decode(media['data'])
        if len(content)>1500000:continue
        asset=hashlib.sha256(content).hexdigest()[:24]+'.jpg'
        folder.mkdir(parents=True,exist_ok=True);(folder/asset).write_bytes(content)
        from .reposnews_assets import provenance
        rows.append({'kind':'REEL_FRAME','asset':asset,'url':'/reposnews-preview/assets/'+item_id+'/'+asset,
            'source':permalink,'permission':'REVIEW_REQUIRED','created_at':holdings._now(),
            **provenance('REEL_FRAME',permalink,frame_timestamp=frame_timestamps[len(rows)] if frame_timestamps and len(rows)<len(frame_timestamps) else round((len(rows)+.5)*duration/8,2) if duration and frame_timestamps is None else None)})
    return rows


def modify_request(scope,payload):
    from .reposnews_automation import revoke
    text=str(payload.get('instruction') or '').strip()
    if not 3<=len(text)<=3000:raise ValueError('Indica el cambio que quieres aplicar al borrador.')
    with holdings.transaction('reposnews-editorial'):
        rn.state(scope);data=rn.read();article=next((a for a in data.get('articles',[]) if a['id']==payload.get('id')),None)
        if not article or article.get('published') or article.get('state')=='CANCELLED':raise ValueError('PRIVATE_DRAFT_REQUIRED')
        row=next((r for r in data.get('instagram_inbox',[]) if r.get('article_id')==article['id']),None)
        if not row or not row.get('research_package'):raise ValueError('OFFICIAL_RESEARCH_REQUIRED')
        revoke(article);article.update(state='MODIFYING',status='MODIFYING')
        article['history']=(article.get('history',[])+[{'at':holdings._now(),'fields':['modification_request'],'reason':'Cambio solicitado por el titular: '+text}])[-60:]
        cover=payload.get('cover_asset')
        if cover:
            asset=next((a for a in article.get('assets',[]) if a.get('asset')==cover),None)
            if not asset:raise ValueError('Elige un asset del borrador.')
            row['requested_cover']=dict(asset,permission='USER_APPROVED')
        image=str(payload.get('image_url') or '').strip()
        if image:
            from .browser_network import public_url
            public_url(image)
            row['requested_image']={'url':image,'source':image,'permission':'USER_PROVIDED'}
        row.update(status='RECEIVED',processing_state='MODIFYING',modification_request=text,upgrade_article_id=article['id'],
            retry_after=0,attempt_limit=row.get('attempts',0)+8)
        if re.search(r'(?:otra|nueva|regenera|cambia).{0,40}portada|(?:new|regenerate|replace).{0,40}cover',text,re.I):
            row['replace_cover']=holdings._now()
        row['research_package']['current_draft']={k:article.get(k) for k in ('title_es','title_en','summary_es','summary_en','body_es','body_en')}
        rn.write(data)
    from .reposnews_inbox import start_worker
    start_worker()
    return rn.state(scope)


def register(app,scope_fn):
    @app.post('/api/reposnews/editorial/<action>')
    def reposnews_editorial_action(action):
        if session.get('zar_auth') is not True:return jsonify(ok=False,error='AUTHENTICATED_USER_DECISION_REQUIRED'),401
        csrf=session.get('business_csrf')
        if not csrf or not secrets.compare_digest(csrf,request.headers.get('X-ZAR-Business-CSRF','')):return jsonify(ok=False,error='CSRF_REQUIRED'),403
        if action not in {'decision','publish','modify'}:abort(404)
        try:
            result=rn.operate(scope_fn(),{'decision':'editorial_decision','publish':'publish','modify':'modify_request'}[action],request.get_json(silent=True) or {})
            return jsonify(ok=True,result=result)
        except (ValueError,KeyError,TypeError) as exc:return jsonify(ok=False,error=str(exc)),400

    @app.get('/reposnews-preview/assets/<item_id>/<asset>')
    def reposnews_private_asset(item_id,asset):
        try:rn.state(scope_fn())
        except ValueError:abort(403)
        if not re.fullmatch(r'[a-f0-9]{24}',item_id) or not re.fullmatch(r'[a-f0-9]{24}\.jpg',asset):abort(404)
        path=rn._path().parent/'private-assets'/item_id/asset
        if not path.is_file():abort(404)
        return send_file(path,mimetype='image/jpeg',max_age=0)
