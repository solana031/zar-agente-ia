const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {chromium}=require('playwright');
new vm.Script(fs.readFileSync('app/static/integrations.js','utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
 try{for(const width of [1440,390]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));
  const policy={kill_switch:false,conway_mode:'OFF',coding_mode:'DISABLED',per_task_cents:0,daily_cents:0,monthly_cents:0,providers:{}};
  const names=['DramaClaw','Jev','Conway Automaton','Coding Agent','NODE-01','NODE-02','ZAR Cloud'];
  await page.route('**/*',route=>{
   const req=route.request(),path=new URL(req.url()).pathname;
   if(path==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync('app/templates/index.html','utf8')});
   if(path.startsWith('/static/')&&fs.existsSync('app'+path))return route.fulfill({contentType:path.endsWith('.js')?'application/javascript':path.endsWith('.css')?'text/css':'image/png',body:fs.readFileSync('app'+path)});
   let data={ok:true};
   if(path==='/api/holdings/state')data={ok:true,totals:{},companies:{},connectors:{},ledger:[]};
   if(path==='/api/holdings/media/jobs')data={ok:true,tasks:[],connector:{ready:false}};
   if(path==='/api/nodes')data={nodes:[]};
   // Existing ZAR boot clears ephemeral chat context; mock it separately.
   if(path==='/api/context/reset' && req.method()==='POST')return route.fulfill({contentType:'application/json',body:'{"ok":true}'});
   if(path==='/api/integrations')data={ok:true,csrf:'fixture-csrf',policy,cards:names.map((name,i)=>({name,state:i===0?'DEGRADED':i===2||i===3?'DISABLED':'NOT_CONFIGURED',version:'33.3.0',node:'<img src=x onerror=alert(1)>',capabilities:['official API'],last_heartbeat:null,estimated_cost_eur:null,missing:['Not verified'],...(i===0?{probe:'dramaclaw'}:i===1?{probe:'jev'}:i===2?{probe:'conway',mode:policy.conway_mode}:i===3?{probe:'coding',mode:policy.coding_mode}:{})}))};
   if(req.method()==='POST'){
    assert.ok(['/api/integrations/probe/jev','/api/integrations/policy'].includes(path),'Unexpected operational request '+path);
    assert.equal(req.headers()['x-zar-integrations-csrf'],'fixture-csrf');writes.push(path);
    if(path==='/api/integrations/policy'){const body=req.postDataJSON();assert.equal(body.confirmed,true);Object.assign(policy,body.changes);}
    data={ok:true,result:{fallback_verified:true,external_call:false}};
   }
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('https://zar.test');await page.evaluate(()=>showHoldings());
  await page.waitForSelector('.zarIntegrationCard');
  assert.equal(await page.locator('.zarIntegrationCard').count(),7);
  assert.equal(await page.locator('.zarIntegrationCard img,.zarIntegrationCard script').count(),0);
  assert.match(await page.locator('#zarAutomationBudget').innerText(),/0.00 EUR automático\/mes/);
  assert.equal(await page.locator('[data-integration-probe="conway"]').isDisabled(),true);
  assert.equal(await page.locator('[data-integration-mode="conway_mode"] option[value="EXECUTE"]').evaluate(option=>option.disabled),true);
  for(const card of await page.locator('.zarIntegrationCard').all()){
   const box=await card.boundingBox();assert.ok(box.width>200&&box.x>=-1&&box.x+box.width<=width+1,JSON.stringify(box));
  }
  await page.click('[data-integration-probe="jev"]');await page.waitForFunction(()=>document.getElementById('zarIntegrationsNotice').textContent.includes('fallback_verified'));
  assert.equal(writes.length,1);
  page.once('dialog',d=>d.dismiss());await page.selectOption('[data-integration-mode="coding_mode"]','PATCH');
  assert.equal(writes.length,1);assert.equal(await page.locator('[data-integration-mode="coding_mode"]').inputValue(),'DISABLED');
  await page.fill('[data-budget="daily_cents"]','1.50');await page.evaluate(()=>zarIntegrationsRefresh());
  assert.equal(await page.locator('[data-budget="daily_cents"]').inputValue(),'1.50');
  page.once('dialog',d=>d.dismiss());await page.click('[data-budget-save]');assert.equal(writes.length,1);
  page.once('dialog',d=>d.accept());await page.click('[data-automation-kill]');
  await page.waitForFunction(()=>document.getElementById('zarAutomationBudget').textContent.includes('Rearmar controles'));
  assert.deepEqual(writes,['/api/integrations/probe/jev','/api/integrations/policy']);
  const duplicates=await page.evaluate(()=>{const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);return ids.filter((id,i)=>ids.indexOf(id)!==i)});
  assert.deepEqual(duplicates,[]);assert.deepEqual(errors,[]);
  await page.evaluate(()=>closeHoldings());await page.close();
  console.log(`PASS integrations UI ${width}: seven evidence cards, escaped metadata, zero budget, no operational calls, confirmations/CSRF, no overflow/JS errors`);
 }}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
