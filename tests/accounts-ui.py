"""Desktop/mobile account registry, filters, assistants and global sidebar. Offline APIs."""
import json,os
from pathlib import Path
from flask import Flask, render_template
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
app=Flask(__name__,template_folder=str(ROOT/'app/templates'))
with app.test_request_context():html=render_template('accounts.html')
providers=[]
for key,name,category,status in [('google','Google','GOOGLE / PRODUCTIVIDAD','CONNECTED'),('youtube','YouTube','GOOGLE / PRODUCTIVIDAD','CHANNEL_REQUIRED'),('instagram','Instagram','SOCIAL','PARTIAL'),('tiktok','TikTok','SOCIAL','DISCONNECTED'),('shopify','Shopify','COMERCIO','DISCONNECTED')]:
    providers.append({'id':key,'name':name,'category':category,'icon':name[0],'status':status,'account_identity':'zaragente031@gmail.com' if key=='google' else 'zaragente031' if key=='instagram' else None,'used_by':['Workspace'],'last_verified':'2026-10-21T09:00:00Z','capabilities':{'messaging':'READY','publishing':'PERMISSION_REQUIRED'} if key=='instagram' else {},'human_action':'Revisa los permisos de esta función.' if status=='PARTIAL' else None,'diagnostic':{'NEW_TOKEN_PERSISTED':True,'NEW_TOKEN_READBACK':True,'STALE_SOURCE_SELECTED':False} if key=='instagram' else {}})

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get("ZAR_TEST_BROWSER"))
    for width in (1440,390):
        page=browser.new_page(viewport={'width':width,'height':1000});errors=[];calls=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(r):
            url=r.request.url
            if '/static/' in url:return r.fulfill(path=str(ROOT/'app/static'/url.split('/')[-1].split('?')[0]))
            if '/api/accounts/connections' in url:
                if r.request.method=='GET':return r.fulfill(json={'ok':True,'csrf':'fixture','providers':providers})
                calls.append(url)
                assert r.request.headers['x-zar-business-csrf']=='fixture'
                key,action=url.split('/')[-2:]
                if action=='reverify':return r.fulfill(json={'ok':True,'result':next(c for c in providers if c['id']==key)})
                return r.fulfill(json={'ok':True,'assistant':key if key in {'tiktok','shopify'} else None,'url':'/connect/google?service=core'})
            if '/accounts' in url:return r.fulfill(content_type='text/html',body=html)
            if '/?shell' in url:return r.fulfill(content_type='text/html',body='<body><aside class="side"><div class="nav"></div></aside><main class="main"><header class="top"></header></main><script src="/static/workspace-tabs.js"></script></body>')
            r.abort()
        page.route('**/*',route)
        page.goto('https://zar.test/accounts#instagram')
        expect(page.locator('#google .status')).to_have_text('✓ CONECTADA')
        expect(page.locator('#instagram .status')).to_have_text('CONECTADA PARCIALMENTE')
        assert not page.locator('#google .actions [data-action=reconnect]').count()
        expect(page.locator('#instagram [data-action=reconnect]').first).to_be_visible()
        assert page.locator('#instagram').evaluate('e=>e.getBoundingClientRect().top')>=0
        page.get_by_role('button',name='CONECTADAS',exact=True).click()
        assert page.locator('.card').count()==2
        page.get_by_role('button',name='REQUIEREN ATENCIÓN',exact=True).click()
        assert page.locator('.card').count()==4
        page.get_by_role('button',name='TODAS',exact=True).click()
        page.locator('#tiktok .primary').click()
        expect(page.get_by_role('dialog')).to_be_visible()
        expect(page.get_by_role('dialog')).to_contain_text('Todavía no hay OAuth')
        page.get_by_role('button',name='CERRAR',exact=True).click()
        page.locator('#shopify .primary').click()
        expect(page.get_by_role('dialog')).to_contain_text('tienda y su integración Admin API existentes')
        page.get_by_role('button',name='CERRAR',exact=True).click()
        page.locator('#instagram [data-action=reverify]').click()
        expect(page.locator('#notice')).to_have_text('Estado actualizado.')
        assert page.evaluate('document.documentElement.scrollWidth')<=width
        assert page.locator('.card').evaluate_all('(rows)=>rows.every(e=>e.scrollWidth<=e.clientWidth)')
        # Every action fits within its card at both breakpoints.
        assert page.locator('.actions button').evaluate_all('(buttons)=>buttons.every(b=>{const r=b.getBoundingClientRect(),c=b.closest(".card").getBoundingClientRect();return r.left>=c.left&&r.right<=c.right})')
        page.screenshot(path=str(ROOT/'.local'/f'accounts-{width}.png'),full_page=True)
        page.goto('https://zar.test/?shell=1')
        page.locator('[data-zwt-open=accounts]').click()
        expect(page.locator('iframe[title=CUENTAS]')).to_be_visible()
        assert page.locator('iframe[title=CUENTAS]').get_attribute('src')=='/accounts'
        assert not errors,errors
        assert all('/publish' not in url and '/confirm' not in url for url in calls)
        page.close()
    browser.close()
print(json.dumps({'desktop':1440,'mobile':390,'filters':'PASS','assistants':'PASS','sidebar':'PASS','deep_link':'PASS','overflow':'NONE','real_publications':0}))
