"""Offline popup/callback regressions with real accounts iframe and isolated providers."""
import json, os
from pathlib import Path
from urllib.parse import urlsplit
from flask import Flask
from playwright.sync_api import sync_playwright, expect
from app.oauth_transport import page as callback_page

ROOT=Path(__file__).resolve().parents[1]
app=Flask(__name__)
app.secret_key='TEST-only-callback-session'
with app.test_request_context():
    callbacks={p:callback_page(p.title(),'CONNECTED',200).get_data(as_text=True) for p in ('instagram','google','youtube','tiktok')}

with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=os.environ.get('ZAR_TEST_BROWSER'))
    for width in (1440,390,393,412):
        for provider,blocked in [('instagram',False),('google',False),('youtube',False),('tiktok',False)]:
            context=browser.new_context(viewport={'width':width,'height':844},user_agent='Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Version/4.0 Chrome/130.0 Mobile Safari/537.36' if width<600 else None)
            state={'completed':False,'verified':False,'checks':0,'starts':0}
            errors=[]
            row={'id':provider,'name':provider.title(),'category':'SOCIAL','icon':'I','status':'REAUTH_REQUIRED','used_by':['Workspace'],'capabilities':{}}
            def route(r):
                u=urlsplit(r.request.url);path=u.path
                if path.startswith('/static/'):
                    return r.fulfill(path=str(ROOT/'app'/path.lstrip('/')))
                if u.netloc in ('oauth.instagram.test','oauth.google.test'):
                    assert r.request.is_navigation_request() and r.request.frame.parent_frame is None
                    return r.fulfill(content_type='text/html',body='<h1>Proveedor externo simulado</h1><a href="https://zar.test/callback">ACEPTAR PRUEBA</a>')
                if path=='/callback':
                    state['completed']=True
                    return r.fulfill(content_type='text/html',body=callbacks[provider])
                if path=='/accounts':return r.fulfill(content_type='text/html',body=(ROOT/'app/templates/accounts.html').read_text(encoding='utf-8'))
                if path=='/shell':return r.fulfill(content_type='text/html',body='<iframe title="CUENTAS" src="/accounts" style="width:100%;height:790px;border:0"></iframe>')
                if path=='/deep':return r.fulfill(content_type='text/html',body='<a href="/accounts#'+provider+'">RECONECTAR</a><script src="/static/oauth-launcher.js"></script>')
                if path=='/api/accounts/connections':return r.fulfill(json={'csrf':'TEST','providers':[{**row,'status':'CONNECTED' if state['verified'] else 'REAUTH_REQUIRED'}]})
                if path.endswith('/reconnect'):
                    if state.get('fail_launch'):return r.fulfill(status=503,json={'error':'TEST_UNAVAILABLE'})
                    assert r.request.method=='POST' and r.request.headers['x-zar-business-csrf']=='TEST'
                    assert r.request.post_data_json=={'external':True}
                    state['starts']+=1
                    return r.fulfill(json={'external':True,'poll_id':'fixture','url':'https://zar.test/oauth/accounts/start/fixture'})
                if path.endswith('/reverify'):
                    assert state['completed'], 'Untrusted message must not trigger reverify'
                    state['checks']+=1;state['verified']=True
                    return r.fulfill(json={'ok':True,'result':{**row,'status':'CONNECTED'}})
                if path=='/api/accounts/oauth/status/fixture':return r.fulfill(json={'status':'CONNECTED' if state['completed'] else 'PENDING'})
                if path=='/oauth/accounts/start/fixture':
                    host='oauth.instagram.test' if provider=='instagram' else 'oauth.google.test'
                    return r.fulfill(content_type='text/html',body='<script>location.replace('+json.dumps('https://'+host+'/oauth/authorize')+')</script>')
                r.abort();raise AssertionError('Unexpected network: '+u.netloc+path)
            context.route('**/*',route)
            parent=context.new_page();parent.on('pageerror',lambda e:errors.append(str(e)))
            parent.goto('https://zar.test/shell')
            frame=parent.frame_locator('iframe')
            if blocked:
                parent.frames[1].evaluate('window.open=()=>null')
                frame.locator('.primary').click()
                expect(frame.locator('#zarOAuthNotice')).to_contain_text('Tu navegador ha bloqueado')
                with context.expect_page() as new:
                    frame.get_by_role('link',name='ABRIR AUTORIZACIÓN',exact=True).click()
            else:
                with context.expect_page() as new:frame.locator('.primary').click()
            popup=new.value;popup.wait_for_url('https://'+('oauth.instagram.test' if provider=='instagram' else 'oauth.google.test')+'/**')
            assert parent.frames[1].url=='https://zar.test/accounts'
            expect(frame.locator('.status')).to_have_text('AUTORIZANDO…')
            # Both a wrong origin with the correct source, and a same-origin
            # message with an unrelated source must be ignored.
            parent.frames[1].evaluate('''p=>{
                dispatchEvent(new MessageEvent('message',{origin:location.origin,source:parent,data:{type:'zar-oauth-result',provider:p,status:'CONNECTED'}}));
            }''',provider)
            if not blocked:
                popup.evaluate('p=>opener.postMessage({type:"zar-oauth-result",provider:p,status:"CONNECTED"},"https://zar.test")',provider)
            parent.wait_for_timeout(150)
            assert state['checks']==0
            popup.get_by_role('link',name='ACEPTAR PRUEBA').click()
            expect(popup.locator('body')).to_contain_text('Cuenta conectada correctamente.')
            expect(frame.locator('.status')).to_have_text('✓ CONECTADA',timeout=12000)
            assert state['checks']==1 and state['starts']==1
            assert parent.frames[1].url=='https://zar.test/accounts'
            if not blocked:popup.wait_for_event('close',timeout=5000)
            # Reconnection links emitted by the different modules share the
            # same capture handler rather than navigating their workspaces.
            parent.goto('https://zar.test/deep');state.update(completed=False,verified=False)
            with context.expect_page() as deep:parent.get_by_role('link',name='RECONECTAR').click()
            deep.value.wait_for_url('https://'+('oauth.instagram.test' if provider=='instagram' else 'oauth.google.test')+'/**')
            assert parent.url=='https://zar.test/deep'
            parent.evaluate('sessionStorage.removeItem("zar-accounts-oauth")')
            parent.goto('https://zar.test/accounts');state['fail_launch']=True
            parent.locator('.primary').click()
            expect(parent.locator('#notice')).to_contain_text('No se pudo abrir la autorización')
            expect(parent.locator('#zarOAuthNotice')).to_contain_text('No se pudo abrir la autorización')
            expect(parent.locator('.status')).to_have_text('REQUIERE RECONEXIÓN')
            assert not errors,errors
            context.close()
    for width in (1440,390,393,412):
        context=browser.new_context(viewport={'width':width,'height':844},user_agent='Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Version/4.0 Chrome/130.0 Mobile Safari/537.36' if width<600 else None)
        state={'completed':False,'verified':False,'checks':0,'starts':0}
        provider='google'
        row={'id':provider,'name':'Google','category':'GOOGLE','icon':'G','status':'REAUTH_REQUIRED','used_by':['Workspace'],'capabilities':{}}
        with app.test_request_context():
            from flask import session
            session['zar_auth']=True
            callbacks['google']=callback_page('Google','CONNECTED',200).get_data(as_text=True)
        context.route('**/*',route)
        page=context.new_page();page.goto('https://zar.test/shell')
        page.frames[1].evaluate('window.open=()=>null')
        page.frame_locator('iframe').locator('.primary').click()
        page.wait_for_url('https://oauth.google.test/**')
        assert len(context.pages)==1 and len(page.frames)==1
        page.get_by_role('link',name='ACEPTAR PRUEBA').click()
        page.wait_for_url('https://zar.test/accounts')
        expect(page.locator('.status')).to_contain_text('CONECTADA',timeout=12000)
        assert state['starts']==1 and state['checks']==1
        context.close()
    browser.close()
