const fs=require('fs'),assert=require('assert'),{chromium}=require('playwright');
(async()=>{
 const html=fs.readFileSync('app/templates/index.html','utf8');
 const css=[...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(m=>m[1]).join('\n')+['ui-polish.css','task-results.css','media-production.css','visual-polish.css','mobile-consolidation.css'].map(f=>fs.readFileSync('app/static/'+f,'utf8')).join('\n');
 const graph=html.match(/function orchestrationMarkup\(\)\{\s*return `([\s\S]*?)`;/)[1];
 const menu=['Investigación profunda','Multimedia / Vídeo','Buscar en Internet','Google Maps','Cómo funciona','Orquestación de Subagentes'];
 const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
 try{for(const [width,height] of [[390,844],[393,852],[412,915],[768,1024],[1440,1000]]){
  const page=await browser.newPage({viewport:{width,height}});
  await page.setContent('<style>'+css+'</style><section id="orchestrationWorkspace" class="orchestrationWorkspace" style="display:flex"><div id="orchestrationWorkspaceInner" class="orchestrationWorkspaceInner">'+graph+'</div></section><div id="mobileDrawer" hidden><div class="mobileMenuSection">'+menu.map(t=>'<button class="mobileMenuItem">'+t+'</button>').join('')+'</div></div>');
  await page.evaluate(()=>{window.fitCalls=0;window.zoFitAll=()=>fitCalls++;document.querySelector('#zoNodes').innerHTML='<button class="zoNode" style="left:50%;top:50%">Supervisor</button>';});
  await page.addScriptTag({path:'app/static/orchestration-clusters.js'});await page.addScriptTag({path:'app/static/workspace-polish.js'});
  await page.addScriptTag({path:'app/static/mobile-consolidation.js'});
  const measured=await page.locator('#zoViewport').evaluate(e=>{const r=e.getBoundingClientRect();return {top:r.top,height:r.height,bottom:r.bottom};});
  if(width<=720){assert(measured.height>=320,JSON.stringify(measured));assert(measured.top<260,JSON.stringify(measured));assert(measured.bottom<height,JSON.stringify(measured));assert.equal(await page.locator('[data-zo-mobile-controls]').getAttribute('open'),null);await page.getByRole('button',{name:'Ajustar mapa',exact:true}).click();assert.equal(await page.evaluate(()=>fitCalls),1);await page.locator('[data-zo-mobile-controls]>summary').click();assert(await page.locator('#zoSectionFilter').isVisible());assert.equal(await page.locator('[data-cluster]').count(),9);await page.setViewportSize({width:1440,height:1000});assert.equal(await page.locator('.zoSceneWrap>.zoToolbar').count(),1);await page.setViewportSize({width,height});}
  await page.locator('#orchestrationWorkspace').evaluate(e=>e.remove());await page.locator('#mobileDrawer').evaluate(e=>e.removeAttribute('hidden'));
  const overflow=await page.locator('.mobileMenuItem').evaluateAll(rows=>rows.some(e=>e.scrollWidth>e.clientWidth+1||e.scrollHeight>e.clientHeight+1));assert(!overflow,'Menu text overflow '+width);
  console.log('PASS mobile map/menu '+width+'x'+height+' '+JSON.stringify(measured));await page.close();
 }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
