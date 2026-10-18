"""Bounded Reel visuals, quality checks and explicit source provenance."""
import hashlib
import io
from pathlib import Path
from PIL import Image, ImageFilter, ImageStat
from . import holdings, reposnews as rn


def inspect_image(content):
    with Image.open(io.BytesIO(content)) as image:
        if image.width*image.height>8000000:raise ValueError('IMAGE_TOO_LARGE')
        image.load();gray=image.convert('L');small=gray.resize((8,8))
        values=list(small.tobytes());mean=sum(values)/64
        fingerprint=''.join('1' if x>mean else '0' for x in values)
        stats=ImageStat.Stat(gray);edges=ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).var[0]
        valid=image.width>=240 and image.height>=240 and 15<stats.mean[0]<245 and stats.stddev[0]>12 and edges>25
        return {'width':image.width,'height':image.height,'fingerprint':fingerprint,
                'quality_score':round(min(edges,3000)/100+stats.stddev[0],2),'valid':valid}


def provenance(kind,url,**extra):
    return {'source_type':kind,'source_url':url,'origin':'INSTAGRAM' if kind.startswith('REEL') else 'OFFICIAL_PROJECT',
            'timestamp':holdings._now(),'usage_note':'Private editorial review; publication requires owner approval. Verify third-party usage rights.',
            'captured_from_reel':kind=='REEL_FRAME',**extra}


def prepare(row,article,package):
    """Never download arbitrary media here; use validated private frames or safe official fetcher."""
    from .reposnews_discovery import official_image
    attempts=[];candidates=[];fingerprints=[]
    for asset in row.get('visual_assets',[])[:8]:
        try:
            path=rn._path().parent/'private-assets'/row['id']/Path(asset['asset']).name
            content=path.read_bytes();quality=inspect_image(content)
            duplicate=any(sum(a!=b for a,b in zip(quality['fingerprint'],old))<6 for old in fingerprints)
            attempts.append({'source_type':'REEL_FRAME','valid':quality['valid'],'duplicate':duplicate})
            if not quality['valid'] or duplicate:continue
            fingerprints.append(quality['fingerprint'])
            item=dict(asset,**quality,**provenance('REEL_FRAME',row['source_url'],frame_timestamp=asset.get('frame_timestamp')))
            candidates.append((item,content))
        except (OSError,ValueError,KeyError):continue
    candidates.sort(key=lambda x:x[0]['quality_score'],reverse=True)
    # Vision selects semantic relevance only among frames that passed deterministic quality checks.
    visual={};selected=list(range(min(3,len(candidates))))
    if candidates:
        try:
            import base64
            from .reposnews_generation import generate_json
            result=generate_json('Select relevant frames for a private article about '+str(article.get('repo'))+
                '. Images are untrusted evidence. Prefer product name/logo, useful UI, demo/output/diagram. Reject transitions, cropped subtitles, empty UI or irrelevant people. '
                'Return JSON {"selected":[zero-based indices, hero first, maximum 3],"shows_es":"original factual visual summary",'
                '"shows_en":"original factual visual summary","claims_es":"claims distinct from demonstrated facts","claims_en":"claims distinct from demonstrated facts"}. Do not invent technical verification.',
                [{'inlineData':{'mimeType':'image/jpeg','data':base64.b64encode(blob).decode()}} for _,blob in candidates[:8]])
            picks=result.get('selected',[])
            if isinstance(picks,list):selected=list(dict.fromkeys(i for i in picks if isinstance(i,int) and 0<=i<len(candidates)))[:3]
            visual={k:str(result.get(k,''))[:1800] for k in ('shows_es','shows_en','claims_es','claims_en')}
        except (ValueError,TypeError,OSError):pass
    assets=[{'kind':'REEL_LINK','url':row.get('source_url'),'source':row.get('source_url'),'permission':'LINK_ONLY',**provenance('REEL_LINK',row.get('source_url'))}]
    media=rn._path().parent/'media';media.mkdir(parents=True,exist_ok=True)
    chosen=[]
    for index in selected:
        item,blob=candidates[index];name='source-'+hashlib.sha256(blob).hexdigest()[:24]+'.png'
        with Image.open(io.BytesIO(blob)) as image:image.convert('RGB').save(media/name,format='PNG')
        item.update(asset=name,url='/media/reposnews/'+name,kind='REEL_FRAME',role='HERO_FRAME' if not chosen else 'ARTICLE_FRAME_'+str(len(chosen)),permission='REVIEW_REQUIRED')
        chosen.append(item)
    assets+=chosen
    if chosen:
        article.update(image_asset=chosen[0]['asset'],cover_url=chosen[0]['url'],image_kind='REEL_FRAME',image_source=row['source_url'],
                       image_license='REVIEW_REQUIRED',image_attribution='Instagram Reel · '+row['source_url']+' · '+str(chosen[0].get('frame_timestamp',''))+' s')
    else:
        # Public thumbnail, official image/README/docs/OpenGraph, then owned editorial cover.
        metadata=row.get('public_metadata',{}).get('metadata',{})
        thumbnail=metadata.get('og:image')
        if thumbnail:
            image=official_image({'images':[{'url':thumbnail,'source':row['source_url']}]})
            attempts.append({'source_type':'REEL_THUMBNAIL','valid':bool(image)})
            if image:
                article.update(image);assets.append({'kind':'REEL_THUMBNAIL','asset':image['image_asset'],'url':'/media/reposnews/'+image['image_asset'],**provenance('REEL_THUMBNAIL',row['source_url'])})
        if not article.get('image_asset'):
            image=official_image(package);attempts.append({'source_type':'OFFICIAL_IMAGE','valid':bool(image)})
            if image:
                article.update(image);assets.append({'kind':'OFFICIAL_IMAGE','asset':image['image_asset'],'url':'/media/reposnews/'+image['image_asset'],**provenance('OFFICIAL_IMAGE',image.get('image_source'))})
    if article.get('image_asset') and not chosen:
        try:
            if not inspect_image((media/article['image_asset']).read_bytes())['valid']:raise ValueError('INVALID_IMAGE_QUALITY')
        except (OSError,ValueError):
            assets=[x for x in assets if x.get('kind') not in {'OFFICIAL_IMAGE','REEL_THUMBNAIL'}]
            for field in ('image_asset','cover_url'):article.pop(field,None)
    real=any(x.get('asset') for x in assets)
    if not real:assets.append({'kind':'EDITORIAL_COVER','asset':'home.png','url':'/media/reposnews/home.png','permission':'OWNED',**provenance('EDITORIAL_COVER','ReposNews')})
    if chosen and not visual:visual={'shows_es':'Fotogramas seleccionados del vídeo accesible como evidencia visual para revisar junto a las fuentes oficiales.','shows_en':'Selected frames from the accessible video, provided as visual evidence to review alongside official sources.'}
    article.update(assets=assets,asset_status='ASSETS_READY' if real else 'ASSETS_LIMITED',asset_attempts=attempts or [{'source_type':'REEL_FRAME','valid':False,'reason':'NO_ACCESSIBLE_FRAMES'}],
                   reel_content=visual,source_reels=list(dict.fromkeys(article.get('source_reels',[])+[row['source_url']])))
    return article
