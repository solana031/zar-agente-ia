"""Mocked browser proof: public mobile navigation, strict CSP and account-review UI."""
import asyncio,json,os,tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from flask import Flask
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
async def check():
    with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'ZAR_DATA_DIR':tmp}):
        from app import reposnews as rn,reposnews_adsense as ads
        articles=[rn.article_defaults(a) for a in json.loads((ROOT/'app/reposnews_content.json').read_text(encoding='utf-8'))]
        for a in articles:a.update(published=True,published_at='2026-10-20T10:00:00Z')
        articles[0].update(image_kind='REEL_FRAME',image_asset='source-'+'a'*24+'.png',
            assets=[{'source_type':'REEL_FRAME','permission':'REVIEW_REQUIRED','role':'COVER'}])
        rn.write({'owner':'owner','articles':articles,'domain_status':'ACTIVE','publisher':'pub-0000000000000001'})
        app=Flask(__name__,template_folder=str(ROOT/'app/templates'));app.secret_key='fixture'
        app.before_request(rn.public_dispatch);rn.register(app,lambda:'owner');client=app.test_client()
        readiness=ads.view('owner');state={'ok':True,'csrf':'fixture-csrf','sites':[],'media':[],'jev':[],
            'adsense':{'readiness':readiness,'payments':[]},'identity_center':{},'identity':{},'commerce':{},'agency':{}}
        external=[];posts=[];errors=[]
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True,executable_path=os.environ.get('ZAR_TEST_BROWSER'))
            for width in (1440,390):
                context=await browser.new_context(viewport={'width':width,'height':900})
                page=await context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                async def route(route):
                    url=urlsplit(route.request.url)
                    if url.hostname not in {'www.reposnews.com','web-production-a9565.up.railway.app'}:external.append(url.hostname);return await route.abort()
                    if url.path=='/account-fixture':
                        html='<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>*{box-sizing:border-box}body{margin:0;padding:12px;background:#15120e;color:#ead8bb;font:16px system-ui}input,select,textarea{max-width:100%}pre{overflow-wrap:anywhere;white-space:pre-wrap}</style></head><body><div id="orchestrationWorkspace"><div id="orchestrationWorkspaceInner"></div></div><script src="/static/reposnews-adsense.js"></script><script src="/static/business-workflows.js"></script><script>window.zarWorkflowRefresh()</script></body></html>'
                        return await route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html.replace('<head>','<head><meta charset="utf-8">'))
                    if url.path.startswith('/api/holdings/workflows'):
                        if route.request.method=='POST':
                            posts.append({'path':url.path,'data':route.request.post_data_json})
                            if url.path.endswith('/adsense_probe_start'):body={'ok':True,'result':{'nonce':'n'*43,'url':rn.ORIGIN+'/es/#zar-cmp-probe='+'n'*43}}
                            else:body={'ok':True,'result':readiness}
                        else:body=state
                        return await route.fulfill(status=200,content_type='application/json',body=json.dumps(body))
                    if url.path.startswith('/static/'):
                        path=ROOT/'app'/url.path.lstrip('/')
                        return await route.fulfill(status=200,content_type='text/javascript; charset=utf-8',body=path.read_text(encoding='utf-8'))
                    response=client.get(route.request.url,base_url=rn.ORIGIN)
                    return await route.fulfill(status=response.status_code,body=response.data,headers=dict(response.headers))
                await context.route('**/*',route)
                for path in ('/es/','/es/repositorios/uv/','/es/privacy/','/es/cookies/','/es/legal/'):
                    await page.goto(rn.ORIGIN+path);await page.locator('main h1').wait_for()
                    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,path)
                    assert await page.locator('script[data-adsense-prepared]').count()==1
                    assert await page.evaluate("dataLayer.some(x=>x[0]==='consent'&&x[2].ad_storage==='denied')")
                    if path=='/es/repositorios/uv/':
                        image=page.locator('.article-cover');await image.evaluate('(i)=>i.decode()')
                        assert 'editorial-uv.png' in await image.get_attribute('src')
                        assert 'ReposNews' in await image.get_attribute('alt')
                    assert not any(c['name'] not in {'reposnews_lang'} for c in await context.cookies())
                await page.goto(rn.ORIGIN+'/es/')
                await page.get_by_role('link',name='EN',exact=True).click();assert '/en/' in page.url
                assert any(c['name']=='reposnews_lang' and c['value']=='en' for c in await context.cookies())
                await page.get_by_role('textbox',name='Search',exact=True).fill('uv')
                await page.get_by_role('button',name='Search',exact=True).click();assert 'q=uv' in page.url
                await page.goto('https://web-production-a9565.up.railway.app/account-fixture')
                panel=page.locator('#zarAdsenseReadiness');await panel.wait_for()
                assert await panel.locator('dt').count()==10
                assert 'NO' in await panel.inner_text()
                assert await panel.evaluate('(el)=>el.getBoundingClientRect().right<=innerWidth')
                for field in ads.ACCOUNT_FIELDS:await panel.locator('input[name="'+field+'"]').check()
                await panel.locator('form[data-form=adsense-account-review] input[name=confirmed]').check()
                try:await panel.get_by_role('button',name='Guardar revisión de datos').click(timeout=7000)
                except Exception:
                    print(json.dumps({'width':width,'url':page.url,'errors':errors,'panel_text':await panel.inner_text() if await panel.count() else 'MISSING','posts':posts},ensure_ascii=False))
                    raise
                await page.wait_for_timeout(150)
                assert posts and posts[-1]['path'].endswith('/adsense_account_review')
                payload=posts[-1]['data'];assert set(payload)=={'checks','confirmed','tax_status'}
                assert set(payload['checks'])==set(ads.ACCOUNT_FIELDS) and all(x is True for x in payload['checks'].values())
                assert payload['tax_status']=='UNKNOWN'
                await panel.get_by_text('Estado observado en Google · UNKNOWN',exact=True).click()
                observed=panel.locator('form[data-form=adsense-provider-observation]')
                await observed.locator('[name=tax_status]').select_option('IN_REVIEW')
                await observed.locator('[name=PAYEE_NAME_MISMATCH]').check()
                await observed.locator('[name=POSTAL_STREET_MISSING]').check()
                await observed.locator('[name=confirmed]').check()
                await observed.get_by_role('button',name='Guardar comprobación de Google').click()
                await page.wait_for_timeout(100)
                assert posts[-1]['path'].endswith('/adsense_provider_observation')
                assert posts[-1]['data']=={'tax_status':'IN_REVIEW','findings':['PAYEE_NAME_MISMATCH','POSTAL_STREET_MISSING'],'confirmed':True}
                await panel.get_by_text('Disponibilidad de la CMP en AdSense · ACTION_REQUIRED',exact=True).click()
                availability=panel.locator('form[data-form=adsense-provider-availability]')
                await availability.locator('[name=cmp]').select_option('WAITING_FOR_ADSENSE_AVAILABILITY')
                await availability.locator('[name=account_not_approved]').check()
                await availability.locator('[name=confirmed]').check()
                await availability.get_by_role('button',name='Guardar disponibilidad de CMP').click()
                await page.wait_for_timeout(100)
                assert posts[-1]['path'].endswith('/adsense_provider_availability')
                assert posts[-1]['data']=={'cmp':'WAITING_FOR_ADSENSE_AVAILABILITY','account_not_approved':True,'confirmed':True}
                async with page.expect_popup() as opened:
                    await panel.get_by_role('button',name='REVERIFICAR ADSENSE / CMP').click()
                probe_page=await opened.value
                try:
                    await page.wait_for_function("document.querySelector('[data-adsense-probe-status]')?.textContent.includes('Verificación terminada')",timeout=12000)
                except Exception:
                    print(json.dumps({'probe_posts':posts[-2:],'status':await panel.locator('[data-adsense-probe-status]').inner_text(),'popup':probe_page.url,'cmp':await probe_page.locator('html').get_attribute('data-cmp-status'),'errors':errors},ensure_ascii=False))
                    raise
                assert posts[-1]['path'].endswith('/adsense_probe_finish')
                proof=posts[-1]['data'];assert proof['nonce']=='n'*43 and proof['probe']['api'] is False
                assert 'tcString' not in json.dumps(proof)
                assert await probe_page.locator('html').get_attribute('data-cmp-status')=='MISSING'
                await context.close()
            await browser.close()
        assert not external,external
        assert not errors,errors
        print(json.dumps({'desktop':True,'mobile':True,'public_navigation':True,'strict_csp':True,'advertising_requests':0,'account_review_payload':'BOOLEANS_ONLY','errors':errors}))
if __name__=='__main__':asyncio.run(check())
