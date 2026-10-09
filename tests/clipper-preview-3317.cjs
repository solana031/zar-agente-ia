const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}});let posts=0;
  const job={id:'smoke',status:'PRODUCED',result:{stage:'done',preview_url:'/api/holdings/media/video/smoke',format:'9:16'}};
  await page.route('**/*',r=>{
   if(r.request().method()==='POST')posts++;
   if(new URL(r.request().url()).pathname.includes('/video/'))return r.fulfill({status:404});
   return r.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,tasks:[job],connector:{api_ready:true,capabilities:{}}})});
  });
  await page.goto('https://zar.test/');
  await page.setContent('<div id="zarMediaWorkflowMount"></div>');
  await page.addScriptTag({path:'app/static/media-production.js'});
  await page.waitForFunction(()=>document.querySelector('[data-media-stage]')?.textContent.includes('Renderizado'));
  assert.equal(await page.locator('video[controls]').count(),1);
  assert.equal(await page.getByRole('link',{name:'Abrir MP4'}).getAttribute('href'),'/api/holdings/media/video/smoke');
  assert.equal(await page.getByRole('link',{name:'Descargar MP4'}).getAttribute('download'),'');
  await page.waitForFunction(()=>document.querySelector('[data-media-error]')?.textContent.includes('PREVIEW_PLAYER_ERROR'));
  assert.equal(posts,0,'Mounting a produced clip must never publish automatically');
  job.result.preview_url='https://untrusted.invalid/video.mp4';
  await page.getByRole('button',{name:'VER PROGRESO',exact:true}).click();
  await page.getByRole('link',{name:'Abrir MP4'}).waitFor({state:'detached'});
  assert.equal(await page.getByRole('link',{name:'Abrir MP4'}).count(),0,'External preview URLs are not accepted');
  console.log('Clipper stable player, authenticated MP4 links, load error and no automatic publication: PASS');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
