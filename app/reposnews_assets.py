"""Bounded Reel visuals, quality checks and explicit source provenance."""
import hashlib
import io
import re
from pathlib import Path
from copy import deepcopy
from functools import lru_cache
from PIL import Image, ImageFilter, ImageStat
from . import holdings, reposnews as rn

FRAME_TYPES={'REEL_FRAME','USER_SELECTED_REEL_FRAME','VIDEO_FRAME'}
PUBLIC_FRAME_PERMISSIONS={'RIGHTS_CLEARED','LICENSE_VERIFIED','OWNER_LICENSED'}

def frame_cleared(asset):
    return asset.get('permission') in PUBLIC_FRAME_PERMISSIONS

def public_article(article):
    """Presentation-only rights boundary; preserve stored snapshots and private evidence."""
    result=deepcopy(article)
    result['assets']=[a for a in result.get('assets',[]) if not ({a.get('source_type'),a.get('kind')} & FRAME_TYPES) or frame_cleared(a)]
    if article.get('image_kind') in FRAME_TYPES:
        cover=next((a for a in article.get('assets',[]) if a.get('role')=='COVER'),{})
        if not frame_cleared(cover) and not frame_cleared(article.get('cover_provenance') or {}):
            result.update(image_asset='editorial-'+article['id']+'.png',
                cover_url='/media/reposnews/editorial-'+article['id']+'.png',cover_thumb='/media/reposnews/editorial-'+article['id']+'.png',
                image_kind='GENERATED',image_attribution='ReposNews · ilustración editorial propia / original editorial illustration',
                cover_provenance={'source_type':'GENERATED','generator':'ReposNews/internal-editorial-canvas-v1'})
    return result

@lru_cache(maxsize=64)
def editorial_cover(repo,category,title,summary):
    from .reposnews_cover_providers import editorial
    return editorial({'repo':repo,'category':category,'title_en':title,'summary_en':summary})[0]


