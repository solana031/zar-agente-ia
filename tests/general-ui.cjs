const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
const viewports=[[360,800],[390,844],[412,915],[430,932],[768,1024],[1440,900],[1920,1080]];
const project={id:'mock-video',name:'Proyecto de prueba',preset:'youtube',media:[{name:'Imagen de prueba',type:'image',url:'/static/zar-silhouette.png',duration:3}],music:null};
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.ZAR_TEST_BROWSER?{executablePath:process.env.ZAR_TEST_BROWSER}:{})});
 try{for(const [width,height] of viewports){
 const page=await browser.newPage({viewport:{width,height},hasTouch:width<=1100});
 page.setDefaultTimeout(6000);
 const errors=[],requests=[];let apiError=false;
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{navigator.geolocation.getCurrentPosition=success=>success({coords:{latitude:40,longitude:-3}})});
 await page.route('**/*',route=>{
 const req=route.request(),path=new URL(req.url()).pathname;requests.push(path);
 if(path==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync('app/templates/index.html','utf8')});
 if(/^\/static\/[a-zA-Z0-9_.-]+$/.test(path)&&fs.existsSync('app'+path))return route.fulfill({contentType:path.endsWith('.js')?'application/javascript':path.endsWith('.css')?'text/css':'image/png',body:fs.readFileSync('app'+path)});
 if(apiError&&path.startsWith('/api/'))return route.fulfill({status:503,contentType:'application/json',body:'{"ok":false,"error":"Servicio temporalmente no disponible"}'});
 return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,project,skills:[],jobs:[],events:[],files:[],tasks:[{tasklist:{title:'Pruebas'},task:{title:'Revisar interfaz en móvil',notes:'Texto de ejemplo',status:'needsAction'}}],contacts:[{name:'Contacto de prueba',email:'test@example.invalid'}],messages:[],reports:[],services:[],recent:[],conversations:[],items:[],data:{current:{temperature_2m:20}},google:{connected:false},stats:{}})});
 });
 await page.goto('https://zar.test');await page.waitForTimeout(150);
 async function bounds(selector,vertical=true){
 const r=await page.locator(selector).first().evaluate(e=>({r:e.getBoundingClientRect().toJSON(),w:innerWidth,h:innerHeight}));
 assert.ok(r.r.width>0&&r.r.left>=-1&&r.r.right<=r.w+1,`${width} ${selector} horizontal ${JSON.stringify(r)}`);
 if(vertical)assert.ok(r.r.top>=-1&&r.r.bottom<=r.h+1,`${width} ${selector} vertical ${JSON.stringify(r)}`);
 }
 async function globalWidth(){assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`${width}: global overflow`)}
 async function home(){
 await globalWidth();await bounds('.top');await bounds('.composerMain');
 assert.equal(await page.locator('#editorBackBtn').isVisible(),false);
 // Holdings is part of the canonical default dock since v33.
 assert.deepEqual(await page.locator('.zarDockItem:visible').evaluateAll(items=>items.map(e=>e.dataset.dockId)),
   ['calendar','files','weather','studio','memory','tasks','control','research','learning','orchestration','holdings']);
 for(const b of await page.locator('.zarDockItem').all()){await b.scrollIntoViewIfNeeded();await bounds(`[data-dock-id="${await b.getAttribute('data-dock-id')}"]`,false)}
 for(const id of ['#attachBtn','#mic','#speakBtn','.composerMain button:last-child']){await bounds(id);assert.equal(await page.locator(id).isVisible(),true)}
 await page.locator('#input').fill('Borrador conservado');
 await page.locator('#speakBtn').click();await page.locator('#speakBtn').click();
 const picker=page.waitForEvent('filechooser');await page.locator('#attachBtn').click();await picker;
 await page.locator('#zarDockManageBtn').click();await bounds('.zarDockManagerCard');
 await page.locator('#zarDockManager [data-close]').first().click();
 if(width<=1100){
 await page.locator('.mobileMenu').click();await bounds('#mobileDrawer');
 assert.equal(await page.locator('.mobileMenu').getAttribute('aria-expanded'),'true');
 const menuItems=await page.locator('#mobileDrawer button').all();
 for(const b of menuItems){await b.scrollIntoViewIfNeeded();const hit=await b.evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))});assert.ok(hit,await b.textContent())}
 await page.locator('#mobileDrawer .mobileClose').click();
 await page.locator('.mobileMenu').click();await page.keyboard.press('Escape');assert.equal(await page.locator('#mobileDrawer').isVisible(),false);
 }else{
 for(const fn of ['toggleZarMenu','toggleRightRail']){await page.evaluate(fn=>window[fn](),fn);await globalWidth();await bounds('#zarHomeDock',false);await page.evaluate(fn=>window[fn](),fn)}
 }
 }
 for(const theme of ['dark','light']){
 await page.evaluate(t=>zarThemeApply(t),theme);await home();
 for(const fn of ['showMobileCalendar','showFiles','showMobileWeather','showMemory','showTasks','showControlCenter','showResearch','showContacts','showWorkspace','showMobileTime','showTools','showHelp']){
 await page.evaluate(fn=>window[fn](),fn);await page.waitForTimeout(30);await globalWidth();await bounds('#panel');
 await page.locator('#panel>button').click();assert.equal(await page.locator('#panel').isVisible(),false);
 assert.equal(await page.locator('.composer').evaluate(e=>getComputedStyle(e).visibility),'visible');
 }
 await page.evaluate(()=>openRecentEmails());await bounds('#zarEmailOverlay');await page.locator('#zarEmailOverlay .zarOverlayClose').click();
 await page.locator('#settingsBtn').click();await bounds('#zarSettingsOverlay');await page.locator('#zarSettingsOverlay .zarOverlayClose').click();
 await page.evaluate(()=>window.ZARSkills.open());await bounds('.zarSkillsShell');await page.locator('.zarSkillsClose').click();
 await page.evaluate(()=>enterControlCenter());await bounds('#controlWorkspace');await globalWidth();await page.evaluate(()=>exitControlCenter());
 await page.evaluate(()=>enterMediaEditor());await page.waitForTimeout(80);await bounds('#mediaWorkspace');
 assert.ok((await page.locator('#mediaWorkspace').boundingBox()).width>width*.5,'Studio should use available width');
 await page.evaluate(()=>showStudioTime());await page.locator('[data-close-context]').click();
 assert.equal(await page.locator('#studioContextPopup').isVisible(),false);
 await page.locator('.editorModeTab').filter({hasText:'IMAGEN'}).click();await globalWidth();
 await page.locator('.editorModeTab').filter({hasText:'AUDIO'}).click();await globalWidth();
 await page.evaluate(()=>renderAudioEditor({id:'mock-audio',name:'Prueba audio',instruments:['kick','bass'],tracks:[],bpm:120,duration:30}));await globalWidth();await bounds('.zarAudioPro',false);
 await page.locator('.editorModeTab').filter({hasText:'VÍDEO'}).click();await page.waitForTimeout(100);await globalWidth();
 assert.ok(await page.locator('.videoTrackRow').count()>0,'Video timeline rendered');
 await bounds('#mediaWorkspace');
 if(process.env.ZAR_TEST_SCREENSHOTS&&width===360&&theme==='dark')await page.screenshot({path:'data/general-studio.png'});
 await page.evaluate(()=>exitMediaEditor());
 if(process.env.ZAR_TEST_SCREENSHOTS&&theme==='light')await page.screenshot({path:`data/general-${width}-light.png`});
 }
 apiError=true;await page.evaluate(()=>showTasks());assert.match(await page.locator('#panel').textContent(),/no disponible|No se pudieron|Reintentar/i);await page.locator('#panel>button').click();apiError=false;
 if(width<=1100){
 await page.setViewportSize({width:800,height:430});await globalWidth();await bounds('.composerMain');
 await page.setViewportSize({width:360,height:400});await page.locator('#input').focus();await bounds('.composerMain');await bounds('#mic');await bounds('.composerMain button:last-child');
 await page.setViewportSize({width,height});
 // Simulate a visual viewport reduced by a keyboard without resizing layout viewport.
 await page.evaluate(()=>{Object.defineProperty(visualViewport,'height',{configurable:true,value:350});visualViewport.dispatchEvent(new Event('resize'))});
 const composerBottom=await page.locator('.composerMain').evaluate(e=>e.getBoundingClientRect().bottom);
 assert.ok(composerBottom<=350,`keyboard composer bottom ${composerBottom}`);
 await page.evaluate(()=>{delete visualViewport.height;visualViewport.dispatchEvent(new Event('resize'))});
 }
 assert.equal(await page.locator('#input').inputValue(),'Borrador conservado');
 assert.ok(!requests.some(p=>p.startsWith('/api/stonks/')),'General UI must not call trading routes');
 assert.deepEqual(errors,[],`${width}: JavaScript errors`);
 console.log(`PASS ${width}x${height}: Home, menu, composer, panels, functions, Studio, themes and overflow`);
 await page.close();
 }}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
