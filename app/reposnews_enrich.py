"""Expand short published ReposNews guides into complete ones (AdSense content quality).

One article per cycle: research the official repository again, draft a longer guide with
the normal builder (same evidence/command checks and independent review) and file it as
a private update proposal. Nothing is published without the owner's decision; the owner
can approve all expansions at once from ZAR Sites.
"""
import hashlib
import time

from . import holdings, reposnews as rn, reposnews_automation as auto

TARGET_WORDS = 700
SPACING = 600
RETRY = 86400
_last = 0


def words(article, lang='es'):
    return len(str(article.get('body_' + lang) or '').split())


def candidates(data):
    pending = {r['article_id'] for r in data.get('article_revisions', []) if r.get('state') == 'ARTICLE_UPDATE_DRAFT'}
    now = time.time()
    rows = [a for a in data.get('articles', []) if a.get('published') and a['id'] not in pending
            and min(words(a, 'es'), words(a, 'en')) < TARGET_WORDS and a.get('repository_url')
            and now - (a.get('enrich_job') or {}).get('at', 0) > RETRY and (a.get('enrich_job') or {}).get('attempts', 0) < 3]
    return sorted(rows, key=lambda a: words(a))


def status(data):
    published = [a for a in data.get('articles', []) if a.get('published')]
    short = [a for a in published if min(words(a, 'es'), words(a, 'en')) < TARGET_WORDS]
    pending = [r for r in data.get('article_revisions', []) if r.get('state') == 'ARTICLE_UPDATE_DRAFT' and r.get('kind') == 'ENRICHMENT']
    return {'published': len(published), 'short': len(short), 'pending': len(pending), 'target_words': TARGET_WORDS,
            'median_words': sorted(words(a) for a in published)[len(published) // 2] if published else 0}


def tick():
    global _last
    if time.time() - _last < SPACING:
        return None
    _last = time.time()
    with holdings.transaction('reposnews-editorial'):
        data = rn.read()
        if not data.get('owner') or holdings.read(data['owner']).get('global_stop'):
            return None
        rows = candidates(data)
        if not rows:
            return None
        target = rows[0]
        job = target.setdefault('enrich_job', {})
        job.update(at=time.time(), attempts=job.get('attempts', 0) + 1)
        repo = target['repository_url'].removeprefix('https://github.com/').strip('/')
        rn.write(data)
    from . import reposnews_inbox as inbox
    try:
        candidate = inbox.build(inbox.research(repo), target.get('discovery_source') or '')
    except Exception as exc:  # Provider/validation failures retry tomorrow; never partial publish.
        with holdings.transaction('reposnews-editorial'):
            data = rn.read()
            article = next((a for a in data.get('articles', []) if a['id'] == target['id']), None)
            if article:
                article.setdefault('enrich_job', {})['error'] = str(exc)[:60] if str(exc).isupper() else 'ENRICH_FAILED'
                rn.write(data)
        return None
    if min(words(candidate, 'es'), words(candidate, 'en')) <= min(words(target, 'es'), words(target, 'en')):
        return None
    return propose(target['id'], candidate)


def propose(article_id, candidate):
    from .reposnews_revisions import diff, identity
    from .reposnews_covers import VISUAL_FIELDS
    with holdings.transaction('reposnews-editorial'):
        data = rn.read()
        old = next((a for a in data.get('articles', []) if a['id'] == article_id), None)
        if not old:
            return None
        # Same article, same URLs and visuals: only the text grows.
        for key in VISUAL_FIELDS + ('seo', 'source_reels', 'discovery_source', 'inbox_item_id', 'github_stars', 'cover_spec'):
            if key in old:
                candidate[key] = old[key]
        candidate.update(id=old['id'], canonical_entity_id=identity(old)['entity_id'], published_at=old.get('published_at'))
        before, after = words(old), words(candidate)
        identifier = hashlib.sha256((old['id'] + auto.revision(old) + auto.revision(candidate)).encode()).hexdigest()[:24]
        revisions = data.setdefault('article_revisions', [])
        if not any(r['article_revision_id'] == identifier for r in revisions):
            revisions.append({'article_revision_id': identifier, 'article_id': old['id'], 'inbox_item_id': old.get('inbox_item_id'),
                              'kind': 'ENRICHMENT', 'base_revision': auto.revision(old),
                              'base_published_revision': auto.revision(old.get('published_snapshot', old)), 'old_snapshot': dict(old),
                              'draft': candidate, 'state': 'ARTICLE_UPDATE_DRAFT', 'approval_status': 'PENDING',
                              'source_reels': candidate.get('source_reels', []), 'updated_at': holdings._now(),
                              'verified_at': candidate.get('checked_at'),
                              'change_summary': 'Guía ampliada con fuentes oficiales: %d → %d palabras (casos de uso, errores comunes, alternativas y preguntas frecuentes).' % (before, after),
                              'diff': diff(old, candidate)})
        old.setdefault('enrich_job', {}).update(proposed=identifier, error=None)
        rn.write(data)
    return identifier


def approve_all(scope):
    """Owner decision (authenticated session) applying every pending expansion."""
    from . import reposnews_revisions as revisions
    data = rn.read()
    ids = [r['article_revision_id'] for r in data.get('article_revisions', []) if r.get('state') == 'ARTICLE_UPDATE_DRAFT' and r.get('kind') == 'ENRICHMENT']
    applied, failed = 0, 0
    for ident in ids:
        current = next((r for r in rn.read().get('article_revisions', []) if r['article_revision_id'] == ident), None)
        if not current:
            continue
        try:
            revisions.decide(scope, {'id': ident, 'decision': 'ACTUALIZAR', 'approval_request': revisions.token(scope, current)})
            applied += 1
        except ValueError:
            failed += 1
    return {'applied': applied, 'failed': failed}
