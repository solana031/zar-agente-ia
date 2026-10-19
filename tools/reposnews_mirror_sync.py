"""GitHub runner: derive a noindex mirror from primary PUBLISHED content only."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
try:
    from .reposnews_static import build_reposnews_static, ORIGIN, public_fetch
    from .reposnews_static_host import PREVIEW, verify
except ImportError:
    from reposnews_static import build_reposnews_static, ORIGIN, public_fetch
    from reposnews_static_host import PREVIEW, verify


def manifest(fetch=public_fetch):
    value = json.loads(fetch(ORIGIN+'/mirror-manifest.json'))
    if (value.get('primary_status') != 'PRIMARY_PUBLISHED' or not value.get('articles')
            or value.get('published_articles_count') != len(value['articles'])
            or not re.fullmatch('[a-f0-9]{64}', value.get('source_revision', ''))):
        raise ValueError('PRIMARY_PUBLISHED_MANIFEST_REQUIRED')
    for article in value['articles']:
        if not re.fullmatch('[a-z0-9-]{1,80}', article.get('id', '')) or not re.fullmatch('[a-f0-9]{64}', article.get('revision', '')):
            raise ValueError('PUBLIC_REVISION_REQUIRED')
        if article.get('es') != '/es/repositorios/'+article['id']+'/' or article.get('en') != '/en/repositories/'+article['id']+'/':
            raise ValueError('PUBLIC_SLUG_REQUIRED')
    allowed = {key: value.get(key, '') for key in ('schema','source_revision','source_commit','primary_status','published_articles_count','request_nonce')}
    allowed['articles'] = [{k: a[k] for k in ('id','revision','es','en')} for a in value['articles']]
    return allowed


def unchanged(source, remote):
    try:
        built = datetime.fromisoformat(remote.get('last_static_build', '').replace('Z', '+00:00'))
        recent = (datetime.now(timezone.utc)-built).total_seconds() < 7*86400
    except (ValueError, TypeError):
        recent = False
    return (source['source_revision'] == remote.get('source_revision')
            and source.get('source_commit') == remote.get('source_commit')
            and source.get('request_nonce', '') == remote.get('request_nonce', '')
            and remote.get('mirror_policy') == 'noindex,follow' and recent)


def build_mirror(output, fetch=public_fetch):
    before = manifest(fetch)
    report = build_reposnews_static(output, fetch)
    after = manifest(fetch)
    if before != after:
        raise ValueError('PRIMARY_CHANGED_DURING_BUILD_RETRY_NEXT_RUN')
    if report['published_articles'] != before['published_articles_count']:
        raise ValueError('PRIMARY_ARTICLE_COUNT_MISMATCH')
    root = Path(output)
    for article in before['articles']:
        for lang in ('es', 'en'):
            if not (root/article[lang].strip('/')/'index.html').is_file():
                raise ValueError('PUBLIC_SLUG_PARITY_MISMATCH')
    for page in root.rglob('*.html'):
        text = page.read_text(encoding='utf-8')
        for article in before['articles']:
            if page.as_posix().endswith(article['es'].strip('/')+'/index.html') or page.as_posix().endswith(article['en'].strip('/')+'/index.html'):
                if ORIGIN+article['es'] not in text or ORIGIN+article['en'] not in text:
                    raise ValueError('PUBLIC_SLUG_PARITY_MISMATCH')
        text, count = re.subn(r'(<meta\s+name="robots"\s+content=")[^"]*(")', r'\g<1>noindex,follow\2', text)
        if count != 1:
            raise ValueError('ONE_PUBLIC_ROBOTS_META_REQUIRED')
        page.write_text(text, encoding='utf-8')
    stamp = datetime.now(timezone.utc).isoformat()
    metadata = report | before | {'mirror_policy': 'noindex,follow', 'last_static_build': stamp,
        'last_static_deploy': stamp, 'deploy_status': 'DEPLOYED', 'run_id': os.getenv('GITHUB_RUN_ID', ''),
        'asset_paths': sorted('/'+p.relative_to(root).as_posix() for p in (root/'media/reposnews').iterdir() if p.is_file())}
    (root/'build-manifest.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return metadata


def prepare(output, force=False):
    source = manifest()
    try:
        with urlopen(Request(PREVIEW+'/build-manifest.json', headers={'Cache-Control': 'no-cache'}), timeout=30) as response:
            current = json.loads(response.read())
    except HTTPError as error:
        if error.code != 404:
            raise
        current = {}
    changed = force or not unchanged(source, current)
    if changed:
        build_mirror(output)
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            stream.write('changed='+str(changed).lower()+'\n')
    print(json.dumps({'changed': changed, 'source_revision': source['source_revision']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'verify'])
    parser.add_argument('--output', default='dist/reposnews')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    if args.operation == 'prepare':
        prepare(args.output, args.force)
    else:
        # Pages CDN may briefly serve the preceding deployment during propagation.
        for attempt in range(6):
            try:
                print(json.dumps(verify(args.output)))
                break
            except (HTTPError, ValueError):
                if attempt == 5:
                    raise
                time.sleep(15)
