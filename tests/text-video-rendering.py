"""Actual Clipper and private project DOM, with mocked APIs and no social uploads."""
import json
from pathlib import Path
from flask import Flask,render_template
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
ID='0123456789abcdef'
CLIPPER_HTML="""<meta name="viewport" content="width=device-width,initial-scale=1">
<body class="zarBusinessPane" data-workspace-type="clipper"><main id="orchestrationWorkspaceInner">
<header class="zwtSubappHeader"><button onclick="document.getElementById('zarBusinessWorkflows').insertAdjacentHTML('beforeend','<div id=zarMediaWorkflowMount></div>');this.remove()">Abrir Clipper</button></header>
<details id="zoDebug" open><section id="zarBusinessWorkflows"></section></details></main></body>"""


def check(width):
    record={'title':'Guía original','project':{'title':'Guía original'},'payload':{'master_brief':'Una guía privada'},'status':'PRODUCED','video_state':'READY_PRIVATE','artifact':'fixture.mp4','render':{'duration':45,'width':1080,'height':1920},'voice':{'provider':'FIXTURE'},'music':{'status':'NONE'},'providers':[],'scenes':[],'publication':{}}
    app=Flask(__name__,template_folder=str(ROOT/'app/templates'))
    with app.test_request_context():html=render_template('text_video.html',record=record,identifier=ID)
    rows=[dict(record,id=ID if i==0 else 'fixture-'+str(i)) for i in range(8)];posts=[]
    def api(route):
        url=route.request.url
        if url.endswith('/notifications'):data={'ok':True,'csrf':'fixture-csrf','items':[]}
        elif route.request.method=='POST':
            data=route.request.post_data_json;posts.append((url,data));assert route.request.headers['x-zar-business-csrf']=='fixture-csrf'
            if url.endswith('/prepare'):
                data={'ok':True,'result':{'ready_to_publish':True,'approval_request':'fixture-approval','checks':{p:{'ready':True,'account':'Cuenta de prueba','privacy':'private'} for p in data['platforms']}}}
            elif url.endswith('/confirm'):
                assert data=={'approval_request':'fixture-approval','confirmed':True,'rights_confirmed':True};data={'ok':True,'result':{}}
            else:data={'ok':True,'project':{'id':ID}}
        else:data={'ok':True,'projects':rows}
        route.fulfill(content_type='application/json',body=json.dumps(data))
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':width,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.abort());page.route('https://zar.test/clipper',lambda r:r.fulfill(content_type='text/html',body=CLIPPER_HTML))
        page.route('**/api/**',api)
        page.route('**/static/*',lambda r:r.fulfill(path=str(ROOT/'app/static'/r.request.url.split('/')[-1].split('?')[0])))
        page.route('https://zar.test/video-project/'+ID,lambda r:r.fulfill(content_type='text/html',body=html))
        page.goto('https://zar.test/clipper');page.add_style_tag(path=str(ROOT/'app/static/workspace-tabs.css'));page.add_style_tag(path=str(ROOT/'app/static/text-video.css'));page.add_script_tag(path=str(ROOT/'app/static/text-video.js'))
        page.get_by_role('button',name='Abrir Clipper',exact=True).click()
        expect(page.get_by_role('heading',name='De texto a vídeo terminado')).to_be_visible();expect(page.locator('[data-tv-projects] .tvCard')).to_have_count(6)
        page.get_by_role('button',name='Siguiente',exact=True).click();expect(page.locator('[data-tv-projects] .tvCard')).to_have_count(2)
        page.get_by_label('¿Sobre qué quieres el vídeo?').fill('Explica cuatro pasos para preparar contenido original.')
        page.get_by_role('button',name='Crear vídeo privado',exact=True).click();expect(page.locator('[data-tv-feedback]')).to_contain_text('Proyecto guardado')
        assert len(posts)==1 and posts[0][1]['duration']==45 and len(posts[0][1]['request_id'])>=12
        assert page.evaluate('document.documentElement.scrollWidth')<=width
        page.evaluate("document.body.dataset.workspaceType='sites'")
        expect(page.locator('#zarTextVideoCreator')).to_be_hidden()
        page.goto('https://zar.test/video-project/'+ID)
        expect(page.locator('[data-social-form] [name=title]')).to_have_value('Guía original')
        expect(page.locator('[data-social-confirm]')).to_be_disabled()
        page.locator('[name=platform][value=instagram]').check();page.locator('[name=platform][value=youtube]').check()
        page.get_by_role('button',name='Comprobar redes · no publica',exact=True).click();expect(page.locator('[data-social-checks] .tvCard')).to_have_count(2)
        assert len(posts)==2 and posts[-1][0].endswith('/prepare');expect(page.locator('[data-social-confirm]')).to_be_disabled()
        page.locator('[name=rights]').check();expect(page.locator('[data-social-confirm]')).to_be_enabled()
        page.locator('[data-social-form] [name=caption]').fill('Texto cambiado exige otro dry-run');expect(page.locator('[data-social-confirm]')).to_be_disabled()
        page.get_by_role('button',name='Comprobar redes · no publica',exact=True).click();expect(page.locator('[data-social-confirm]')).to_be_enabled()
        page.locator('[data-social-confirm]').click();expect(page.locator('[data-social-feedback]')).to_contain_text('Confirmación guardada')
        assert len([url for url,_ in posts if url.endswith('/confirm')])==1
        assert page.evaluate('document.documentElement.scrollWidth')<=width;assert errors==[]
        page.screenshot(path=str(ROOT/'.local/instagram-worker'/('text-video-'+str(width)+'.png')));browser.close()


if __name__=='__main__':
    for width in (1440,390):check(width);print('PASS',width)
