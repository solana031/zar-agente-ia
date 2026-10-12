const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
 try{for(const width of [390,1440]){
  const page=await browser.newPage({viewport:{width,height:844}}),errors=[],posts=[];
  page.on('pageerror',e=>errors.push(e.message));
  const project={id:'site-fixture',name:'TEST site',source_kind:'NATIVE_DEMO',files:['index.html']};
  let articles=[];
  await page.route('https://zar.invalid/**',async route=>{
   const req=route.request();if(req.method()==='GET')return route.fulfill({contentType:'text/html',body:'<style>'+fs.readFileSync('app/static/workspace-tabs.css','utf8')+'</style><div id="zwSites"></div>'});
   assert.equal(req.headers()['x-zar-business-csrf'],'offline');const data=req.postDataJSON();posts.push(data);
   assert.equal(data.id,project.id);
   const id=data.article_id||'aaaaaaaaaaaaaaaa';let article=articles.find(a=>a.id===id);
   if(!article){article={id,state:'DRAFT',preview_url:'/private-preview'};articles.push(article);}
   Object.assign(article,{title:data.title,body:data.body,keyword:data.keyword,is_test:data.is_test});
   return route.fulfill({json:{ok:true,result:{articles,saved_article_id:id}}});
  });
  await page.goto('https://zar.invalid/');
  await page.addScriptTag({content:fs.readFileSync('app/static/sites-editorial.js','utf8')});
  await page.evaluate(project=>window.dispatchEvent(new CustomEvent('zar-workflow-state',{detail:{csrf:'offline',sites:[project]}})),project);
  await page.locator('[name=title]').fill('TEST guía');await page.locator('[name=body]').fill('Contenido de prueba privado.');
  await page.getByRole('button',{name:'Guardar borrador'}).click();
  await page.waitForFunction(()=>document.querySelector('[name=article_id]').value==='aaaaaaaaaaaaaaaa');
  await page.locator('[name=body]').fill('Edición privada');await page.getByRole('button',{name:'Guardar borrador'}).click();
  await page.waitForFunction(()=>document.querySelector('[data-notice]').textContent.includes('guardado'));
  await page.waitForFunction(()=>document.querySelector('[name=article_id]').value.length>0);
  assert.equal(posts[1].article_id,'aaaaaaaaaaaaaaaa');assert.equal(articles.length,1);
  assert.equal(await page.getByRole('button',{name:'Publicar',exact:true}).isDisabled(),true);
  assert.equal(await page.getByRole('link',{name:/Preview privado/}).getAttribute('href'),'/private-preview');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.deepEqual(errors,[]);await page.close();
 }console.log('PASS: editorial private save/edit, no duplicate, TEST blocked, preview, 390/1440');}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
