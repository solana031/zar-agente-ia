"""Offline desktop/mobile policy controls; every network request is intercepted."""
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright


async def check():
    source = Path('app/static/reposnews-editor.js').read_text(encoding='utf8')
    errors = []; posts = []
    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch(headless=True, executable_path=os.environ.get('ZAR_TEST_BROWSER'))
        for width in (1440, 390):
            context = await browser.new_context(viewport={'width': width, 'height': 900})
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            state = {'project_id': 'fixture', 'articles': [], 'legal_status': {'fields': {}},
                     'autonomous_editorial_status': {'enabled': False, 'last_status': 'NOT_RUN', 'published': 0}}
            async def route(request):
                if request.request.url.endswith('/fixture'):
                    return await request.fulfill(content_type='text/html', body='<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>*{box-sizing:border-box}body{margin:12px;font:16px system-ui}button{min-height:44px;max-width:100%;white-space:normal}section{max-width:100%;overflow-wrap:anywhere}table{width:100%}</style></head><body><div id="zwSites"></div><script src="/editor.js"></script></body></html>')
                if request.request.url.endswith('/editor.js'):
                    return await request.fulfill(content_type='text/javascript', body=source)
                if '/api/holdings/workflows/reposnews_' in request.request.url:
                    payload = request.request.post_data_json
                    if request.request.url.endswith('autonomous_configure'):
                        posts.append(payload)
                        state['autonomous_editorial_status']['enabled'] = payload['enabled']
                    return await request.fulfill(content_type='application/json', body=json.dumps({'ok': True, 'result': state}))
                raise AssertionError('Unexpected network request: ' + request.request.url)
            await context.route('**/*', route)
            await page.goto('https://fixture.test/fixture')
            await page.evaluate("window.dispatchEvent(new CustomEvent('zar-workflow-state',{detail:{csrf:'fixture-csrf'}}))")
            enable = page.get_by_role('button', name='Activar generación y publicación automática', exact=True)
            await enable.wait_for(timeout=5000)
            assert await enable.is_visible()
            assert await page.locator('[data-autonomous-editorial]').evaluate('(el)=>!el.closest("details")')
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            await enable.click()
            pause = page.get_by_role('button', name='Pausar publicación automática', exact=True)
            await pause.wait_for()
            assert posts[-1] == {'enabled': True, 'authorize_publication': True}
            await pause.click()
            await enable.wait_for()
            assert posts[-1] == {'enabled': False, 'authorize_publication': False}
            await context.close()
        assert not errors, errors
        await browser.close()
    print('PASS: desktop/mobile, visible policy, enable/pause payloads, no external requests, no JS errors')


asyncio.run(check())
