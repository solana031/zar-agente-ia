// One reusable responsive audit. No service is contacted; screenshots only on failure.
const fs=require('fs'),path=require('path'),os=require('os'),assert=require('assert/strict');
const {chromium}=require('playwright');
const html=fs.readFileSync('app/templates/index.html','utf8');
const matrix=[[1920,1080],[1600,900],[1440,900],[1366,768],[1180,820],[1024,768],[820,1180],[768,1024],[430,932],[412,915],[393,852],[375,812],[360,800]];
const sizes=process.env.ZAR_AUDIT_SMOKE?[[1440,900],[360,800]]:matrix;
const surfaces=['showConversations','showMemory','showFiles','showTasks','showContacts','showGmail','showWorkspace','showConnections','showMaps','showResearch','openLearning','showProvider','showVoice','showMobileCalendar','showMobileTime','showMobileWeather','showControlCenter','showMedia','showStonks','showSubagentOrchestration'];
const fixtures={ok:true,version:'32.0.0',mode:'paper',execution_mode:'shadow',paused:true,revoked:false,
 google:{account:'test@example.invalid',connected:false},services:[],models:[],files:[],folders:[],items:[],events:[],tasks:[],lists:[],contacts:[],messages:[],conversations:[],memories:[],learnings:[],recent:[],stats:{},insights:{by_type:[]},backups:[],projects:[],positions:[],orders:[],audit:[],signals:[],managed_positions:{},agents:[],edges:[],stonks_trace:[],queue:[],data:[],health:{},settings:{},status:'ready',
 max_trade_eur:25,max_daily_loss_eur:10,max_position_pct:20,stop_loss_pct:1,take_profit_pct:2};