print(json.dumps({'desktop':'PASS','mobile':'PASS','iframe_unchanged':'PASS','instagram_google_youtube_tiktok':'PASS','blocked_popup_automatic_top_navigation':'PASS','callback_refresh':'PASS','origin_and_source':'PASS','deep_links':'PASS','real_grants':0,'publications':0}))

# Recovery and layout: no initialization probes, no success on cancellation,
# provider-specific setup errors, and the rest of the batch survives a failure.
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=os.environ.get('ZAR_TEST_BROWSER'))
    for width in (320,390,1440):
        context=browser.new_context(viewport={'width':width,'height':900},user_agent='Mozilla/5.0 (Linux; Android 14; Pixel Build/TEST; wv) Chrome/130.0 Mobile Safari/537.36')
        errors=[];checks=[];reads={'accounts':0}
        rows=[dict(id=p,name=n,icon=i,category=c,status=s,used_by=['Workspace'],capabilities={'publishing':'READY' if s=='CONNECTED' else 'PERMISSION_REQUIRED'},account_identity='cuenta de demostración') for p,n,i,c,s in [
            ('google','Google','G','GOOGLE / PRODUCTIVIDAD','PARTIAL'),('youtube','YouTube','▶','GOOGLE / PRODUCTIVIDAD','CONNECTED'),
            ('instagram','Instagram','◎','SOCIAL','REAUTH_REQUIRED'),('tiktok','TikTok','♪','SOCIAL','DISCONNECTED'),('shopify','Shopify','S','COMERCIO','UNKNOWN')]]
        def recovery_route(r):
            path=urlsplit(r.request.url).path
            if path.startswith('/static/'):return r.fulfill(path=str(ROOT/'app'/path.lstrip('/')))
            if path=='/accounts':return r.fulfill(content_type='text/html',body=(ROOT/'app/templates/accounts.html').read_text(encoding='utf-8'))
            if path=='/api/accounts/connections':
                reads['accounts']+=1
                return r.fulfill(json={'csrf':'fixture' if reads['accounts']==1 else 'rotated-fixture','providers':rows})
            if path.endswith('/instagram/reconnect'):
                assert r.request.headers['x-zar-business-csrf']=='rotated-fixture'
                return r.fulfill(json={'external':True,'poll_id':'recovery','url':'/oauth/accounts/start/recovery'})
            if path.endswith('/tiktok/connect'):return r.fulfill(status=409,json={'message':'Configura Login Kit de la app TikTok existente.'})
            if path=='/api/accounts/oauth/status/recovery':return r.fulfill(json={'status':'PENDING'})
            if path.endswith('/reverify'):
                provider=path.split('/')[-2];checks.append(provider)
                if provider=='google':return r.fulfill(status=503,json={'message':'Proveedor temporalmente no disponible'})
                return r.fulfill(json={'result':next(row for row in rows if row['id']==provider)})
            r.abort();raise AssertionError('Unexpected network: '+path)
        context.route('**/*',recovery_route)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('https://zar.test/accounts');expect(page.locator('.card')).to_have_count(5)
        assert checks==[], 'Opening accounts must not block buttons on provider calls'
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        output=ROOT/'artifacts'/'connections';output.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(output/('accounts-'+str(width)+'.png')),full_page=True)
        page.locator('#instagram .actions .primary').click()
        expect(page.get_by_role('button',name='COPIAR ENLACE PARA CHROME')).to_be_visible()
        page.get_by_role('button',name='CANCELAR',exact=True).click()
        expect(page.locator('#zarOAuthNotice')).to_contain_text('Autorización cancelada')
        assert checks==[], 'Cancellation cannot reverify an old token and claim success'
        expect(page.locator('#instagram .status')).to_have_text('REQUIERE RECONEXIÓN')
        page.get_by_role('button',name='CERRAR',exact=True).click()
        page.locator('#tiktok .actions .primary').click()
        expect(page.locator('#zarOAuthNotice')).to_contain_text('Configura Login Kit')
        page.get_by_role('button',name='CERRAR',exact=True).click()
        page.get_by_role('button',name='REVERIFICAR TODAS',exact=True).click()
        expect(page.locator('#notice')).to_contain_text('No se pudo comprobar: Google')
        assert checks==['google','youtube','instagram','tiktok','shopify']
        assert not errors,errors
        context.close()
    browser.close()
print(json.dumps({'cancel_without_false_success':'PASS','provider_error_message':'PASS','batch_continues_on_failure':'PASS','layout_320_390_1440':'PASS','webview':'PASS'}))
