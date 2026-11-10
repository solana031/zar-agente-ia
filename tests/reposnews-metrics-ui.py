"""Browser regression for the ReposNews metrics card, with fully simulated APIs."""
import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://zar.example.test'


def fixture():
    daily = [{'date': f'2026-11-{day:02}', 'clicks': day % 3, 'impressions': day * 18,
              'ctr': .01, 'position': 8.4} for day in range(1, 11)]
    return {
        'connect_url': '/connect/google?force=1&purpose=accounts&service=site_metrics',
        'accounts': [{'id': 'a', 'email': 'search@example.test', 'active': True},
                     {'id': 'b', 'email': 'ads@example.test', 'active': False}],
        'providers': {
            'search_console': {
                'status': 'READY', 'checked_at': '2026-11-10T22:00:00Z', 'stale': False,
                'data': {'start_date': '2026-10-14', 'end_date': '2026-11-10',
                         'timezone': 'America/Los_Angeles', 'empty': False,
                         'totals': {'clicks': 17, 'impressions': 2080, 'ctr': 17/2080, 'position': 8.4},
                         'previous': {'clicks': 0, 'impressions': 0},
                         'daily': daily, 'first_incomplete_date': '2026-11-10',
                         'latest_date': '2026-11-10',
                         'top_pages': [{'url': 'https://www.reposnews.com/es/repositorios/un-proyecto-largo-con-un-slug-descriptivo/',
                                        'clicks': 3, 'impressions': 80}]},
            },
            'adsense': {'status': 'READY', 'checked_at': '2026-11-10T22:00:00Z', 'stale': False,
                        'data': {'account_state': 'READY', 'site_state': 'NEEDS_ATTENTION',
                                 'auto_ads_enabled': False, 'sites': []}},
        },
    }


async def check():
    proof = ROOT / '.local' / 'reposnews-metrics-ui'
    proof.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, executable_path=os.environ.get('ZAR_TEST_BROWSER'))
        for width in (1440, 390):
            context = await browser.new_context(viewport={'width': width, 'height': 1000}, reduced_motion='reduce')
            page = await context.new_page()
            data = fixture()
            errors = []
            requests = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            async def route(request):
                path = request.request.url.removeprefix(ORIGIN)
                if path.startswith('/static/'):
                    file = ROOT / 'app' / path.lstrip('/')
                    await request.fulfill(body=file.read_bytes(), content_type='text/css' if file.suffix == '.css' else 'application/javascript')
                elif path == '/api/notifications':
                    await request.fulfill(json={'ok': True, 'csrf': 'TEST'})
                elif path.startswith('/api/holdings/workflows/reposnews_metrics_'):
                    body = request.request.post_data_json
                    requests.append(body)
                    service = body.get('provider')
                    if service and 'account_id' in body:
                        data['providers'][service]['selected_account'] = body['account_id']
                    await request.fulfill(json={'ok': True, 'result': deepcopy(data)})
                else:
                    await request.fulfill(content_type='text/html', body='''<!doctype html>
<html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/static/reposnews-metrics.css">
<style>body{margin:0;background:#111;color:#e7d7bc;font:16px system-ui}main{max-width:1100px;margin:auto;padding:16px;box-sizing:border-box}</style>
<main><section id="zarReposNewsSiteSummary"><h2>ReposNews</h2></section></main>
<script src="/static/reposnews-metrics.js"></script></html>''')

            await context.route('**/*', route)
            await page.goto(ORIGIN)
            host = page.locator('#zarReposNewsMetrics')
            await host.get_by_role('button', name='Actualizar ahora').wait_for()
            await page.wait_for_function("document.querySelectorAll('#zarReposNewsMetrics .rn-metrics-stat strong')[0]?.textContent==='17'")
            await host.get_by_text('Requiere atención', exact=True).wait_for()
            text = await host.inner_text()
            assert ('2080' in text or '2.080' in text) and 'Requiere atención' in text
            assert 'Datos provisionales' in text
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
            await host.locator('[data-rn-metrics-details="daily"] summary').click()
            assert await host.locator('tbody tr').count() >= 10
            await host.locator('[data-rn-metrics-account="adsense"]').select_option('b')
            await page.wait_for_function("document.querySelector('[data-rn-metrics-account=adsense]')?.value==='b'")
            assert any(r.get('account_id') == 'b' for r in requests)
            await host.get_by_role('button', name='Actualizar ahora').click()
            await host.get_by_role('button', name='Actualizar ahora').wait_for(state='visible')
            await page.wait_for_function("!document.querySelector('[data-rn-metrics-refresh]')?.disabled")
            assert await host.locator('[data-rn-metrics-details="daily"]').get_attribute('open') is not None
            await page.screenshot(path=str(proof / f'card-{width}.png'), full_page=True)

            # Unavailable data retains an unknown metric, never a fabricated zero.
            data['providers']['search_console'].update(status='NEEDS_PERMISSION', data=None, checked_at=None)
            await host.get_by_role('button', name='Actualizar ahora').click()
            await page.wait_for_function("document.querySelectorAll('#zarReposNewsMetrics .rn-metrics-stat strong')[0]?.textContent==='—'")
            assert 'Falta permiso o acceso' in await host.inner_text()
            assert not errors, errors
            await context.close()
        await browser.close()
    print(json.dumps({'widths': [1440, 390], 'clicks_impressions': 'PASS', 'adsense_attention': 'PASS',
                      'daily_details': 'PASS', 'account_selection': 'PASS', 'unknown_metrics': 'PASS',
                      'js_errors': 0, 'overflow': False}))


if __name__ == '__main__':
    asyncio.run(check())
