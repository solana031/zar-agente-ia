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
    responses.update({static.ORIGIN+'/sitemap.xml': sitemap.encode(), static.ORIGIN+'/media/reposnews/home.png': b'public-image', static.ORIGIN+'/media/reposnews/editorial.css': b'body{color:green}'})
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
