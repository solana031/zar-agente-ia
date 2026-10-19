"""Export the public, approved ReposNews surface; never reads editorial/private stores.

Run: python tools/reposnews_static.py [--output dist/reposnews]
Only build-time acquisition needs the public site. Serving the result needs HTTP only.
"""
from argparse import ArgumentParser
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen
import xml.etree.ElementTree as ET

ORIGIN = 'https://www.reposnews.com'
PAGE = re.compile(r'/(?:es|en)/(?:|(?:about|contact|privacy|cookies|legal|repositories|guides|trends)/|(?:repositorios|repositories)/[a-z0-9-]{1,80}/)')
ARTICLE = re.compile(r'/(es/repositorios|en/repositories)/([a-z0-9-]{1,80})/')
ASSET = re.compile(r'/media/reposnews/[a-zA-Z0-9_-]+\.(?:png|svg|jpg|jpeg|webp|css|js)')
PRIVATE = re.compile(r'READY_PRIVATE|AWAITING_APPROVAL|reposnews-preview|https?://(?:localhost|127\.0\.0\.1)|web-production-[\w.-]+|[A-Za-z]:(?:\\|/(?!/))|/(?:tmp|data|worker)/|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|(?:access_token|refresh_token|api_key)["\s]*[:=]', re.I)
STATIC_SEARCH = """<script>document.querySelectorAll('form.search').forEach(f=>{const input=f.querySelector('input');const params=new URLSearchParams(location.search);input.value=params.get('q')||'';let category=params.get('category')||'';function filter(){document.querySelectorAll('.grid>.card').forEach(c=>{c.hidden=!(c.textContent.toLowerCase().includes(input.value.toLowerCase())&&(!category||c.querySelector('.tag').textContent===category))})}f.addEventListener('submit',e=>{e.preventDefault();filter()});document.querySelectorAll('.filters a').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();category=new URL(a.href).searchParams.get('category')||'';filter()}));filter()});</script>"""


class Resources(HTMLParser):
    def __init__(self, origin):
        super().__init__()
        self.origin = origin
        self.assets = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {'img', 'script'}:
            url = attrs.get('src', '')
        elif tag == 'link' and attrs.get('rel') in {'stylesheet', 'icon'}:
            url = attrs.get('href', '')
        else:
            return
        if not url:
            return
        parsed = urlsplit(urljoin(self.origin, url))
        if parsed.netloc != urlsplit(self.origin).netloc or not ASSET.fullmatch(parsed.path):
            raise ValueError('Resource outside the public asset allowlist')
        self.assets.add(parsed.path)


def public_fetch(url):
    with urlopen(url, timeout=45) as response:
        if urlsplit(response.url).netloc != urlsplit(ORIGIN).netloc:
            raise ValueError('Unexpected public-site redirect')
        return response.read()


class ReposNewsStaticBuilder:
    """Input is the live public sitemap and its published HTML snapshots only.

    Deliberately never crawls links or loads a private editorial API. Inject fetch
    for offline tests. A nonempty output is refused to prevent stale private files.
    """
    def __init__(self, output='dist/reposnews', fetch=public_fetch):
        self.output = Path(output)
        self.fetch = fetch

    def build(self):
        if self.output.exists() and any(self.output.iterdir()):
            raise ValueError('Output must be empty; choose a fresh build directory')
        sitemap = self.fetch(ORIGIN + '/sitemap.xml')
        urls = [el.text for el in ET.fromstring(sitemap).iter() if el.tag.split('}')[-1] == 'loc']
        paths = set()
        for url in urls:
            parsed = urlsplit(url or '')
            if parsed.scheme != 'https' or parsed.netloc != urlsplit(ORIGIN).netloc or parsed.query or parsed.fragment or not PAGE.fullmatch(parsed.path):
                raise ValueError('Nonpublic URL in sitemap')
            paths.add(parsed.path)
        articles = {lang: {ARTICLE.fullmatch(p)[2] for p in paths if ARTICLE.fullmatch(p) and p.startswith('/'+lang+'/')} for lang in ('es', 'en')}
        if not articles['es'] or articles['es'] != articles['en'] or not {'/es/', '/en/'}.issubset(paths):
            raise ValueError('Published ES/EN content is incomplete')
        files, assets = {}, set()
        for path in sorted(paths):
            document = self.fetch(ORIGIN + path).decode('utf-8')
            if PRIVATE.search(document) or 'noindex,nofollow' in document:
                raise ValueError('Private data or backend dependency in public HTML: '+path)
            if not all(marker in document for marker in ('rel="canonical"', 'hreflang="es"', 'hreflang="en"', 'og:title')):
                raise ValueError('Missing public SEO: '+path)
            if ARTICLE.fullmatch(path) and 'application/ld+json' not in document:
                raise ValueError('Missing article schema')
            resources = Resources(ORIGIN)
            resources.feed(document)
            assets.update(resources.assets)
            # Include social/schema images as well as rendered image/CSS references.
            assets.update(ASSET.findall(document))
            document = document.replace('</body>', STATIC_SEARCH+'</body>')
            files[path.strip('/')+'/index.html'] = document.encode('utf-8')
        for asset in sorted(assets):
            content = self.fetch(ORIGIN + asset)
            if asset.endswith(('.css', '.js', '.svg')) and (PRIVATE.search(content.decode('utf-8')) or re.search(rb'(?:url\(|@import)', content)):
                raise ValueError('Unresolved or private resource dependency: '+asset)
            files[asset.lstrip('/')] = content
        # A real 200 homepage with the existing ES SEO, rather than a server redirect.
        files['index.html'] = files['es/index.html']
        files['sitemap.xml'] = sitemap
        files['robots.txt'] = ('User-agent: *\nAllow: /\nSitemap: '+ORIGIN+'/sitemap.xml\n').encode()
        report = dict(status='STATIC_HOST_READY', published_articles=len(articles['es']), es=len(articles['es']), en=len(articles['en']), assets=len(assets), pages=len(paths)+1, backend_required=False)
        # Nothing is written until every page and dependency has passed validation.
        for relative, content in files.items():
            target = self.output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (self.output/'build-manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        return report


def build_reposnews_static(output='dist/reposnews', fetch=public_fetch):
    """Future approved-publication hook; builds files, never deploys them."""
    return ReposNewsStaticBuilder(output, fetch).build()


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='dist/reposnews')
    print(json.dumps(build_reposnews_static(parser.parse_args().output), indent=2))
