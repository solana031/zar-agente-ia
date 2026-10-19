"""Focused general Workspace UI: mocked APIs, no Google writes."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=(ROOT/'app/static/workspace-creator.js').read_text(encoding='utf-8')
CSS=(ROOT/'app/static/workspace-creator.css').read_text(encoding='utf-8')
COMPANY=(ROOT/'app/static/company-workspace.js').read_text(encoding='utf-8')

def check(width):
    rows=[{'id':'fixture-job-'+str(i),'request':{'type':'DOC','title':'Documento '+str(i)},'state':'COMPLETED','stage':'PREVIEW','file_id':'persistent-file-'+str(i),'created_at':'2026-10-19T00:00:00Z','result':{'url':'https://docs.google.com/document/d/persistent-file-'+str(i)+'/edit','validation':{'status':'VERIFIED','check':'native content'}}} for i in range(8)]
    posts=[];company_reads=[]
    def api(route):
        url=route.request.url
        if url.endswith('/notifications'):
            route.fulfill(content_type='application/json',body=json.dumps({'ok':True,'csrf':'fixture-csrf','items':[]}));return
        if url.endswith('/company-workspace'):
            company_reads.append(url);route.fulfill(content_type='application/json',body=json.dumps({'ok':True,'csrf':'fixture-csrf','workspace':{'revision':0,'profile':{},'sources':[],'history':[]}}));return
        if route.request.method=='POST':
            payload=route.request.post_data_json;posts.append(payload)
            assert route.request.headers['x-zar-business-csrf']=='fixture-csrf'
            job={'id':payload['request_id'],'request':payload,'state':'QUEUED','stage':'PLAN','created_at':'2026-10-19T01:00:00Z'};rows.append(job)
            route.fulfill(content_type='application/json',body=json.dumps({'ok':True,'job':job}));return
        route.fulfill(content_type='application/json',body=json.dumps({'ok':True,'jobs':rows}))
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':width,'height':900})
        page.route('**/*',lambda r:r.abort())
        page.route('https://zar.test/workspace',lambda r:r.fulfill(content_type='text/html',body='<meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:12px;background:#100d0a}</style><main></main>'))
        page.route('**/api/**',api);page.goto('https://zar.test/workspace');page.clock.install()
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.add_style_tag(content=CSS);page.add_script_tag(content=COMPANY);page.add_script_tag(content=SCRIPT)
        page.evaluate("window.openZarWorkspace(document.querySelector('main'))")
        expect(page.get_by_role('heading',name='ZAR Workspace',exact=True)).to_be_visible()
        expect(page.locator('.gwJob')).to_have_count(6);assert company_reads==[]
        page.get_by_role('button',name='Siguiente',exact=True).click();expect(page.locator('.gwJob')).to_have_count(2)
        edit=page.get_by_role('link',name='Editar el mismo archivo',exact=True).first
        assert edit.get_attribute('href').startswith('/workspace-artifact/fixture-job-')
        page.get_by_label('Tipo de archivo',exact=True).select_option('SLIDES');page.get_by_label('Diseño',exact=True).select_option('EDITORIAL')
        page.get_by_label('Título',exact=True).fill('Presentación desde Workspace')
        page.get_by_label('Contenido y objetivo',exact=True).fill('Una presentación original para el equipo.')
        page.get_by_role('button',name='Crear archivo Google',exact=True).click()
        expect(page.locator('[data-gw-feedback]')).to_contain_text('Solicitud guardada')
        assert len(posts)==1 and posts[0]['type']=='SLIDES' and posts[0]['theme']=='EDITORIAL'
        assert len(posts[0]['request_id'])>=12 and posts[0]['source_article_id']==''
        page.clock.fast_forward(21000);expect(page.get_by_label('Título',exact=True)).to_have_value('Presentación desde Workspace')
        page.get_by_text('Empresa y documentos fuente',exact=True).click()
        expect(page.get_by_role('heading',name='Workspace · Empresa',exact=True)).to_be_visible();assert len(company_reads)==1
        assert page.evaluate('document.documentElement.scrollWidth')<=width
        assert errors==[]
        page.screenshot(path=str(ROOT/'.local/instagram-worker'/('workspace-creator-'+str(width)+'.png')))
        browser.close()

if __name__=='__main__':
    for width in (1440,390):check(width);print('PASS',width)
