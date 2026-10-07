const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const html=fs.readFileSync('app/templates/index.html','utf8');
const script=html.match(/<script id="zar-orchestration-global-js-v31-3-49">([\s\S]*?)<\/script>/)[1];
const css=[...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(x=>x[1]).join('\n');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
 try{for(const width of [1440,390]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  let saved={},posts=0;
  let agents=[{id:'zar_supervisor',name:'ZAR',domain:'core'},{id:'stonks_supervisor',name:'AUTOMATON',domain:'finance'},{id:'CommerceOrchestrator',name:'COMMERCE',domain:'commerce',type:'orchestrator'},...Array.from({length:3000},(_,i)=>({id:'dynamic-'+i,name:'Future '+i,domain:'commerce',parent:'CommerceOrchestrator',status:'IDLE'}))];
  await page.route('**/*',route=>{
   const req=route.request(),path=new URL(req.url()).pathname;
   if(path==='/')return route.fulfill({contentType:'text/html',body:`<style>${css}</style><div class="app"><main class="main"><h1 id="topTitle"></h1><section id="orchestrationWorkspace" class="orchestrationWorkspace" hidden><div id="orchestrationWorkspaceInner"></div></section></main></div>`});
   if(path==='/api/subagents/view'){
    if(req.method()==='POST'){assert.equal(req.headers()['x-zar-business-csrf'],'offline');saved=req.postDataJSON();posts++;}
    return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,csrf:'offline',view:saved})});
   }
   return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,agents,edges:agents.slice(3).map(a=>['CommerceOrchestrator',a.id]),stonks_trace:[]})});
  });
  await page.goto('https://zar.invalid/');await page.evaluate(()=>{window.closePanel=()=>{};window.state=()=>{};});await page.addScriptTag({content:script});
  await page.evaluate(()=>showSubagentOrchestration());await page.waitForFunction(()=>window.__zoState?.agents.length===3003);
  await page.evaluate(()=>zoSetZoom(0));await page.waitForFunction(()=>document.getElementById('zoZoomBadge').textContent==='0%');
  assert.ok(await page.locator('#zoScene').evaluate(e=>e.style.transform==='scale(0.001)'));
  assert.ok(await page.locator('#zoSummaryOverlay').isVisible());assert.ok((await page.locator('.zoNode').count())<200);
  await page.evaluate(()=>zoSetZoom(100));await page.waitForFunction(()=>document.getElementById('zoZoomBadge').textContent==='10000%');
  await page.evaluate(()=>zoSetZoom(1000));assert.equal(await page.locator('#zoZoomBadge').innerText(),'100000%');
  await page.evaluate(()=>zoFitAll());assert.ok((await page.locator('.zoNode').count())<200);
  agents=agents.slice(0,20);await page.evaluate(()=>zoRefresh());await page.evaluate(()=>zoSetZoom(2));
  await page.locator('#zoViewport').evaluate(e=>{
    e.scrollLeft=400;e.scrollTop=300;const r=e.getBoundingClientRect(),x=120,y=100;
    const world=(e.scrollLeft+x)/zoViewState().zoom;
    e.dispatchEvent(new WheelEvent('wheel',{clientX:r.left+x,clientY:r.top+y,deltaY:-80,bubbles:true,cancelable:true}));
    if(Math.abs((e.scrollLeft+x)/zoViewState().zoom-world)>1)throw Error('Cursor anchor moved');
    const before=zoViewState().zoom;
    for(const [id,px] of [[10,100],[11,200]])e.dispatchEvent(new PointerEvent('pointerdown',{pointerId:id,pointerType:'touch',button:0,clientX:r.left+px,clientY:r.top+150,bubbles:true}));
    e.dispatchEvent(new PointerEvent('pointermove',{pointerId:11,pointerType:'touch',clientX:r.left+240,clientY:r.top+150,bubbles:true}));
    if(zoViewState().zoom<=before)throw Error('Pinch did not zoom');
    for(const id of [10,11])e.dispatchEvent(new PointerEvent('pointerup',{pointerId:id,pointerType:'touch',bubbles:true}));
  });
  await page.evaluate(()=>zoSetZoom(2));
  await page.locator('#zoViewport').evaluate(e=>{e.scrollLeft=300;e.scrollTop=200;e.dispatchEvent(new Event('scroll'));});await page.waitForTimeout(550);
  assert.ok(posts>0);assert.equal(saved.zoom,2);assert.ok(saved.pan_x>0);
  const pan=saved.pan_x;await page.evaluate(()=>{exitSubagentOrchestration();showSubagentOrchestration();});
  await page.waitForFunction(()=>document.getElementById('zoZoomBadge').textContent==='200%');await page.waitForTimeout(150);
  assert.ok(Math.abs(await page.locator('#zoViewport').evaluate(e=>e.scrollLeft)-pan)<2);
  assert.ok((await page.locator('.zoNode[data-agent="dynamic-5"]').count())===1);
  await page.locator('.zoNode[data-agent="dynamic-5"]').click();assert.ok((await page.locator('#zoNodeDetail').textContent()).includes('Future 5'));
  await page.evaluate(()=>zoFilter('finance'));await page.waitForFunction(()=>!document.querySelector('.zoNode[data-agent="dynamic-5"]'));assert.equal(await page.locator('.zoNode[data-agent="dynamic-5"]').count(),0);
  assert.deepEqual(errors,[]);await page.close();
  console.log(`PASS ${width}px: 3000 dynamic agents, culling/summary, 0% scale positive, 10000% zoom, fit, scoped view restore and detail`);
 }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
