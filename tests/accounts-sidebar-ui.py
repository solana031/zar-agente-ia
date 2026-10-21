"""Only primary navigation: actual sidebar/drawer markup and CSS, mocked registry GET."""
import json,os,re
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'app/templates/index.html').read_text(encoding='utf-8')
styles=''.join(re.findall(r'<style\b[^>]*>.*?</style>',source,re.S))
start=source.index('<aside class="side">');side=source[start:source.index('</aside>',start)+8]
start=source.index('<div id="mobileDrawer"');depth=0;end=start
for match in re.finditer(r'<div\b[^>]*>|</div>',source[start:]):
    depth+=-1 if match.group().startswith('</') else 1
    if depth==0:end=start+match.end();break
drawer=source[start:end]
shell='<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+styles+'<link rel="stylesheet" href="/static/workspace-tabs.css"></head><body><div class="app">'+side+'<main class="main"><header class="top"><button id="menu">Menú</button></header></main></div>'+drawer+'''<script>
window.closeMobileDrawer=()=>document.getElementById('mobileDrawer').hidden=true;
window.newChat=()=>{};
document.getElementById('menu').onclick=()=>{document.getElementById('mobileDrawer').hidden=false;};
</script><script src="/static/workspace-tabs.js"></script></body></html>'''

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('ZAR_TEST_BROWSER'))
    for width,height in [(1440,900),(390,844)]:
        page=browser.new_page(viewport={'width':width,'height':height});errors=[];calls=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        statuses=['CONNECTED','PERMISSION_REQUIRED','REAUTH_REQUIRED','DISCONNECTED','CONNECTED']
        failed=False
        def route(r):
            url=r.request.url
            if '/static/' in url:return r.fulfill(path=str(ROOT/'app/static'/url.split('/')[-1]),headers={'Content-Type':'text/css; charset=utf-8' if url.endswith('.css') else 'text/javascript; charset=utf-8'})
            if '/api/' in url:
                calls.append((r.request.method,url));assert url.endswith('/api/accounts/connections') and r.request.method=='GET'
                if failed:return r.fulfill(status=503,json={'ok':False})
                return r.fulfill(json={'ok':True,'providers':[{'id':k,'status':s} for k,s in zip(['google','youtube','instagram','tiktok','shopify'],statuses)]})
            if url.endswith('/accounts'):return r.fulfill(content_type='text/html',body='<h1>CUENTAS global existente</h1>')
            return r.fulfill(content_type='text/html',body=shell)
        page.route('**/*',route);page.goto('https://zar.test/')
        scope='.side' if width>1100 else '#mobileDrawer'
        if width<=1100:page.locator('#menu').click()
        button=page.locator(scope+' [data-zwt-open=accounts]')
        expect(button).to_be_visible();expect(button.locator('small')).to_have_text('3 PENDIENTES')
        assert button.count()==1
        assert page.locator(scope).get_by_role('button',name=re.compile('Nueva conversación')).count()==1
        order=page.locator(scope+' .zwtAgentNav >button').all_text_contents()
        assert 'Chat' in order[0] and 'CUENTAS' in order[1] and 'Nueva conversación' in order[2],order
        box=button.bounding_box();assert box['y']>=0 and box['y']+box['height']<=height
        assert page.locator(scope).evaluate('e=>e.scrollTop')==0
        assert page.locator('.zwtLaunchers [data-zwt-open=accounts]').count()==0
        assert page.locator(scope).get_by_role('button',name=re.compile('Cuenta Google|Identity Center|Reautorizar Google')).count()==0
        page.screenshot(path=str(ROOT/'.local'/f'accounts-sidebar-{width}.png'))
        # Agent controls stay visible while the rest of the menu scrolls.
        page.locator(scope).evaluate('e=>e.scrollTop=e.scrollHeight')
        box=button.bounding_box();assert box['y']>=0 and box['y']+box['height']<=height
        button.click();expect(page.locator('iframe[title=CUENTAS]')).to_be_visible()
        assert page.locator('iframe[title=CUENTAS]').get_attribute('src')=='/accounts'
        if width<=1100:expect(page.locator('#mobileDrawer')).to_be_hidden()
        statuses=['CONNECTED']*5;page.reload()
        if width<=1100:page.locator('#menu').click()
        expect(page.locator(scope+' .zwtAccountsBadge')).to_have_text('✓ CONECTADAS')
        statuses=['UNKNOWN']*5;page.reload()
        if width<=1100:page.locator('#menu').click()
        expect(page.locator(scope+' .zwtAccountsBadge')).to_have_text('SIN VERIFICAR')
        failed=True;page.reload()
        if width<=1100:page.locator('#menu').click()
        expect(page.locator(scope+' .zwtAccountsBadge')).to_have_text('SIN VERIFICAR')
        assert not errors,errors
        assert calls and all(method=='GET' for method,_ in calls)
        page.close()
    browser.close()
print(json.dumps({'desktop':'PASS','mobile':'PASS','visible_without_scroll':'PASS','sticky_on_scroll':'PASS','pending_badge':3,'all_connected_badge':'PASS','unknown_not_connected':'PASS','opens_existing_center':'PASS','duplicates':0,'provider_mutations':0}))
