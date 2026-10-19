"""Focused notification UI contract; no provider requests or real publication."""
import json,re
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=(ROOT/'app/static/notification-center.js').read_text(encoding='utf-8-sig')
CSS=(ROOT/'app/static/notification-center.css').read_text(encoding='utf-8-sig')
LEGACY=(ROOT/'app/static/reposnews-approval.js').read_text(encoding='utf-8-sig')
EDITOR=(ROOT/'app/static/reposnews-editor.js').read_text(encoding='utf-8-sig')

def check(width,height,standalone=False):
    items=[
        {'id':'ready','type':'ARTICLE_READY','title':'REA','editorial':{'preview_es':'/reposnews-preview/es/rea','reel':'https://www.instagram.com/reel/example/'},'article':{'id':'rea','approval_request':'exact-revision-token'}},
        {'id':'update','type':'ARTICLE_UPDATE_READY','title':'Actualización REA','entity_id':'revision-1','approval_request':'update-exact-token','deep_link':'/reposnews-revision/revision-1/es'},
        {'id':'ambiguous','type':'ARTICLE_NEEDS_DISAMBIGUATION','title':'Necesito un dato','inbox_item_id':'a'*24,'editorial':{'reel':'https://www.instagram.com/reel/unknown/'}},
        {'id':'failed','type':'ARTICLE_FAILED','title':'No se pudo completar','inbox_item_id':'b'*24,'message':'PROVIDER_503 technical details '*30},
        {'id':'doc','type':'DOC_READY','title':'Documento listo','completed':True,'actions':[{'label':'ABRIR EN GOOGLE','url':'https://docs.google.com/document/d/demo/edit'}]}
    ]+[{'id':'info'+str(i),'type':'SYSTEM_ACTION_REQUIRED','title':'Información '+str(i)} for i in range(12)]
    items[5].update(type='ARTICLE_NEEDS_DISAMBIGUATION',processing=True,editorial={'reel':'https://www.instagram.com/reel/reprocessing/'})
    payload={'ok':True,'csrf':'fixture','items':items,'unread':len(items),'historical':{}}
    posts=[]
    def api(route):
        if route.request.method=='POST':
            body=route.request.post_data_json;posts.append((route.request.url,body))
            if route.request.url.endswith('/read'):
                for row in items:
                    if body.get('all') or row['id']==body.get('id'):
                        if 'dismissed' in body:row['dismissed_at']='now' if body['dismissed'] else None
                        row['read_at']=None if body.get('unread') else 'now'
            if route.request.url.endswith('inbox_resolve'):
                items[2].update(type='SYSTEM_ACTION_REQUIRED',completed=True,title='Identificación recibida')
            route.fulfill(content_type='application/json',body=json.dumps({'ok':True}));return
        payload['unread']=sum(not n.get('read_at') and not n.get('dismissed_at') for n in items)
        route.fulfill(content_type='application/json',body=json.dumps(payload))
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':width,'height':height})
        page.route('**/*',lambda r:r.abort())
        page.route('**/api/**',api)
        page.route('**/static/notification-center.css*',lambda r:r.fulfill(content_type='text/css',body=CSS))
        html='<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}body.zarEmbedded .top{display:none}</style></head><body class="'+('zarEmbedded' if standalone else '')+'"><header class="top"><div class="topActions"></div></header><main id="zwSites"><section id="reposnewsEditor"><h2>Contenido del sitio</h2><table></table></section></main></body></html>'
        page.route(re.compile(r'^https://zar\.test/($|\?|frame)'),lambda r:r.fulfill(content_type='text/html',body=html))
        page.goto('https://zar.test/'+('?zar_workspace=sites' if standalone else ''))
        page.clock.install();page.add_script_tag(content=SCRIPT)
        bell=page.locator('#zarNotificationBell');expect(bell).to_be_visible();bell.click()
        panel=page.locator('#zarNotificationCenter');expect(panel).to_be_visible()
        expect(panel.locator('.znCard')).to_have_count(8)
        assert not panel.locator('details').first.is_visible() or not panel.locator('details').first.get_attribute('open')
        expect(panel.locator('[data-note=failed] .znMessage')).not_to_contain_text('PROVIDER_503')
        expect(panel.locator('[data-note=info0]')).to_contain_text('Reanalizando el Reel')
        expect(panel.locator('[data-note=info0] form')).to_have_count(0)
        page.screenshot(path=str(ROOT/'.local/instagram-worker'/('notification-redesign-'+str(width)+('-standalone' if standalone else '')+'.png')))
        field=panel.locator('[data-resolve=ambiguous] input');field.fill('Evidence preserved')
        page.clock.fast_forward(21000);expect(field).to_have_value('Evidence preserved')
        assert panel.evaluate('(e)=>e.getBoundingClientRect().width')<=min(width,460)
        assert panel.evaluate('(e)=>e.getBoundingClientRect().right')<=width
        if width>600:assert panel.evaluate('(e)=>e.getBoundingClientRect().left')>=width-480
        else:assert panel.evaluate('(e)=>e.getBoundingClientRect().height')==height
        assert bell.evaluate('(e)=>e.getBoundingClientRect().height')>=44
        assert page.evaluate('document.documentElement.scrollWidth')<=width
        panel.locator('[data-action=publish][data-id=ready]').click()
        expect(panel.locator('[data-action=publish][data-id=ready]')).to_be_enabled()
        assert any(b.get('approval_request')=='exact-revision-token' and b.get('decision')=='PUBLICAR' for _,b in posts)
        panel.locator('[data-action=update][data-id=update]').click()
        expect(panel.locator('[data-action=update][data-id=update]')).to_be_enabled()
        assert any(b.get('approval_request')=='update-exact-token' for _,b in posts)
        panel.locator('[data-resolve=ambiguous] button').click()
        expect(panel.get_by_text('Identificación recibida',exact=True)).to_be_visible()
        assert any(b.get('name')=='Evidence preserved' and b.get('id')=='a'*24 for _,b in posts)
        panel.locator('[data-action=retry][data-id=failed]').click()
        expect(panel.locator('[data-action=retry][data-id=failed]')).to_be_enabled()
        assert any(u.endswith('inbox_recover') and b.get('id')=='b'*24 for u,b in posts)
        panel.locator('[data-action=dismiss][data-id=doc]').click()
        expect(panel.locator('[data-note=doc]')).to_have_count(0)
        panel.locator('[data-action=archive]').click();expect(panel.locator('[data-note=doc]')).to_be_visible()
        panel.locator('[data-action=restore][data-id=doc]').click();expect(panel.locator('[data-note=doc]')).to_have_count(0)
        panel.locator('[data-close]').click();expect(panel).not_to_be_visible()
        if not standalone:
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.add_script_tag(content=LEGACY)
            # Reuse actual legacy rendering with an editorial status fixture.
            # The status endpoint gets its own exact response rather than a provider mock.
            page.route('**/api/holdings/workflows/reposnews_status',lambda r:r.fulfill(content_type='application/json',body=json.dumps({'ok':True,'result':{'project_id':'fixture','articles':[{'id':'real-history-shape','title_es':'Artículo con revisión','state':'READY_PRIVATE','history':[{'at':'today','reason':'Approved revision without fields'}]}],'editorial_notifications':[],'domain_status':'ACTIVE'}})))
            # The summary may arrive before the editor's independent status call.
            page.evaluate("window.dispatchEvent(new CustomEvent('zar-workflow-state',{detail:{csrf:'fixture'}}))")
            expect(page.locator('#zarReposNewsSiteSummary')).to_be_visible()
            page.locator('#reposnewsEditor').evaluate('(e)=>e.remove()')
            page.add_script_tag(content=EDITOR)
            page.evaluate("window.dispatchEvent(new CustomEvent('zar-workflow-state',{detail:{csrf:'fixture'}}))")
            expect(page.locator('#zarReposNewsSiteSummary')).to_be_visible()
            assert page.locator('#zarReposNewsSiteSummary').evaluate("(e)=>Boolean(e.compareDocumentPosition(document.querySelector('#reposnewsEditor')) & Node.DOCUMENT_POSITION_FOLLOWING)")
            expect(page.get_by_text('Notification Center · Reels → ReposNews',exact=True)).to_have_count(0)
            expect(page.get_by_text('Artículo con revisión',exact=True)).to_be_visible()
            assert errors==[]
            page.evaluate("document.body.insertAdjacentHTML('beforeend','<iframe src=\"/frame\"></iframe>')")
            frame=page.frames[-1] if len(page.frames)>1 else None
            page.locator('iframe').wait_for()
            page.frame_locator('iframe').locator('body').wait_for()
            frame=page.frames[-1];frame.add_script_tag(content=SCRIPT)
            assert frame.locator('#zarNotificationBell').count()==0
            assert page.locator('#zarNotificationBell').count()==1
        browser.close()

if __name__=='__main__':
    for case in [(1440,900,False),(390,844,False),(390,844,True)]:
        check(*case);print('PASS',case)
