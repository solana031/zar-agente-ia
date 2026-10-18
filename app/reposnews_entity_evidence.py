"""Corroborating entity hints from the existing editorial store, never research facts."""
import re
from urllib.parse import urlsplit

GENERIC={'ai','api','mcp','agent','agents','tool','tools','video','python','github','opensource'}

def normalized(value):return re.sub(r'[^a-z0-9]','',str(value).casefold())

def names(article):
    repo=str(article.get('repo') or '')
    values=[repo.rsplit('/',1)[-1],article.get('name','')]+list(article.get('aliases') or [])
    return {str(v).strip() for v in values if len(normalized(v))>=3 and normalized(v) not in GENERIC}

def urls(value):
    if isinstance(value,dict):
        return set().union(*(urls(v) for v in value.values())) if value else set()
    if isinstance(value,list):
        return set().union(*(urls(v) for v in value)) if value else set()
    if not isinstance(value,str):return set()
    result=set()
    for url in re.findall(r'https://[^\s<>"\x27\\]+',value):
        try:
            p=urlsplit(url.rstrip('.,);]'));host=(p.hostname or '').removeprefix('www.').lower()
            if p.username or p.password or not host or host in {'instagram.com','facebook.com','youtube.com','tiktok.com'} or host.endswith(('.fbcdn.net','.cdninstagram.com')):continue
            result.add(host+p.path.rstrip('/').lower())
        except ValueError:pass
    return result

def creator(row):
    meta=(row.get('public_metadata') or {}).get('metadata') or {}
    value=row.get('creator') or meta.get('author') or (row.get('discovery_metadata') or {}).get('creator')
    return str(value).casefold().strip() if isinstance(value,str) else ''

def hints(data,row,evidence):
    """A creator alone cannot identify a tool. Shared frames need corroboration."""
    text=str(evidence.get('text') or '')
    primary={normalized(n) for n in evidence.get('project_names',[]) if isinstance(n,str) and normalized(n) not in GENERIC}
    current_urls=urls([text,evidence.get('outbound_links',[]),evidence.get('github_urls',[])])
    assets={a.get('asset') for a in row.get('visual_assets',[]) if a.get('asset')}
    pooled=[];current_creator=creator(row) or str((evidence.get('metadata') or {}).get('author') or '').casefold().strip()
    for other in data.get('instagram_inbox',[])[-200:]:
        if other.get('id')==row.get('id'):continue
        shared=assets & {a.get('asset') for a in other.get('visual_assets',[]) if a.get('asset')}
        if shared and current_creator and current_creator==creator(other):
            pooled.append({'item_id':other['id'],'analysis':other.get('analysis',{}),'repo':other.get('repo'),'resolution':other.get('entity_resolution',{})})
    pooled_urls=urls(pooled)
    matches=[]
    for article in data.get('articles',[]):
        from .instagram_local_queue import same_reel
        same_source=any(same_reel(row.get('source_url'),source) for source in article.get('source_reels',[])+[article.get('discovery_source')] if source)
        aliases=names(article)
        mentioned=[name for name in aliases if primary=={normalized(name)} or re.search(r'(?:logo|project|proyecto|tool|herramienta)\s*[:=]?\s*'+re.escape(name)+r'(?!\w)',text,re.I)]
        official=urls([article.get('repository_url',''),article.get('website',''),article.get('official_docs','')])
        shared_urls=official & current_urls
        pooled_match=bool(official & pooled_urls)
        if not mentioned and not shared_urls and not pooled_match and not same_source:continue
        matches.append({'article_id':article['id'],'repo':article.get('repo'),'repository_url':article.get('repository_url'),'website':article.get('website'),
            'official_docs':article.get('official_docs'),'aliases':sorted(aliases),'evidence':['EXACT_REEL_PROVENANCE'] if same_source else ['URL'] if shared_urls else ['NAME_OR_LOGO_TEXT'] if mentioned else ['CREATOR_AND_IDENTICAL_FRAME'],
            'corroborating_reels':[p['item_id'] for p in pooled] if pooled_match else []})
    return {'status':'UNIQUE_HINT' if len(matches)==1 else 'AMBIGUOUS_HINTS' if matches else 'NO_MATCH','candidates':matches[:12],'verified_facts':False}
