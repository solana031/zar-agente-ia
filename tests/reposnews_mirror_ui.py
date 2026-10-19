"""Focused component browser check with simulated APIs; no production mutations."""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def check():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for width in (1440, 390):
            context = await browser.new_context(viewport={'width': width, 'height': 900})
            page = await context.new_page()
            calls, errors = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('dialog', lambda d: errors.append('Unexpected second confirmation'))
            state = {'primary_online': True, 'status': 'SYNCED', 'published_articles_count': 11,
                     'verified_at': '2026-10-19T21:00:00Z', 'parity': 'MIRROR_IN_SYNC'}
            async def route(route):
                request = route.request
                if '/api/reposnews/mirror' in request.url:
                    calls.append((request.method, request.url, request.headers))
                    await route.fulfill(json={'ok': True, 'csrf': 'csrf', 'mirror': state})
                else:
                    html = '<html><head><meta charset="utf-8"></head><body><section id="zwSites"></section><script>window.intervals=new Set();const nativeSet=setInterval,nativeClear=clearInterval;window.setInterval=(...a)=>{const id=nativeSet(...a);intervals.add(id);return id};window.clearInterval=id=>{intervals.delete(id);nativeClear(id)};</script><script>'+ (ROOT/'app/static/reposnews-mirror.js').read_text(encoding='utf-8')+'</script></body></html>'
                    await route.fulfill(body=html, content_type='text/html')
            await context.route('**/*', route)
            await page.goto('http://zar.test/')
            await page.get_by_text('GitHub Pages · SYNCED', exact=False).wait_for()
            assert await page.get_by_role('link', name='ABRIR PRODUCCIÓN').get_attribute('href') == 'https://www.reposnews.com'
            assert await page.get_by_role('link', name='ABRIR MIRROR').get_attribute('href') == 'https://solana031.github.io/'
            await page.get_by_role('button', name='SINCRONIZAR MIRROR').click()
            await page.get_by_text('Mirror en cola.', exact=False).wait_for()
            assert calls[-1][0] == 'POST' and calls[-1][2]['x-zar-business-csrf'] == 'csrf'
            assert await page.evaluate('intervals.size') == 1
            await page.locator('#zwSites').evaluate("e=>e.style.display='none'")
            await page.wait_for_function('intervals.size===0')
            assert not errors, errors
            await context.close()
        await browser.close()
    print(json.dumps({'component_widths': [1440, 390], 'manual_sync': 'PASS', 'csrf': 'PASS', 'second_confirmation': False, 'close_timer_cleanup': 'PASS', 'js_errors': 0}))


if __name__ == '__main__':
    asyncio.run(check())
