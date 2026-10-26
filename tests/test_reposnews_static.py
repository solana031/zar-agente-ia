import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('reposnews_static', Path(__file__).parents[1]/'tools/reposnews_static.py')
static = importlib.util.module_from_spec(spec)
spec.loader.exec_module(static)


def public_fixture():
    paths = ['/es/', '/en/', '/es/repositorios/approved/', '/en/repositories/approved/']
    sitemap = '<urlset>'+''.join('<url><loc>'+static.ORIGIN+p+'</loc></url>' for p in paths)+'</urlset>'
    html = '<html><head><link rel="canonical" href="https://www.reposnews.com/es/"><link hreflang="es"><link hreflang="en"><meta property="og:title"><link rel="stylesheet" href="/media/reposnews/editorial.css"></head><body><img src="/media/reposnews/home.png"><script type="application/ld+json">{}</script></body></html>'
    responses = {static.ORIGIN+p: html.encode() for p in paths}
    responses.update({static.ORIGIN+'/sitemap.xml': sitemap.encode(), static.ORIGIN+'/media/reposnews/home.png': b'public-image', static.ORIGIN+'/media/reposnews/editorial.css': b'body{color:green}', static.ORIGIN+'/ads.txt': b'existing public publisher record'})
    return responses


def test_published_bilingual_assets_seo_only(tmp_path):
    responses = public_fixture()
    responses[static.ORIGIN+'/reposnews-preview/es/draft'] = b'PRIVATE DRAFT'
    report = static.build_reposnews_static(tmp_path, responses.__getitem__)
    assert report['published_articles'] == report['es'] == report['en'] == 1
    assert report['assets'] == 2 and not report['backend_required']
    for name in ['index.html', 'es/index.html', 'en/index.html', 'es/repositorios/approved/index.html', 'en/repositories/approved/index.html', 'sitemap.xml', 'robots.txt']:
        assert (tmp_path/name).is_file()
    assert (tmp_path/'media/reposnews/home.png').read_bytes() == b'public-image'
    assert (tmp_path/'ads.txt').read_bytes() == b'existing public publisher record'
    assert all(b'PRIVATE DRAFT' not in p.read_bytes() for p in tmp_path.rglob('*') if p.is_file())
    with pytest.raises(ValueError, match='empty'):
        static.build_reposnews_static(tmp_path, responses.__getitem__)


@pytest.mark.parametrize('bad', ['/reposnews-preview/es/draft', '/es/repositorios/../secret/', '/api/reposnews', 'https://evil.example/es/'])
def test_reject_private_or_unsafe_sitemap(tmp_path, bad):
    responses = public_fixture()
    responses[static.ORIGIN+'/sitemap.xml'] = ('<urlset><url><loc>'+ (bad if bad.startswith('https:') else static.ORIGIN+bad) +'</loc></url></urlset>').encode()
    with pytest.raises(ValueError, match='Nonpublic'):
        static.build_reposnews_static(tmp_path, responses.__getitem__)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('leak', ['READY_PRIVATE', 'http://localhost:8000/image.png', 'refresh_token=secret', 'C:\\worker\\frame.png', '/reposnews-preview/es/draft'])
def test_no_private_data(tmp_path, leak):
    responses = public_fixture()
    responses[static.ORIGIN+'/es/'] += leak.encode()
    with pytest.raises(ValueError, match='Private'):
        static.build_reposnews_static(tmp_path, responses.__getitem__)
    assert not list(tmp_path.iterdir())


def test_primary_cmp_probe_and_inert_ad_tags_are_not_static_dependencies(tmp_path):
    responses=public_fixture()
    primary='''<script nonce="fixture" type="text/plain" data-adsense-prepared="consent-required" async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-0000000000000001" crossorigin="anonymous"></script>
<script nonce="fixture" defer src="/media/reposnews/consent.js" data-probe-origin="https://web-production-private.up.railway.app"></script>
<script nonce="fixture" async src="https://fundingchoicesmessages.google.com/i/pub-0000000000000001?ers=1" data-google-cmp="official-loader"></script>'''
    for path in list(responses):
        if path.endswith('/'):
            responses[path]=responses[path].replace(b'</head>',primary.encode()+b'</head>')
    before=dict(responses)
    report=static.build_reposnews_static(tmp_path,responses.__getitem__)
    assert report['published_articles']==1
    assert responses==before # Primary HTML remains unchanged.
    for page in tmp_path.rglob('*.html'):
        text=page.read_text(encoding='utf-8')
        assert not static.PRIVATE.search(text)
        assert 'data-probe-origin' not in text and 'consent.js' not in text
        assert 'adsbygoogle' not in text and 'fundingchoicesmessages' not in text
        assert 'rel="canonical"' in text and 'application/ld+json' in text


@pytest.mark.parametrize('payload',[
    '<script src="/media/reposnews/consent.js">refresh_token=private</script>',
    '<a href="https://web-production-private.up.railway.app/accounts">Private account</a>',
    '<script>fetch("https://web-production-private.up.railway.app/api/private")</script>',
    '<script type="text/plain" data-adsense-prepared="consent-required" src="https://evil.example/adsbygoogle.js"></script>',
])
def test_projection_never_scrubs_other_private_content_or_unrecognized_tags(tmp_path,payload):
    responses=public_fixture();responses[static.ORIGIN+'/en/']+=payload.encode()
    with pytest.raises(ValueError):static.build_reposnews_static(tmp_path,responses.__getitem__)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('prose',['<p>Access the installed interface at `http://localhost:4318`.</p>', '<pre><code>Open http://127.0.0.1:4318 after installation.</code></pre>'])
def test_documented_local_installation_is_not_a_runtime_dependency(tmp_path,prose):
    responses=public_fixture();responses[static.ORIGIN+'/en/']=responses[static.ORIGIN+'/en/'].replace(b'</body>',prose.encode()+b'</body>')
    static.build_reposnews_static(tmp_path,responses.__getitem__)
    assert prose in (tmp_path/'en/index.html').read_text()


@pytest.mark.parametrize('active',[
 '<p><a href="http://localhost:4318">Open interface</a></p>',
 '<p><img src="http://127.0.0.1:4318/private.png"></p>',
 '<p><script>fetch("http://localhost:4318/private")</script></p>',
 '<style>body{background:url(http://localhost:4318/private.png)}</style>',
 '<!-- http://localhost:4318/private -->',
 '<p>READY_PRIVATE</p>',
])
def test_documented_loopback_exception_cannot_allow_private_runtime_or_other_secrets(tmp_path,active):
    responses=public_fixture();responses[static.ORIGIN+'/en/']=responses[static.ORIGIN+'/en/'].replace(b'</body>',active.encode()+b'</body>')
    with pytest.raises(ValueError):static.build_reposnews_static(tmp_path,responses.__getitem__)
    assert not list(tmp_path.iterdir())
