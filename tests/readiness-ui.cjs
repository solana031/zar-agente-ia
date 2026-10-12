const fs=require('node:fs'),assert=require('node:assert/strict'),{chromium}=require('playwright');
const sizes=[[1366,768],[1440,900],[1920,1080],[768,1024],[390,844],[393,852],[412,915]];
const out='.local/readiness-ui';fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});try{
for(const [width,height] of sizes){
const page=await browser.newPage({viewport:{width,height}}),errors=[],posts=[];let configFails=true;
page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
const fixture={ok:true,csrf:'TEST-csrf',version:fs.readFileSync('VERSION','utf8').trim(),jev:[],sites:[],media:[],commerce:{niches:[],suppliers:[],listings:[],orders:[],products:[]},skills:[],tasks:[],agents:[],events:[],companies:{},identity_center:{google:{email:'TEST@example.invalid',status:'ACTION_REQUIRED'},onboarding:[],capabilities:{},plans:[],human_actions:[],human_action_groups:[],mail_audit:[],integrations:[]},connectors:{},view:{},files:[],contacts:[],messages:[],conversations:[],items:[],jobs:[],reports:[],services:[],stats:{},wallet:{balances:{},note:'TEST · Sin movimientos contables.'},budgets:{},ledger:[],approvals:[],financial_provider:{status:'ACTION_REQUIRED'},financial_events:{periods:{},events:[]},project:{id:'TEST-video',name:'TEST vídeo',preset:'youtube',media:[],tracks:[],instruments:[]},workspace:{revision:1,profile:{},sources:[],history:[],knowledge:{facts:[],changes:{}}}};
await page.route('**/*',r=>{const p=new URL(r.request().url()).pathname;if(p==='/')return r.fulfill({contentType:'text/html',body:fs.readFileSync('app/templates/index.html')});if(p.startsWith('/static/')&&fs.existsSync('app'+p))return r.fulfill({contentType:p.endsWith('.css')?'text/css':p.endsWith('.js')?'application/javascript':'image/png',body:fs.readFileSync('app'+p)});if(r.request().method()==='POST'){posts.push({path:p,body:r.request().postDataJSON(),headers:r.request().headers()});if(p==='/api/config'&&configFails)return r.fulfill({status:503,json:{ok:false,error:'TEST proveedor no disponible'}});}return r.fulfill({json:fixture});});
await page.goto('https://zar.test/');await page.waitForFunction(()=>window.WorkspaceTabsManager);
await page.screenshot({path:`${out}/${width}-home.png`});
// Settings failure must stay visible and retry must recover.
await page.evaluate(()=>openZarSettings());await page.getByRole('button',{name:'Guardar ajustes',exact:true}).click();await page.waitForFunction(()=>document.getElementById('zarSettingsStatus').textContent.includes('sin guardar'));
configFails=false;await page.getByRole('button',{name:'Guardar ajustes',exact:true}).click();await page.waitForFunction(()=>document.getElementById('zarSettingsStatus').textContent.includes('✓'));await page.locator('#zarSettingsOverlay .zarOverlayClose').click();
const modules=await page.evaluate(()=>navigationRegistry.filter(x=>x.id!=='home').map(x=>({id:x.id,title:x.title})));
for(const {id,title} of modules){
 await page.evaluate(id=>WorkspaceTabsManager.open(id),id);const pane=await (await page.locator('iframe.zwtPane').elementHandle()).contentFrame();await pane.waitForURL('**/?zar_workspace='+id);await pane.waitForLoadState('domcontentloaded');await page.waitForTimeout(200);
 assert(await pane.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${width} ${id}: horizontal overflow`);
 if(id==='calendar'){
  await pane.locator('#zarEventTitle').fill('TEST evento sin enviar');await pane.locator('#zarEventDate').fill('2026-11-10');
  await pane.evaluate(()=>{void zarCreateCalendarEvent()});await pane.locator('[data-zar-cancel]').click();assert.equal(posts.filter(x=>x.path==='/api/calendar/create').length,0);
  await pane.evaluate(()=>{void zarCreateCalendarEvent()});await pane.locator('[data-zar-ok]').click();await pane.waitForFunction(()=>document.getElementById('zarEventCreateStatus').textContent.includes('✓'));
  const call=posts.find(x=>x.path==='/api/calendar/create');assert.equal(call.body.confirmed,true);assert.equal(call.headers['x-zar-calendar-csrf'],'TEST-csrf');assert.equal(posts.filter(x=>x.path==='/api/calendar/create').length,1);
 }
 await page.screenshot({path:`${out}/${width}-${id}.png`});
 await page.getByRole('button',{name:'Cerrar '+title,exact:true}).click();assert.equal(await page.locator('iframe.zwtPane').count(),0);
}
assert.deepEqual(errors,[],`${width}: JS errors`);assert.equal(posts.filter(x=>/publish|send|execute|produce|generate/.test(x.path)).length,0);console.log(`PASS ${width}x${height}: ${modules.length} workspaces, screenshots, calendar cancel/confirm, settings failure/retry, no JS errors`);await page.close();
}
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
