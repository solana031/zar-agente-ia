// Explicit production QA: existing media, isolated browser session, no generation/payments.
const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
(async()=>{
 const base='https://web-production-a9565.up.railway.app',out=path.resolve('artifacts/3335');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:!process.argv.includes('--headed'),executablePath:process.env.ZAR_TEST_BROWSER});
 try{
 const context=await browser.newContext({viewport:{width:390,height:844},acceptDownloads:true});
 await context.request.get(base+'/');
 if(process.env.ZAR_ACCESS_PASSWORD){const response=await context.request.post(base+'/login',{form:{password:process.env.ZAR_ACCESS_PASSWORD}});assert(response.ok(),'Existing ZAR login failed');}
 const assets=process.argv.includes('--surfaces-only')?[]:[['image','artifacts/3334/RESEARCH.png'],['video',process.env.ZAR_QA_MP4],['audio','artifacts/3327/trap-Aminor-140.wav'],['pdf','artifacts/3334/PROPOSAL.pdf']];
 const saved=[];
 for(const [kind,file] of assets){assert(file&&fs.existsSync(file),'Existing fixture missing: '+kind);const bytes=fs.readFileSync(file),name='QA3335-'+path.basename(file);const r=await context.request.post(base+'/api/files/upload',{multipart:{files:{name,mimeType:({image:'image/png',video:'video/mp4',audio:'audio/wav',pdf:'application/pdf'})[kind],buffer:bytes},note:'TEST INTERNAL: existing asset; production QA isolated session; no generation.'}});assert(r.ok(),'Upload '+kind+' HTTP '+r.status());const j=await r.json();assert(j.ok);const item=(j.files||[])[0]||(j.duplicates||[])[0];assert(item);saved.push({kind,id:item.id,name,hash:crypto.createHash('sha256').update(bytes).digest('hex')});}
 const page=await context.newPage(),errors=[],serverErrors=[];page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=500)serverErrors.push({status:r.status(),path:new URL(r.url()).pathname});});
 await page.goto(base+'/?zar_workspace=files');await page.locator('#zarFileList').waitFor();
 for(const asset of saved){
  await page.evaluate(a=>previewFile(a.id,a.name),asset);const modal=page.locator('#filePreviewModal');await modal.waitFor({state:'visible'});
  assert(await modal.evaluate(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1;}),'Viewer fits mobile '+asset.kind);
  const close=page.getByRole('button',{name:'✕ Cerrar',exact:true});assert(await close.isVisible(),'Visible close');
  if(asset.kind==='image'){await page.locator('#filePreviewBody img').evaluate(e=>e.decode());assert(await page.locator('#filePreviewBody img').evaluate(e=>e.naturalWidth>0&&e.getBoundingClientRect().width<=innerWidth),'Decoded image and fit');}
  if(['audio','video'].includes(asset.kind)){
   const player=page.locator('#filePreviewBody '+asset.kind);await player.evaluate(e=>new Promise((resolve,reject)=>{if(e.readyState>=2)return resolve();e.addEventListener('loadeddata',resolve,{once:true});e.addEventListener('error',()=>reject(Error('Media decode failed')),{once:true});}));
   assert(await player.evaluate(e=>Number.isFinite(e.duration)&&e.duration>0),'Valid duration');await player.evaluate(e=>e.play());await page.waitForTimeout(300);assert(await player.evaluate(e=>!e.paused&&e.currentTime>0),'Real playback');await player.evaluate(e=>e.pause());assert(await player.evaluate(e=>e.paused));
   await player.evaluate(e=>{e.currentTime=e.duration/2;e.volume=.4;});assert(await player.evaluate(e=>e.currentTime>0&&Math.abs(e.volume-.4)<.01),'Seek and volume');
   if(asset.kind==='video'){await player.evaluate(e=>e.requestFullscreen());assert(await page.evaluate(()=>!!document.fullscreenElement),'Fullscreen');await page.evaluate(()=>document.exitFullscreen());}
  }
  if(asset.kind==='pdf'){await page.locator('#filePreviewBody iframe').waitFor({state:'visible'});await page.waitForTimeout(1500);}
  const download=await context.request.get(base+'/api/files/'+asset.id+'/download');assert(download.ok());assert.equal(crypto.createHash('sha256').update(await download.body()).digest('hex'),asset.hash,'Exact downloaded bytes');
  await page.screenshot({path:path.join(out,'files-'+asset.kind+'-390.png')});await close.click();assert(!await modal.isVisible(),'Close');await page.reload();assert((await (await context.request.get(base+'/api/files')).json()).files.some(x=>x.id===asset.id),'Persistence after reload');console.log('PASS production Files '+asset.kind+' upload/decode/controls/download/close/reload');
 }
 if(process.argv.includes('--media-only'))return;
 const views=['','conversations','memory','learning','files','calendar','contacts','maps','gmail','google','wallet','browser','workspace','sites','dropshipping','clipper','agency','studio','stonks','holdings','orchestration','human'];
 const findings=[],matrix=[];
 for(const [width,height] of [[390,844],[393,852],[412,915],[768,1024],[1440,900],[1920,1080]]){
  await page.setViewportSize({width,height});
  for(const view of views){await page.goto(base+'/?zar_workspace='+view);await page.waitForTimeout(300);assert.equal(await page.evaluate(()=>innerWidth),width,'REAL viewport');const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);if(overflow)findings.push({view,width,issue:'horizontal overflow'});const state=await page.evaluate(()=>({header:[...document.querySelectorAll('h1,h2,h3')].filter(e=>e.getBoundingClientRect().height>0).map(e=>e.textContent.trim()).slice(0,5),buttons:[...document.querySelectorAll('button')].filter(e=>e.getBoundingClientRect().height>0).length,workspace:document.body.dataset.workspaceType||'home'}));matrix.push({view,width,...state});if(view)assert.equal(state.workspace,view,'Workspace route');if(view==='calendar'){await page.locator('.zarCalendarViewMode').waitFor({state:width<=720?'visible':'attached'});if(width<=720){assert(!await page.locator('.zarCalendarCard').isVisible(),'Agenda first');await page.getByRole('button',{name:'Mes / Agenda'}).click();assert(await page.locator('.zarCalendarCard').isVisible(),'Month toggle');}}if(view==='wallet')await page.getByRole('heading',{name:'Costes e ingresos verificados'}).waitFor();if(width===390&&['calendar','wallet','orchestration'].includes(view))await page.screenshot({path:path.join(out,view+'-390.png')});}
  console.log('PASS real production viewport '+width+'x'+height+' surfaces opened');
 }
 fs.writeFileSync(path.join(out,assets.length?'qa-results.json':'surface-results.json'),JSON.stringify({isolatedSession:true,files:saved.map(({hash,...x})=>x),matrix,findings,errors,serverErrors},null,2));assert.equal(serverErrors.length,0,'Unexpected production 5xx');assert.equal(errors.length,0,'Critical JS');assert.equal(findings.length,0,'Responsive findings');
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
