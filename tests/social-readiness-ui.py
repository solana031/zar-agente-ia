"""Private publishing UI only; all APIs and confirmations are offline fixtures."""
import json,os
from pathlib import Path
from flask import Flask,render_template
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
ID='0123456789abcdef'
record={'title':'WorldMonitor fixture','project':{'title':'WorldMonitor fixture'},'payload':{'master_brief':'Private fixture'},'status':'PRODUCED','video_state':'READY_PRIVATE','artifact':'fixture.mp4','render':{'duration':45,'width':1080,'height':1920},'voice':{'provider':'FIXTURE'},'music':{'status':'NONE'},'providers':[],'scenes':[],'publication':{}}
record['required_approval_phrase']='APRUEBO PUBLICAR WORLDMONITOR'
app=Flask(__name__,template_folder=str(ROOT/'app/templates'))
with app.test_request_context():html=render_template('text_video.html',record=record,identifier=ID)
connections={p:{'status':'CONNECTED' if p=='instagram' else 'DISCONNECTED' if p=='tiktok' else 'AUTH_REQUIRED','ready':p=='instagram','account':'zaragente031' if p=='instagram' else None,'permissions':['instagram_business_content_publish'] if p=='instagram' else [],'last_verified':'2026-10-19T21:00:00Z','connect_url':'/api/reposnews/instagram/connect?publishing=1' if p=='instagram' else 'https://developers.tiktok.com/apps/' if p=='tiktok' else '/connect/google?service=youtube','human_action':'Connect operational account'} for p in ['instagram','tiktok','youtube']}
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=os.environ.get('ZAR_TEST_BROWSER'))
 for width in (1440,390):
  page=browser.new_page(viewport={'width':width,'height':900});errors=[];calls=[];dialogs=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.on('dialog',lambda dialog:(dialogs.append(dialog.message),dialog.accept()))
  def route(r):
   url=r.request.url
   if '/static/' in url:return r.fulfill(path=str(ROOT/'app/static'/url.split('/')[-1].split('?')[0]))
   if url.endswith('/video-project/'+ID):return r.fulfill(content_type='text/html',body=html)
   if '/api/' not in url:return r.abort()
   if r.request.method=='POST':
    data=r.request.post_data_json;calls.append((url,data));assert r.request.headers['x-zar-business-csrf']=='fixture'
    if url.endswith('/readiness'):result={'ok':True,'result':connections}
    elif url.endswith('/prepare'):result={'ok':True,'result':{'ready_to_publish':True,'approval_request':'offline-fixture','options':data,'checks':{p:{'ready':True,'account':'zaragente031','privacy':'PUBLIC_REEL'} for p in data['platforms']}}}
    elif url.endswith('/confirm'):
     assert data['approval_phrase']=='APRUEBO PUBLICAR WORLDMONITOR'
     assert data['rights_confirmed'] and data['confirmed'] and data['options']['platforms']==['instagram']
     result={'ok':True,'result':{}}
    else:raise AssertionError('Unexpected mutation '+url)
   elif url.endswith('/notifications'):result={'ok':True,'csrf':'fixture','items':[{'id':'fixture-partial','type':'PUBLISH_FAILED','title':'PUBLICACIÓN PARCIAL','message':'2/3 destinos completados','status':'ACTION_REQUIRED','actions':[{'label':'REINTENTAR TIKTOK','url':'/video-project/'+ID+'#publish'},{'label':'VER INSTAGRAM','url':'https://www.instagram.com/reel/fixture/'}]}]}
   else:result={'ok':True,'projects':[dict(record,id=ID)]}
   r.fulfill(json=result)
  page.route('**/*',route);page.goto('https://zar.test/video-project/'+ID)
  expect(page.locator('[name=platform][value=instagram]')).to_be_enabled()
  expect(page.locator('[name=platform][value=tiktok]')).to_be_disabled();expect(page.locator('[name=platform][value=youtube]')).to_be_disabled()
  expect(page.get_by_role('link',name='CONECTAR TIKTOK',exact=True)).to_be_visible()
  page.locator('[name=platform][value=instagram]').check()
  page.get_by_role('button',name='Comprobar redes · no publica',exact=True).click()
  expect(page.locator('[data-social-confirm]')).to_be_disabled();page.locator('[name=rights]').check()
  expect(page.locator('[data-social-confirm]')).to_be_disabled()
  page.locator('[name=approval_phrase]').fill('APRUEBO PUBLICAR WORLDMONITOR')
  expect(page.locator('[data-social-confirm]')).to_be_enabled()
  page.locator('[name=caption]').fill('Metadata changed');expect(page.locator('[data-social-confirm]')).to_be_disabled()
  page.get_by_role('button',name='Comprobar redes · no publica',exact=True).click();expect(page.locator('[data-social-confirm]')).to_be_enabled()
  page.locator('[data-social-confirm]').click();expect(page.locator('[data-social-feedback]')).to_contain_text('Confirmación guardada')
  assert len(dialogs)==1 and len([c for c in calls if c[0].endswith('/confirm')])==1
  page.get_by_role('button',name='Notificaciones',exact=False).click()
  expect(page.get_by_role('heading',name='PUBLICACIÓN PARCIAL',exact=True)).to_be_visible()
  expect(page.get_by_role('link',name='REINTENTAR TIKTOK',exact=True)).to_be_visible()
  assert page.evaluate('document.documentElement.scrollWidth')<=width
  assert not errors,errors
  page.screenshot(path=str(ROOT/'.local'/('social-readiness-'+str(width)+'.png')))
  page.close()
 browser.close()
print(json.dumps({'widths':[1440,390],'checkbox_readiness':'PASS','metadata_invalidation':'PASS','one_confirmation':'PASS','partial_notification':'PASS','real_uploads':0}))
