"""Exercise the explicit finite-backlog action with simulated authenticated APIs."""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def check():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, executable_path=os.environ.get('ZAR_TEST_BROWSER'))
        for width in (1440, 390):
            context = await browser.new_context(viewport={'width': width, 'height': 1000})
            page = await context.new_page()
            errors, requests = [], []
            status_delay = False
            status_gate = asyncio.Event()
            page.on('pageerror', lambda error: errors.append(str(error)))

            async def route(request):
                path = request.request.url.split('example.test', 1)[-1]
                if path.startswith('/static/'):
                    await request.fulfill(body=(ROOT / 'app' / path.lstrip('/')).read_bytes(),
                                          content_type='application/javascript')
                elif path == '/api/reposnews/history/start':
                    assert request.request.headers['x-zar-business-csrf'] == 'TEST'
                    requests.append(request.request.post_data_json)
                    await request.fulfill(json={'ok': True})
                elif path.startswith('/api/holdings/workflows/'):
                    if status_delay:
                        await status_gate.wait()
                    await request.fulfill(json={'ok': True, 'result': {'articles': []}})
                elif path == '/api/holdings/workflows':
                    await request.fulfill(json={'ok': True, 'csrf': 'TEST', 'sites': []})
                else:
                    await request.fulfill(content_type='text/html', body='''<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<section id="orchestrationWorkspace"><div id="orchestrationWorkspaceInner">
<section id="zarBusinessWorkflows"><section id="zwSites"></section></section></div></section>
<script src="/static/business-workflows.js"></script><script src="/static/reposnews-approval.js"></script>
<script>window.dispatchEvent(new CustomEvent('zar-workflow-state',{detail:{csrf:'TEST'}}));</script>''')

            await context.route('**/*', route)
            await page.goto('https://example.test')
            await page.get_by_role('button', name='Procesar y publicar pendientes', exact=True).click()
            await page.get_by_text('Procesamiento y publicación del lote actual iniciados.', exact=False).wait_for()
            assert requests == [{'reprocess_unresolved': True, 'reuse_media': True, 'authorize_publication': True}]
            await page.get_by_role('button', name='Reanalizar Reels pendientes', exact=True).click()
            await page.get_by_text('Reanálisis iniciado.', exact=False).wait_for()
            assert requests[-1]['authorize_publication'] is False
            assert not errors, errors
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
            # A workspace refresh must preserve the card/actions while its slower
            # editorial request is still pending, including existing editor input.
            await page.evaluate("""() => {
                window.fixtureSummary = document.getElementById('zarReposNewsSiteSummary');
                const editor = document.createElement('section'); editor.id = 'reposnewsEditor';
                editor.innerHTML = '<input value="source under review">';
                document.getElementById('zwSites').append(editor);
            }""")
            status_delay = True
            await page.evaluate('window.zarWorkflowRefresh()')
            assert await page.evaluate("document.getElementById('zarReposNewsSiteSummary') === window.fixtureSummary")
            assert await page.locator('#reposnewsEditor input').input_value() == 'source under review'
            assert await page.get_by_role('button', name='Procesar y publicar pendientes', exact=True).count() == 1
            status_gate.set()
            await context.close()
        await browser.close()
    print('PASS: backlog authorization, reanalysis without publication, CSRF and rendering at 1440/390px')


if __name__ == '__main__':
    asyncio.run(check())