function agents(n){return [{id:'zar_supervisor',name:'ZAR Supervisor',domain:'core'}, {id:'stonks_supervisor',name:'Stonks Supervisor',domain:'finance'},...Array.from({length:n-2},(_,i)=>({id:(i%2?'stonks_':'general_')+i,name:'Agente de datos '+i,role:'Especialista determinista en datos públicos',domain:i%2?'finance':'general'}))];}
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
 const failures=[],coverage=[];let shots=0;
 const diagnostics=fs.mkdtempSync(path.join(os.tmpdir(),'zar-ui-audit-'));
 try{
 for(const [width,height] of sizes){
  const context=await browser.newContext({viewport:{width,height},deviceScaleFactor:width<900?2:1,hasTouch:width<900,isMobile:width<600,serviceWorkers:'block'});
  const page=await context.newPage();let errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
    // Deterministic unavailable geolocation exercises its error state without permission prompts.
    navigator.geolocation.getCurrentPosition=(_ok,fail)=>fail?.({message:'Simulated unavailable location'});
    HTMLMediaElement.prototype.play=async function(){};
    // Emulate the standalone display surface; this is not a native Android device test.
    if(innerWidth===393){const original=matchMedia.bind(window);window.matchMedia=q=>{const m=original(q);if(q==='(display-mode: standalone)')Object.defineProperty(m,'matches',{value:true});return m;};Object.defineProperty(navigator,'standalone',{value:true});}
  });
  await page.route('**/*',r=>{
    const u=new URL(r.request().url());
    if(u.pathname==='/')return r.fulfill({contentType:'text/html',body:html});
    if(u.pathname.startsWith('/static/') && !u.pathname.includes('..') && fs.existsSync('app'+u.pathname)){
      const ext=path.extname(u.pathname);return r.fulfill({body:fs.readFileSync('app'+u.pathname),contentType:ext==='.js'?'application/javascript':ext==='.css'?'text/css':'image/png'});
    }
    return r.fulfill({contentType:'application/json',body:JSON.stringify(u.pathname.includes('/subagents/state')?{...fixtures,agents:agents(20)}:fixtures)});
  });
  async function check(label){
   await page.waitForTimeout(40);
   const issues=await page.evaluate(()=>{
    const issues=[],visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
    if(document.documentElement.scrollWidth>innerWidth+1)issues.push('document horizontal overflow '+document.documentElement.scrollWidth);
    const roots=['#zarSkillsPanel.open .zarSkillsCard','#panel','.orchestrationWorkspace:not([hidden])','#mediaWorkspace:not([hidden])','#mobileDrawer:not([hidden])','#zsConfirmModal','.zarOverlayCard'];
    for(const selector of roots){for(const el of document.querySelectorAll(selector)){
     if(!visible(el))continue;const r=el.getBoundingClientRect();
     if(r.left< -2||r.right>innerWidth+2)issues.push(selector+' outside width '+Math.round(r.left)+'/'+Math.round(r.right));
     if(r.top< -2||r.top>innerHeight-30)issues.push(selector+' inaccessible top '+Math.round(r.top));
     if(el.scrollWidth>el.clientWidth+2 && !['auto','scroll'].includes(getComputedStyle(el).overflowX))issues.push(selector+' inner overflow '+el.scrollWidth+'/'+el.clientWidth);
    }}
    for(const el of document.querySelectorAll('#panel button,#panel input:not([type="hidden"]),#panel select,#panel textarea')){
      if(!el.checkVisibility({checkVisibilityCSS:true,checkOpacity:true}))continue;
      const r=el.getBoundingClientRect();
      if(matchMedia('(pointer: coarse)').matches&&el.tagName==='BUTTON'&&(r.width<(el.matches('.zsPill')?44:24)||r.height<(el.matches('.zsPill')?44:24)))issues.push('small touch control '+(el.id||el.textContent.slice(0,25))+' '+Math.round(r.width)+'x'+Math.round(r.height));
      if(r.width===0||r.height===0)issues.push('zero-size control '+(el.id||el.textContent.slice(0,25)));
      let scroller=el.parentElement,scrollable=false;
      while(scroller&&scroller!==document.body){if(['auto','scroll'].includes(getComputedStyle(scroller).overflowX)&&scroller.scrollWidth>scroller.clientWidth){scrollable=true;break}scroller=scroller.parentElement}
      if(!scrollable&&(r.left< -2||r.right>innerWidth+2))issues.push('control outside width '+(el.id||el.textContent.slice(0,25)));
    }
    const ids=[...document.querySelectorAll('[id]')].filter(visible).map(e=>e.id);
    const duplicates=[...new Set(ids.filter((id,i)=>ids.indexOf(id)!==i))];
    if(duplicates.length)issues.push('duplicate IDs '+duplicates.join(','));
    const input=document.querySelector('#chatContent .composer');
    if(!document.body.classList.contains('zar-panel-open') && !document.querySelector('.app.editor-mode,.app.orchestration-mode,.app.control-mode') && input && visible(input)){
      const r=input.getBoundingClientRect();if(r.bottom>innerHeight+2)issues.push('composer below viewport');
    }
    return issues;
   });
   if(errors.length)issues.push(...errors.splice(0).map(x=>'JS '+x));
   coverage.push([width,height,label]);
   if(issues.length){failures.push({viewport:[width,height],surface:label,issues});if(shots++<6)await page.screenshot({path:path.join(diagnostics,`${width}-${label.replace(/\W/g,'_')}.png`)});}
  }
  await page.goto('https://zar.test/');await page.waitForTimeout(150);await check('desktop');
  for(const surface of surfaces.filter(s=>!process.env.ZAR_AUDIT_SURFACE||process.env.ZAR_AUDIT_SURFACE.split(',').includes(s))){
   await page.evaluate(()=>{document.querySelector('.zarSkillsClose')?.click();closePanel();if(typeof exitMediaEditor==='function')exitMediaEditor();if(typeof exitSubagentOrchestration==='function')exitSubagentOrchestration();});
   assert.equal(await page.locator('#panel').isVisible(),false,'Generic close must hide Stonks before switching surfaces');
   const exists=await page.evaluate(name=>name==='openLearning'?typeof window.ZARSkills?.open==='function':typeof window[name]==='function',surface);
   if(!exists){failures.push({surface,issues:['missing entry point']});continue;}
   try{await page.evaluate(name=>name==='openLearning'?window.ZARSkills.open():window[name](),surface);}catch(e){errors.push(e.message);}
   await check(surface);
   if(surface==='showStonks'){
     for(const tab of await page.locator('[data-zstab]').evaluateAll(els=>els.map(e=>e.dataset.zstab))){
       await page.evaluate(tab=>zsTab(tab,document.querySelector(`[data-zstab="${tab}"]`)),tab);await check('stonks-'+tab);
     }
     await page.evaluate(()=>{zsOpenConfirm('Prueba de confirmación','Confirmación','Texto de diagnóstico','Aceptar','Cancelar');});
     await page.locator('#zsConfirmModal').waitFor({state:'visible'});await check('stonks-confirm');await page.evaluate(()=>zsResolveConfirm(false));await page.evaluate(()=>zsRenderReadiness({readiness:{checks:[{name:'Paper sample size',status:'pendiente',detail:'0/20'}]}}));assert.match(await page.locator('#zsReadiness').textContent(),/LIVE BLOQUEADO/);assert.equal(await page.locator('#zsReadiness button').count(),0);
     await page.evaluate(()=>closeStonksWindow());await page.evaluate(()=>showStonks());await check('stonks-reopen');
   }
   if(surface==='showMedia'){
     await page.evaluate(()=>renderAudioEditor({id:'mock',name:'Proyecto de audio',bpm:100,duration:30,key:'C',tracks:[],instruments:[]}));await check('studio-audio');
     await page.evaluate(()=>renderImageEditor({name:'Imagen',url:''}));await check('studio-image');
     await page.evaluate(()=>renderVideoCreator({id:'mock',name:'Vídeo',clips:[],audio_tracks:[],timeline:[]}));await check('studio-video');
   }
   if(surface==='showSubagentOrchestration'){
     for(const n of [10,20,40,60]){
       await page.evaluate(a=>zoRender({agents:a,edges:a.slice(2).map(x=>[x.domain==='finance'?'stonks_supervisor':'zar_supervisor',x.id])}),agents(n));
       const overlap=await page.evaluate(()=>{
         const nodes=[...document.querySelectorAll('.zoNode')].map(e=>({id:e.dataset.agent,r:e.getBoundingClientRect()}));
         return nodes.some((a,i)=>nodes.slice(i+1).some(b=>Math.min(a.r.right,b.r.right)-Math.max(a.r.left,b.r.left)>1&&Math.min(a.r.bottom,b.r.bottom)-Math.max(a.r.top,b.r.top)>1));
       });if(overlap)failures.push({viewport:[width,height],surface:'orchestration-'+n,issues:['node overlap']});
     }
     await page.evaluate(()=>{exitSubagentOrchestration();showSubagentOrchestration();});await check('orchestration-reopen');
   }
  }
  await page.evaluate(()=>{exitSubagentOrchestration();exitMediaEditor();closePanel();newChat();});await check('return-desktop');
  // Short visible viewport approximates keyboard/landscape; native IME behavior is not emulated.
  if(width<600){await page.locator('#input').focus();await page.setViewportSize({width,height:Math.max(360,height-300)});await check('mobile-keyboard-viewport');await page.setViewportSize({width:height,height:width});await check('mobile-landscape');}
  await context.close();
 }
 console.log(JSON.stringify({checks:coverage.length,viewports:sizes,failures,diagnostics:failures.length?diagnostics:undefined},null,2));
 assert.equal(failures.length,0,'Responsive audit failures');
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
