const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
 try{for(const width of [1440,390]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  const state={google:{status:'CREATED',account_exists:true,email:null},capabilities:{},plans:[],human_actions:[],mail_audit:[],onboarding:[{service:'GOOGLE',status:'ACTION_REQUIRED'}]};
  await page.route('**/*',route=>{
   const req=route.request(),path=new URL(req.url()).pathname;
   if(path==='/')return route.fulfill({contentType:'text/html',body:'<div id="orchestrationWorkspaceInner"></div>'});
   const data=req.postDataJSON();assert.equal(req.headers()['x-zar-business-csrf'],'offline');writes.push({path,data});
   if(path.endsWith('register'))Object.assign(state.google,{email:data.email,status:'NEEDS_OAUTH'});
   if(path.endsWith('request')){state.plans=[{service:'SHOPIFY',identity:state.google.email,status:'HUMAN_ACTION_REQUIRED',configuration:[]}];state.human_actions=[{id:'human-shop',service:'SHOPIFY',action:'SETUP',status:'ACTION_REQUIRED',instructions:['Seleccionar plan personalmente'],reason:'Billing humano',url:'https://www.shopify.com/free-trial'}];}
   return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,result:{status:path.endsWith('continue')?'ACTION_REQUIRED':'CONFIRMED',message_id:'offline-message'}})});
  });
  await page.goto('https://zar.invalid/');await page.addScriptTag({content:fs.readFileSync('app/static/identity-provisioning.js','utf8')});
  async function render(){await page.evaluate(s=>{window.__identity=s;window.zarWorkflowRefresh=async()=>window.dispatchEvent(new CustomEvent('zar-workflow-state',{detail:{csrf:'offline',identity_center:window.__identity}}));zarWorkflowRefresh();},state);}
  await render();assert.match(await page.locator('#zarIdentityCenter').innerText(),/ya existe/);assert.equal(await page.locator('a[href*=signup]').count(),0);
  await page.locator('[data-identity-register] [name=email]').fill('zar.offline@gmail.com');await page.locator('[data-identity-register] button').click();
  await render();await page.waitForFunction(()=>document.querySelector('a[href*="purpose=zar"]'));
  const href=await page.getByRole('link',{name:'CONECTAR CUENTA GOOGLE DE ZAR'}).getAttribute('href');assert.ok(href.includes('email=zar.offline%40gmail.com'));
  await page.locator('[data-identity-request] [name=request]').fill('Necesito Shopify para ZAR');await page.locator('[data-identity-request] button').click();await render();
  await page.locator('[data-human]').click();await page.waitForFunction(()=>document.getElementById('zarIdentityNotice').textContent.includes('ACTION_REQUIRED'));
  await page.locator('[data-mail-compose] [name=to]').fill('recipient@example.test');await page.locator('[data-mail-compose] [name=subject]').fill('Reviewed draft');await page.locator('[data-mail-compose] [name=body]').fill('Offline body');
  const tid=await page.locator('[name=transaction_id]').inputValue();await page.locator('[data-mail-compose] button').click();await page.waitForFunction(()=>document.getElementById('zarMailResult').textContent.includes('offline-message'));
  const sent=writes.find(x=>x.path.endsWith('identity_mail_draft'));assert.equal(sent.data.transaction_id,tid);assert.equal(sent.data.confirmed,true);
  assert.equal(await page.locator('#zarIdentityCenter input[type=password]').count(),0);assert.deepEqual(errors,[]);
  assert.ok(await page.locator('#zarIdentityCenter').isVisible());console.log('PASS existing identity/onboarding/human actions/Mail UI',width);await page.close();
 }}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
