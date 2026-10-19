"""Prepared publication hook; deliberately not registered/automatically activated.

The existing editorial approval gate remains authoritative. The local deploy
adapter is injected by a future approved runner, never by an HTTP request body.
"""
from datetime import datetime, timezone
from . import reposnews as rn
from .reposnews_automation import gate
from .notification_center import emit


def publish_approved(scope, article_id, *, build, deploy, verify):
    data = rn.read()
    if data.get('owner') != scope:
        raise ValueError('OWNER_REQUIRED')
    article = next((a for a in data.get('articles', []) if a.get('id') == article_id), None)
    if not article or not article.get('published'):
        raise ValueError('PUBLISHED_ARTICLE_REQUIRED')
    snapshot = article.get('published_snapshot', article)
    gate(snapshot, scope)
    if snapshot.get('state') != 'PUBLISHED':
        raise ValueError('PUBLISHED_REVISION_REQUIRED')
    stage = 'BUILD'
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        artifact = build()
        stage = 'DEPLOY'
        release = deploy(artifact)
        stage = 'VERIFY'
        result = verify(artifact, release)
        if result.get('ok') is not True:
            raise ValueError('STATIC_VERIFICATION_FAILED')
    except Exception:
        link = '/?zar_workspace=sites#reposnewsEditor'
        emit(scope, 'PUBLISH_FAILED', 'static-failed:'+article_id+':'+stamp,
             'PUBLISH_FAILED', 'Falló el paso '+stage+'. La revisión editorial se conserva.',
             link, article_id, 'ARTICLE', [{'label': 'RETRY', 'url': link}, {'label': 'DETAILS', 'url': link}],
             details={'stage': stage, 'timestamp': stamp})
        raise
    url = release['url'].rstrip('/')+'/es/repositorios/'+article_id+'/'
    emit(scope, 'PUBLISH_SUCCESS', 'static-published:'+article_id+':'+release['commit'],
         'PUBLICACIÓN COMPLETADA · '+snapshot['title_es'], url, url, article_id, 'ARTICLE',
         [{'label': 'VER ARTÍCULO', 'url': url}, {'label': 'ABRIR REPOSNEWS', 'url': release['url']}],
         details={'timestamp': stamp, 'commit': release['commit']}, status='COMPLETED')
    return release
