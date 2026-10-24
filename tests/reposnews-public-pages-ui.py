"""Offline browser checks for public information pages and cover presentation."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from flask import Flask
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]

async def check():
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ZAR_DATA_DIR': tmp}):
        from app import reposnews as rn
        articles = [rn.article_defaults(a) for a in json.loads((ROOT/'app/reposnews_content.json').read_text(encoding='utf-8'))]
        for a in articles:
            a['published'] = True
        legal = dict(controller='Fixture owner', privacy_contact='fixture@example.test', activity_mode='NONCOMMERCIAL', entity_type='PERSON', processing_basis='Fixture approved legal basis', retention='Fixture approved retention', providers_reviewed=True)
        rn.write(dict(owner='owner', articles=articles, legal=legal, legal_reviewed=True))
        app = Flask(__name__, template_folder=str(ROOT/'app/templates'))
        app.before_request(rn.public_dispatch)
        rn.register(app, lambda: 'owner')
        client = app.test_client()
        proof = ROOT/'.local/reposnews-polish-2026-10'
        proof.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, executable_path=os.environ.get('ZAR_TEST_BROWSER'))
            for width in (1440, 390):
                context = await browser.new_context(viewport={'width':width,'height':1000}, reduced_motion='reduce')
                page = await context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                async def route(route):
                    response = client.get(route.request.url, base_url=rn.ORIGIN)
                    await route.fulfill(status=response.status_code, body=response.data, headers={'content-type':response.content_type})
                await context.route('**/*', route)
                for lang in ('es','en'):
                    for slug in ('about','contact','privacy','cookies','legal',''):
                        await page.goto(f'{rn.ORIGIN}/{lang}/{slug+"/" if slug else ""}')
                        await page.locator('main h1').wait_for()
                        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, lang, slug)
                        main = await page.locator('main').inner_text()
                        assert 'ACTION_REQUIRED' not in main
                        if slug in ('privacy','legal'):
                            assert 'Fixture owner' in main
                        else:
                            assert 'Fixture owner' not in main
                        if slug == 'privacy':
                            assert 'Fixture approved legal basis' in main
                            assert 'Fixture approved retention' in main
                            assert await page.locator('#instagram-deletion').count() == 1
                            assert await page.locator('a[href="https://www.aepd.es/"]').count() == 1
                        if not slug:
                            await page.locator('.grid').scroll_into_view_if_needed()
                            await page.locator('.card img').evaluate_all("els=>Promise.all(els.map(i=>i.decode()))")
                            frames = await page.locator('.card-visual').evaluate_all("els=>els.map(e=>({w:e.clientWidth,h:e.clientHeight}))")
                            assert len(frames) == len(articles)
                            assert all(abs(f['w']/f['h']-1.6)<.03 for f in frames), frames
                            for image in await page.locator('.card img').all():
                                assert await image.evaluate('i=>i.naturalWidth>0 && !!i.alt')
                            first = page.locator('.card h2 a').first
                            target = await first.get_attribute('href')
                            await first.click()
                            assert page.url.endswith(target)
                            assert await page.locator('.article-cover').count() == 1
                            await page.goto(f'{rn.ORIGIN}/{lang}/')
                            await page.locator('.grid').scroll_into_view_if_needed()
                        if lang == 'es' and slug in ('about','privacy','cookies',''):
                            await page.screenshot(path=str(proof/f'{slug or "home"}-{width}.png'), full_page=bool(slug))
                assert not await context.cookies(), 'No cookies before language selection'
                await page.locator('[data-lang="es"]').click()
                cookies = await context.cookies()
                assert len(cookies)==1 and cookies[0]['name']=='reposnews_lang' and cookies[0]['value']=='es'
                assert not errors, errors
                await context.close()
            await browser.close()
    print(json.dumps({'widths':[1440,390], 'languages':['es','en'], 'pages':6, 'overflow':False, 'covers_loaded':True, 'legal_identity_preserved':True, 'language_cookie':'PASS', 'article_navigation':'PASS', 'js_errors':0}))

if __name__ == '__main__':
    asyncio.run(check())
