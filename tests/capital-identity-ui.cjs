// All provider and accounting APIs are mocked. No real orders or registrations.
const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
 try{for(const width of [1440,390]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  const identity={base_identity:null,plans:[]};
  await page.route('**/*',route=>{
   const r=route.request(),p=new URL(r.url()).pathname;
   if(p==='/')return route.fulfill({contentType:'text/html',body:'<section id="zsTab-automaton" class="active"></section><div id="orchestrationWorkspaceInner"></div>'});
   let result={ok:true};
   if(r.method()==='POST'){
    assert.equal(r.headers()['x-zar-business-csrf'],'offline');writes.push({p,data:r.postDataJSON()});
    result.transaction={status:'CONFIRMED'};result.result={status:'HUMAN_ACTION_REQUIRED'};
    if(p.endsWith('suggest'))result.result={alternatives:[{email:'zar.mock@gmail.com'}]};
   }else if(p.endsWith('/capital'))result={ok:true,csrf:'offline',capital:{currency:'USD',wallet_available:'100',assigned:'0',note:'Reserva contable Paper',transactions:[]}};
   else if(p.endsWith('/portfolio'))result={ok:false,state:'POR CONFIGURAR',error:'Mock missing broker'};
   else if(p.endsWith('/status'))result={ok:true,automaton:{state:'PAUSED'}};
   return route.fulfill({contentType:'application/json',body:JSON.stringify(result)});
  });
  await page.goto('https://zar.invalid/');
  await page.addScriptTag({content:fs.readFileSync('app/static/trading-capital.js','utf8')});
  await page.addScriptTag({content:fs.readFileSync('app/static/identity-provisioning.js','utf8')});
  await page.evaluate(()=>zarTradingRefresh(true));
  assert.ok(await page.locator('#zsTradingBudget').isVisible());
  assert.match(await page.locator('#zsAutomatonPortfolio').innerText(),/POR CONFIGURAR/);
  await page.locator('[data-trading-capital] [name=amount]').fill('20');
  await page.locator('[data-trading-capital] [name=reason]').fill('Asignación explícita');
  const tid=await page.locator('[name=transaction_id]').inputValue();
  await page.evaluate(()=>zarTradingRefresh());assert.equal(await page.locator('[name=amount]').inputValue(),'20');
  await page.locator('[data-trading-capital] button').click();
  await page.waitForFunction(()=>document.querySelector('[name=amount]').value==='');
  assert.equal(writes[0].data.transaction_id,tid);assert.equal(writes[0].data.confirmed,true);
  assert.equal(writes[0].data.currency,'USD');assert.notEqual(await page.locator('[name=transaction_id]').inputValue(),tid);
  await page.evaluate(j=>{window.zarWorkflowRefresh=async()=>{};window.dispatchEvent(new CustomEvent('zar-workflow-state',{detail:{csrf:'offline',identity:j}}));},identity);
  assert.ok(await page.locator('#zarIdentityCenter').isVisible());
  await page.locator('[data-identity-prepare] [name=desired_name]').fill('zar.mock');
  await page.locator('[data-identity-suggest]').click();await page.waitForFunction(()=>document.getElementById('zarIdentitySuggestions').textContent.includes('no verificada'));
  await page.locator('[data-identity-prepare] [name=identity]').fill('zar.mock@gmail.com');
  await page.locator('[data-identity-prepare] button:not([type=button])').click();
  await page.waitForTimeout(100);assert.ok(writes.some(x=>x.p.endsWith('identity_provision_prepare')&&x.data.identity==='zar.mock@gmail.com'));
  identity.plans=[{id:'mock',service:'GOOGLE',identity:'zar.mock@gmail.com',status:'HUMAN_ACTION_REQUIRED',oauth_state:'UNVERIFIED',capabilities:[],steps:['Datos humanos'],url:'https://accounts.google.com/signup'}];
  await page.evaluate(j=>{document.getElementById('zarIdentityCenter').dataset.editing='';window.dispatchEvent(new CustomEvent('zar-workflow-state',{detail:{csrf:'offline',identity:j}}));},identity);
  await page.locator('[data-identity-op=start]').click();await page.waitForTimeout(100);
  assert.ok(writes.some(x=>x.p.endsWith('identity_provision_start')));
  assert.match(await page.locator('#zarIdentityNotice').innerText(),/HUMAN_ACTION_REQUIRED/);
  assert.equal(await page.locator('#zarIdentityCenter input[type=password]').count(),0);
  assert.deepEqual(errors,[]);console.log('PASS capital/identity UI',width);await page.close();
 }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
