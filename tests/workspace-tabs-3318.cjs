const fs=require('node:fs'),assert=require('node:assert/strict'),{chromium}=require('playwright');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});try{
 for(const [width,height] of [[390,844],[393,852],[412,915],[1440,900]]){
  const page=await browser.newPage({viewport:{width,height}}),errors=[],posts=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>{const p=new URL(r.request().url()).pathname;if(p==='/')return r.fulfill({contentType:'text/html',body:fs.readFileSync('app/templates/index.html')});if(p.startsWith('/static/')&&fs.existsSync('app'+p))return r.fulfill({contentType:p.endsWith('.css')?'text/css':p.endsWith('.js')?'application/javascript':'image/png',body:fs.readFileSync('app'+p)});if(r.request().method()==='POST')posts.push(p);return r.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,csrf:'fixture',jev:[],sites:[{id:'site1',name:'Sitio existente',state:'DRAFT',relative_url:'/sites/example'}],media:[],skills:[],tasks:[],agents:[],events:[],companies:{},connectors:{},view:{}})});});
  await page.goto('http://zar.test/');await page.waitForFunction(()=>window.WorkspaceTabsManager);
  await page.locator('#input').fill('Borrador de chat conservado');
  for(const type of ['sites','dropshipping','clipper'])await page.evaluate(t=>WorkspaceTabsManager.open(t),type);
  assert.equal(await page.getByRole('tab').count(),4);
  const clip=page.frameLocator('iframe[title="ZAR Clipper"]');await clip.locator('#zwtPreview').waitFor();assert(await clip.locator('[data-media-preview]').isVisible());
  await clip.getByRole('textbox',{name:'HISTORIA',exact:true}).fill('Historia sin generar');
  await page.evaluate(()=>WorkspaceTabsManager.open('sites'));const site=page.frameLocator('iframe[title="ZAR Sites"]');await site.locator('#zwtProjects').waitFor();await site.locator('[data-form=site] [name=name]').fill('Nombre sin guardar');await site.getByRole('button',{name:'Abrir / preview',exact:true}).click();assert.equal(await site.locator('#zwtPreview iframe').getAttribute('sandbox'),'allow-scripts');
  await page.evaluate(()=>WorkspaceTabsManager.open('dropshipping'));const drop=page.frameLocator('iframe[title="ZAR Dropshipping"]');await drop.locator('#zwtPreview').waitFor();await drop.locator('.zwtAdForm [name=name]').fill('Producto de prueba');assert.match(await drop.locator('.zwtAd').innerText(),/Producto de prueba/);
  await page.evaluate(()=>WorkspaceTabsManager.open('clipper'));assert.equal(await clip.locator('[name=story]').inputValue(),'Historia sin generar');
  await page.evaluate(()=>WorkspaceTabsManager.open('sites'));assert.equal(await site.locator('[data-form=site] [name=name]').inputValue(),'Nombre sin guardar');assert.equal(await page.getByRole('tab').count(),4);
  await page.getByRole('button',{name:'Cerrar ZAR Sites',exact:true}).click();assert.equal(await page.getByRole('tab').count(),3);await page.evaluate(()=>WorkspaceTabsManager.open('sites'));assert.equal(await page.getByRole('tab').count(),4);await page.evaluate(()=>WorkspaceTabsManager.open('sites'));assert.equal(await page.getByRole('tab').count(),4);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No global horizontal overflow');
  for(const title of ['ZAR Sites','ZAR Dropshipping','ZAR Clipper']){const frame=page.frames().find(f=>f.url().includes('zar_workspace='+({ 'ZAR Sites':'sites','ZAR Dropshipping':'dropshipping','ZAR Clipper':'clipper'}[title])));if(frame)assert(await frame.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),title+' child pane overflow');}
  assert.equal(posts.filter(p=>p==='/api/context/reset').length,1,'Opening subapps must preserve the server chat context');
  await page.getByRole('tab',{name:'🏠 Inicio / Chat',exact:true}).click();assert.equal(await page.locator('#input').inputValue(),'Borrador de chat conservado');
  await page.reload();await page.waitForFunction(()=>window.WorkspaceTabsManager);assert.equal(await page.getByRole('tab').count(),4);
  await page.getByRole('tab',{name:'🏠 Inicio / Chat',exact:true}).click();assert(await page.locator('#input').isVisible());assert.equal(posts.filter(p=>/generate|produce|publish|execute|send/.test(p)).length,0,'Navigation never submits generation or publication');
  if(width===1440){for(const [type,title,selector] of [['stonks','ZAR Stonks','#zarStonksApp'],['studio','ZAR Studio','#mediaWorkspace'],['files','Archivos','#fileSearch'],['orchestration','Orquestación','#zoViewport']]){await page.evaluate(t=>WorkspaceTabsManager.open(t),type);const f=page.frameLocator('iframe[title="'+title+'"]');await f.locator(selector).waitFor();assert(await f.locator(selector).isVisible());await page.getByRole('button',{name:'Cerrar '+title,exact:true}).click();}await page.getByRole('tab',{name:'🏠 Inicio / Chat',exact:true}).click();}
  assert.deepEqual(errors,[]);console.log('PASS tabs, retained forms, previews, close/reopen, session, chat '+width+'x'+height);await page.close();
 }
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
