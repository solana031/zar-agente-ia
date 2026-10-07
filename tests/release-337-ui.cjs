const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {chromium}=require('playwright');
(async()=>{
 const html=fs.readFileSync('app/templates/index.html','utf8');
 for(const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi))if(m[1].trim())new vm.Script(m[1]);
 const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
 try{for(const width of [1440,390]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('https://zar.invalid/**',r=>r.fulfill({contentType:'text/html',body:'<div id="orchestrationWorkspaceInner"></div>'}));
  await page.goto('https://zar.invalid/');await page.addScriptTag({content:fs.readFileSync('app/static/identity-provisioning.js','utf8')});
  await page.evaluate(()=>window.dispatchEvent(new CustomEvent('zar-workflow-state',{detail:{csrf:'fixture',identity_center:{google:{email:'fixture@gmail.com',status:'ACTIVE'},capabilities:{ADSENSE:{account_state:'NO_ACCOUNT'}},adsense_onboarding:{state:'SIGNUP_REQUIRED'},onboarding:[],plans:[],mail_audit:[],human_actions:[{id:'fixture',service:'YOUTUBE',title:'Crear canal YouTube',status:'HUMAN_ACTION_REQUIRED',reason:'Canal inexistente',instructions:['Nombre ZAR Agente IA','@zaragente031'],url:'https://www.youtube.com/account'}]}}})));
  const text=await page.locator('#zarIdentityCenter').innerText();
  for(const expected of ['NO_ACCOUNT','SIGNUP_REQUIRED','CREAR / ACTIVAR ADSENSE','SHOPIFY_SHOP_DOMAIN','SHOPIFY_ADMIN_ACCESS_TOKEN','STRIPE_SECRET_KEY','STRIPE_WEBHOOK_SECRET','ZAR Agente IA','@zaragente031','VALIDAR YOUTUBE · SIN SUBIR'])assert.ok(text.includes(expected),expected);
  assert.equal(await page.getByRole('button',{name:'CONFIGURAR',exact:true}).count(),2);assert.equal(await page.getByRole('button',{name:'VERIFICAR',exact:true}).count(),2);
  assert.equal(await page.locator('input[type=password]').count(),0);assert.ok((await page.getByRole('link',{name:'CREAR / ACTIVAR ADSENSE'}).getAttribute('href')).startsWith('https://www.google.com/adsense/'));
  assert.deepEqual(errors,[]);console.log('PASS focused onboarding/setup UI '+width);await page.close();
 }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
