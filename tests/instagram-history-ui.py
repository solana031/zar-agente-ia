"""Historical status and safe manual reconciliation in the existing Account Center."""
import os,json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=os.environ.get('ZAR_TEST_BROWSER'))
    for width in (1440,390):
        context=browser.new_context(viewport={'width':width,'height':844});page=context.new_page();calls=[];errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        row={'id':'instagram','name':'Instagram','category':'SOCIAL','icon':'I','used_by':['ReposNews'],'status':'UPLOAD_READY',
             'account_identity':'@zaragente031','capabilities':{'messaging':'READY','reel_discovery':'READY','publishing':'READY'},
             'reel_history':{'reels_found':75,'processed':70,'pending':5,'ambiguous':2,'new_drafts':3,'updates_proposed':4,'last_sync':'2026-10-24'}}
        def route(r):
            path=urlsplit(r.request.url).path
            if path.startswith('/static/'):return r.fulfill(path=str(ROOT/'app'/path.lstrip('/')))
            if path=='/accounts':return r.fulfill(content_type='text/html',body=(ROOT/'app/templates/accounts.html').read_text(encoding='utf-8'))
            if path=='/api/accounts/connections':return r.fulfill(json={'csrf':'fixture','providers':[row]})
            if path=='/api/reposnews/history/sync':
                assert r.request.method=='POST' and r.request.headers['x-zar-business-csrf']=='fixture'
                calls.append('sync');return r.fulfill(json={'ok':True,'result':row['reel_history']})
            raise AssertionError('Unexpected request '+path)
        context.route('**/*',route);page.goto('https://zar.test/accounts#instagram')
        expect(page.get_by_role('heading',name='HISTORIAL REELS')).to_be_visible()
        expect(page.get_by_text('Reels encontrados: 75',exact=False)).to_be_visible()
        page.get_by_role('button',name='SINCRONIZAR HISTORIAL',exact=True).click()
        expect(page.locator('#notice')).to_have_text('Sincronización del historial encolada. No publica contenido.')
        assert calls==['sync'] and len(context.pages)==1
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors,errors
        context.close()
    browser.close()
print(json.dumps({'history_ui':'PASS','desktop':1440,'mobile':390,'sync_no_publication':'PASS'}))
