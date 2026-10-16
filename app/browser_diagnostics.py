"""Bounded network metadata only. Never request bodies, headers or URL queries."""
import hashlib
from urllib.parse import urlsplit

SAFE_SEGMENTS=set('api v1 v2 web accounts login ajax onetap two_factor_login challenge checkpoint graphql query logging_client_events logging batch_fetch_web qp consent check cookies storage auth oauth authorize redirect static media video images ajax bz bloks apps'.split())


def safe_path(url):
    parts=urlsplit(url).path.split('/')[:12]
    return '/'.join(p if not p or p in SAFE_SEGMENTS else '[redacted-'+hashlib.sha256(p.encode()).hexdigest()[:8]+']' for p in parts)[:500]


def classify(url,resource=''):
    parsed=urlsplit(url);host=parsed.hostname or '';path=parsed.path.lower()
    ig=host in ('instagram.com','www.instagram.com','i.instagram.com','b.i.instagram.com')
    if ig and any(x in path for x in ('/challenge','/checkpoint')):return 'CHALLENGE'
    if ig and any(x in path for x in ('/accounts/','/login','/auth','/bloks/')):return 'INSTAGRAM_AUTH'
    if ig and (path.startswith('/api/') or '/graphql' in path):return 'INSTAGRAM_API'
    if host.endswith('.cdninstagram.com'):return 'INSTAGRAM_MEDIA' if resource=='media' else 'INSTAGRAM_STATIC'
    if host.endswith('.fbcdn.net'):return 'META_CDN'
    if host in ('facebook.com','www.facebook.com','m.facebook.com') and any(x in path for x in ('login','oauth','dialog')):return 'META_AUTH'
    if ig and resource in ('stylesheet','script','font','image'):return 'INSTAGRAM_STATIC'
    if ig and resource=='media':return 'INSTAGRAM_MEDIA'
    return 'UNKNOWN_SAFE'


def event(url,method,resource,rule,status=None,redirect_url=''):
    return {'hostname':urlsplit(url).hostname or '', 'method':str(method)[:10],
            'resource_type':str(resource)[:30], 'path':safe_path(url), 'network_rule':rule,
            'http_status':status, 'redirect_hostname':urlsplit(redirect_url).hostname or '',
            'classification':'REDIRECT' if redirect_url else classify(url,resource)}
