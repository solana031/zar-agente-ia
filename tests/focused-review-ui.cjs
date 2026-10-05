// Focused recent UI regressions. All network traffic is intercepted.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {chromium}=require('playwright');
const html=fs.readFileSync('app/templates/index.html','utf8');
for(const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) new vm.Script(m[1]);
function agents(general=6,outer=9){
  return [
    {id:'zar_supervisor',domain:'core'}, {id:'stonks_supervisor',domain:'finance'},
    ...Array.from({length:general},(_,i)=>({id:'general_'+i,domain:'general'})),
    ...['data_plane','event_router','ai_gate','self_test'].map(x=>({id:'stonks_'+x,domain:'finance'})),
    ...Array.from({length:outer},(_,i)=>({id:'stonks_outer_'+i,domain:'finance'})),
  ].map(a=>({...a,name:a.id,role:'Especialista determinista de datos y supervisión',status:'ready'}));
}
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const state={ok:true,agents:agents(),edges:[],stonks_trace:[],mode:'paper',execution_mode:'shadow',
    max_trade_eur:25,max_daily_loss_eur:10,max_position_pct:20,stop_loss_pct:1,take_profit_pct:2,
    position_lifecycle_enabled:false,managed_positions:{},audit:[],signals:[],positions:[],orders:[]};
  await page.route('**/*',route=>{
    const u=new URL(route.request().url());
    if(u.pathname==='/') return route.fulfill({contentType:'text/html',body:html});
    if(u.pathname.startsWith('/static/') && fs.existsSync('app'+u.pathname)) {
      const ext=u.pathname.split('.').pop();
      return route.fulfill({contentType:ext==='js'?'application/javascript':ext==='css'?'text/css':'image/png',body:fs.readFileSync('app'+u.pathname)});
    }
    return route.fulfill({contentType:'application/json',body:JSON.stringify(state)});
  });
  await page.goto('https://zar.test/');
  for(let visit=0;visit<2;visit++){
    await page.evaluate(()=>showSubagentOrchestration());
    await page.waitForSelector('.zoNode');
    const result=await page.evaluate(()=>{
      const vp=document.getElementById('zoViewport');
      vp.scrollLeft=300;vp.scrollTop=200;
      vp.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,clientX:300,clientY:200,pointerId:1}));
      vp.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:200,clientY:150,pointerId:1}));
      vp.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:1}));
      const pan=vp.scrollLeft;
      const old=document.getElementById('zoZoomBadge').textContent;
      vp.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,deltaY:-100,clientX:400,clientY:300}));
      const zoom=document.getElementById('zoZoomBadge').textContent;
      zoSetZoom(.7);
      const semantic=document.getElementById('zoScene').classList.contains('zoom-low');
      zoSetZoom(1);
      const wrap=document.querySelector('.zoSceneWrap'),handle=wrap.querySelector('.hint');
      const left=parseFloat(wrap.style.left)||0;
      handle.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,clientX:300,clientY:200,pointerId:2}));
      handle.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:270,clientY:240,pointerId:2}));
      handle.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:2}));
      return {pan,zoom,old,semantic,moved:(parseFloat(wrap.style.left)||0)!==left};
    });
    assert.equal(result.pan,400,`pan on visit ${visit}`);
    assert.notEqual(result.zoom,result.old);
    assert(result.semantic && result.moved,JSON.stringify(result));
    // Native resize is driven by inline dimensions; verify CSS lets them win.
    await page.evaluate(()=>{
      const w=document.querySelector('.zoSceneWrap'); w.style.width='900px';w.style.height='600px';
    });
    await page.waitForTimeout(100);
    assert.equal(await page.locator('.zoSceneWrap').evaluate(el=>el.getBoundingClientRect().height),600);
    await page.evaluate(()=>exitSubagentOrchestration());
    assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('zarOrchestrationMapWindowV1')).height),600);
  }
  await page.evaluate(()=>showSubagentOrchestration());
  assert.equal(await page.locator('.zoSceneWrap').evaluate(el=>el.getBoundingClientRect().height),600);
  for(const [g,f] of [[6,9],[14,16],[30,30]]){
    await page.evaluate(a=>zoRender({ok:true,agents:a,edges:[]}),agents(g,f));
    const overlaps=await page.evaluate(()=>{
      const nodes=[...document.querySelectorAll('.zoNode')].map(e=>({id:e.dataset.agent,r:e.getBoundingClientRect()}));
      const overlaps=[];
      for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
        const a=nodes[i],b=nodes[j];
        if(Math.min(a.r.right,b.r.right)-Math.max(a.r.left,b.r.left)>1 && Math.min(a.r.bottom,b.r.bottom)-Math.max(a.r.top,b.r.top)>1)overlaps.push([a.id,b.id]);
      }
      return overlaps;
    });
    assert.deepEqual(overlaps,[],`node overlaps ${g}/${f}`);
  }
  await page.evaluate(()=>{exitSubagentOrchestration();showStonks();});
  await page.waitForSelector('#stonksMaxTrade',{state:'attached'});
  await page.evaluate(async()=>{
    await zsRefreshStatus();
    const input=document.getElementById('stonksMaxTrade');input.value='17';
    input.dispatchEvent(new Event('input',{bubbles:true}));input.blur();
    await zsRefreshStatus();await zsRefreshStatus();
  });
  assert.equal(await page.locator('#stonksMaxTrade').inputValue(),'17');
  assert.match(await page.locator('#zsRiskDraftStatus').textContent(),/sin guardar/);
  // An edit made while Save is in flight must remain dirty after its response.
  await page.evaluate(()=>{
    const original=window.fetch;
    window.fetch=(url,options)=>url==='/api/stonks/controls'
      ? new Promise(resolve=>window.__finishRiskSave=()=>resolve({json:async()=>({ok:true,execution_mode:'shadow'})}))
      : original(url,options);
    window.__pendingRiskSave=saveStonksControls();
    const input=document.getElementById('stonksMaxTrade');input.value='19';
    input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  await page.evaluate(async()=>{__finishRiskSave();await __pendingRiskSave;await zsRefreshStatus();});
  assert.equal(await page.locator('#stonksMaxTrade').inputValue(),'19');
  assert.match(await page.locator('#zsRiskDraftStatus').textContent(),/sin guardar/);
  await page.evaluate(()=>zsRenderDataPlane({market_stream:{latest:[{symbol:'AAPL',stale:true,timestamp:'2026-01-01T10:00:00Z',price:100}]}}));
  assert.match(await page.locator('#zsDataPlane').textContent(),/OBSOLETO/);
  assert.deepEqual(errors,[]);
  console.log('PASS: JS syntax, reopen/pan/move, wheel/semantic zoom, resize, layout growth, Risk draft sync and stale stream UI');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
