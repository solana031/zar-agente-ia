"""Actual account card: blocked buttons, read-only retry and recovered OAuth."""
import os,json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=os.environ.get('ZAR_TEST_BROWSER'))
    for width in (1440,390):
        context=browser.new_context(viewport={'width':width,'height':844});page=context.new_page();errors=[];calls=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        row={'id':'instagram','name':'Instagram','category':'SOCIAL','icon':'I','used_by':['ReposNews'],'status':'PROVIDER_BLOCKED','provider_blocked':True,'account_identity':'@zaragente031','provider':'META','reason':'DEVELOPER_ACCOUNT_CONFIRMATION_REQUIRED','human_action':'Meta requiere confirmar la cuenta de desarrollador, pero su flujo de confirmación está fallando.','capabilities':{}}
        def route(r):
            path=urlsplit(r.request.url).path
            if path.startswith('/static/'):return r.fulfill(path=str(ROOT/'app'/path.lstrip('/')))
            if path=='/accounts':return r.fulfill(content_type='text/html',body=(ROOT/'app/templates/accounts.html').read_text(encoding='utf-8'))
            if path=='/shell':return r.fulfill(content_type='text/html',body='<iframe title="CUENTAS" src="/accounts" style="width:100%;height:800px;border:0"></iframe>')
            if path=='/api/accounts/connections':return r.fulfill(json={'csrf':'fixture','providers':[row]})
            if path=='/api/accounts/connections/instagram/reverify':
                calls.append('reverify');assert r.request.headers['x-zar-business-csrf']=='fixture'
                return r.fulfill(json={'ok':True,'result':row})
            if path=='/api/accounts/connections/instagram/connect':
                calls.append('connect');assert not row['provider_blocked']
                return r.fulfill(json={'external':True,'poll_id':'fixture','url':'https://zar.test/oauth/accounts/start/fixture'})
            if path=='/api/accounts/oauth/status/fixture':return r.fulfill(json={'status':'PENDING'})
            if path=='/oauth/accounts/start/fixture':return r.fulfill(content_type='text/html',body='External authorization fixture')
            r.abort();raise AssertionError('Unexpected network '+path)
        context.route('**/*',route);page.goto('https://zar.test/shell');frame=page.frame_locator('iframe')
        expect(frame.locator('#instagram .status')).to_have_text('BLOQUEADA POR META')
        expect(frame.locator('#instagram .identity')).to_have_text('@zaragente031')
        assert frame.get_by_role('button',name='RECONECTAR',exact=True).count()==0
        assert frame.locator('[data-action=reconnect]').count()==0
        expect(frame.get_by_role('link',name='ABRIR META DEVELOPERS')).to_have_attribute('target','_blank')
        frame.get_by_role('button',name='REINTENTAR COMPROBACIÓN').click()
        expect(frame.locator('#notice')).to_have_text('Estado actualizado.')
        assert calls==['reverify'] and len(context.pages)==1
        assert page.frames[1].evaluate('document.documentElement.scrollWidth<=innerWidth')
        row.update(status='AUTH_REQUIRED',provider_blocked=False)
        frame.get_by_role('button',name='REINTENTAR COMPROBACIÓN').click()
        expect(frame.get_by_role('button',name='CONECTAR',exact=True)).to_be_visible()
        with context.expect_page() as new:frame.get_by_role('button',name='CONECTAR',exact=True).click()
        new.value.wait_for_url('https://zar.test/oauth/accounts/start/fixture')
        assert calls==['reverify','reverify','connect']
        assert page.frames[1].url=='https://zar.test/accounts'
        assert not errors,errors
        context.close()
    browser.close()
print(json.dumps({'blocked_ui':'PASS','desktop':1440,'mobile':390,'no_oauth_while_blocked':'PASS','recovered_oauth_enabled':'PASS','real_publications':0}))