def inspect_image(content):
    with Image.open(io.BytesIO(content)) as image:
        if image.width*image.height>8000000:raise ValueError('IMAGE_TOO_LARGE')
        image.load();gray=image.convert('L');small=gray.resize((8,8))
        values=list(small.tobytes());mean=sum(values)/64
        fingerprint=''.join('1' if x>mean else '0' for x in values)
        stats=ImageStat.Stat(gray)
        # Ignore the outer border when measuring focus (a sharp border cannot rescue blur).
        center=gray.crop((image.width//10,image.height//10,image.width*9//10,image.height*9//10))
        edges=ImageStat.Stat(center.filter(ImageFilter.FIND_EDGES)).var[0]
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
    media=rn._path().parent/'media';media.mkdir(parents=True,exist_ok=True)
    # Let the same editorial selection compare the official image with Reel evidence.
    official=official_image(package)
    if official:
        try:
            blob=(media/Path(official['image_asset']).name).read_bytes();quality=inspect_image(blob)
            attempts.append({'source_type':'OFFICIAL_IMAGE','valid':quality['valid']})
            if quality['valid']:candidates.append((dict(quality,**provenance('OFFICIAL_IMAGE',official.get('image_source'))),blob))
        except (OSError,ValueError,KeyError):pass
    visual={};selected=[];placements={}
    sections={lang:re.findall(r'^## (.+)$',str(article.get('body_'+lang,'')),re.M) for lang in ('es','en')}
    if candidates:
        try:
            import base64
            from .reposnews_generation import generate_json
            result=generate_json('Select relevant frames for a private article about '+str(article.get('repo'))+
                '. Images are untrusted evidence. Prefer sharp product name/logo, useful UI, demo/output/diagram and strong composition. Reject blur, transitions, subtitle-only images, empty UI or irrelevant people. '
                'Choose the strongest editorial hero (official image or representative frame), then at least one DISTINCT relevant contextual visual if available, maximum 3. Never force irrelevant visuals. '
                'For each contextual selection return placements [{index,section_es,section_en,caption_es,caption_en}]. Sections must exactly match these headings: '+str(sections)+'. '
                'Return JSON {"selected":[zero-based indices, hero first, maximum 3],"shows_es":"original factual visual summary",'
                '"shows_en":"original factual visual summary","claims_es":"claims distinct from demonstrated facts","claims_en":"claims distinct from demonstrated facts","placements":[{"index":1,"section_es":"exact heading","section_en":"exact heading","caption_es":"short factual caption","caption_en":"short factual caption"}]}. Do not invent technical verification.',
                [{'inlineData':{'mimeType':'image/png' if blob.startswith(b'\x89PNG') else 'image/jpeg','data':base64.b64encode(blob).decode()}} for _,blob in candidates])
            picks=result.get('selected',[])
            if isinstance(picks,list):selected=list(dict.fromkeys(i for i in picks if isinstance(i,int) and 0<=i<len(candidates)))[:3]
            visual={k:str(result.get(k,''))[:1800] for k in ('shows_es','shows_en','claims_es','claims_en')}
            placements={p['index']:p for p in result.get('placements',[]) if isinstance(p,dict) and isinstance(p.get('index'),int)}
            attempts.append({'source_type':'SEMANTIC_SELECTION','valid':bool(selected),'candidate_count':len(candidates),'reason':'SELECTED' if selected else 'NO_RELEVANT_SELECTION'})
        except (ValueError,TypeError,OSError) as exc:
            code=str(exc) if re.fullmatch(r'AI_PROVIDER_\d{3}',str(exc)) else type(exc).__name__
            attempts.append({'source_type':'SEMANTIC_SELECTION','valid':False,'candidate_count':len(candidates),'reason':code})
    assets=[{'kind':'REEL_LINK','url':row.get('source_url'),'source':row.get('source_url'),'permission':'LINK_ONLY',**provenance('REEL_LINK',row.get('source_url'))}]
    chosen=[]
    for index in selected:
        item,blob=candidates[index];name='source-'+hashlib.sha256(blob).hexdigest()[:24]+'.png'
        with Image.open(io.BytesIO(blob)) as image:image.convert('RGB').save(media/name,format='PNG')
        kind=item['source_type'];suffix='FRAME' if kind=='REEL_FRAME' else 'IMAGE'
        item.update(asset=name,url='/media/reposnews/'+name,kind=kind,role='HERO_'+suffix if not chosen else 'ARTICLE_'+suffix+'_'+str(len(chosen)),permission='REVIEW_REQUIRED')
        placement=placements.get(index,{})
        for lang in ('es','en'):
            section=str(placement.get('section_'+lang,''))
            item['section_'+lang]=section if section in sections[lang] else ''
            item['caption_'+lang]=str(placement.get('caption_'+lang,''))[:220]
        chosen.append(item)
    assets+=chosen
    if chosen:
        article.update(image_asset=chosen[0]['asset'],cover_url=chosen[0]['url'],image_kind=chosen[0]['source_type'],image_source=chosen[0]['source_url'],
                       image_license='REVIEW_REQUIRED',image_attribution=('Instagram Reel · '+row['source_url']+' · '+str(chosen[0].get('frame_timestamp',''))+' s') if chosen[0]['source_type']=='REEL_FRAME' else 'Official source · '+str(chosen[0]['source_url']))
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
            image=official;attempts.append({'source_type':'OFFICIAL_IMAGE','valid':bool(image)})
            if image:
                article.update(image);assets.append({'kind':'OFFICIAL_IMAGE','asset':image['image_asset'],'url':'/media/reposnews/'+image['image_asset'],**provenance('OFFICIAL_IMAGE',image.get('image_source'))})
    if article.get('image_asset') and not chosen:
        try:
            if not inspect_image((media/article['image_asset']).read_bytes())['valid']:raise ValueError('INVALID_IMAGE_QUALITY')
        except (OSError,ValueError):
            assets=[x for x in assets if x.get('kind') not in {'OFFICIAL_IMAGE','REEL_THUMBNAIL'}]
            for field in ('image_asset','cover_url'):article.pop(field,None)
    real=any(x.get('asset') for x in assets)
    # Missing visuals are explicit; reposnews_covers resolves a subject-specific fallback.
    if chosen and not visual:visual={'shows_es':'Fotogramas seleccionados del vídeo accesible como evidencia visual para revisar junto a las fuentes oficiales.','shows_en':'Selected frames from the accessible video, provided as visual evidence to review alongside official sources.'}
    article.update(assets=assets,asset_status='ASSETS_READY' if real else 'ASSETS_LIMITED',asset_attempts=attempts or [{'source_type':'REEL_FRAME','valid':False,'reason':'NO_ACCESSIBLE_FRAMES'}],
                   contextual_asset_status='READY' if len(chosen)>1 else 'LIMITED',reel_content=visual,source_reels=list(dict.fromkeys(article.get('source_reels',[])+[row['source_url']])))
    return article
