// Isolated WebView UI regression: no provider login or real OAuth grant.
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.ZAR_TEST_BROWSER});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844},userAgent:'Mozilla/5.0 (Linux; Android 14; Pixel 7 Build/TEST; wv) AppleWebKit/537.36 Version/4.0 Chrome/130.0.0.0 Mobile Safari/537.36'});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));let completed=false,starts=0;
  const provider={id:'google',name:'Google',category:'GOOGLE',icon:'G',status:'AUTH_REQUIRED',used_by:['Workspace'],last_verified:new Date().toISOString(),capabilities:{}};
  await page.route('**/*',async route=>{
   const u=new URL(route.request().url());
   if(u.pathname.startsWith('/static/'))return route.fulfill({path:path.join('app',u.pathname)});
   if(u.pathname==='/accounts')return route.fulfill({contentType:'text/html',body:fs.readFileSync('app/templates/accounts.html','utf8')});
   if(u.pathname==='/api/accounts/connections')return route.fulfill({json:{csrf:'TEST',providers:[{...provider,status:completed?'CONNECTED':'AUTH_REQUIRED'}]}});
   if(u.pathname==='/api/accounts/connections/google/connect'){
    starts++;assert.equal(route.request().postDataJSON().external,true);
    assert.equal(route.request().headers()['x-zar-business-csrf'],'TEST');
    return route.fulfill({json:{ok:true,external:true,poll_id:'TEST-single-use',url:'https://zar.test/oauth/accounts/start/TEST-single-use'}});
   }
   if(u.pathname==='/api/accounts/oauth/status/TEST-single-use')return route.fulfill({json:{status:completed?'CONNECTED':'PENDING'}});
   if(u.pathname==='/api/accounts/connections/google/reverify')return route.fulfill({json:{ok:true,result:{...provider,status:completed?'CONNECTED':'AUTH_REQUIRED'}}});
   throw Error('Unexpected network request '+u.origin+u.pathname);
  });
  await page.goto('https://zar.test/accounts');
  await page.getByRole('button',{name:'CONECTAR',exact:true}).click();
  await page.getByRole('link',{name:'ABRIR NAVEGADOR SEGURO'}).waitFor();
  const href=await page.getByRole('link',{name:'ABRIR NAVEGADOR SEGURO'}).getAttribute('href');
  assert(href.startsWith('intent://zar.test/oauth/accounts/start/TEST-single-use#Intent;scheme=https;'));
  assert(href.includes('package=com.android.chrome'));
  assert(!href.includes('accounts.google.com'));
  assert((await page.locator('#notice').innerText()).includes('Conectando'));
  completed=true;
  await page.waitForFunction(()=>document.querySelector('#notice').textContent==='Cuenta conectada correctamente.');
  await page.waitForFunction(()=>document.querySelector('#google .status').textContent==='✓ CONECTADA');
  assert.equal(starts,1);assert.deepEqual(errors,[]);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  console.log(JSON.stringify({webview_external_intent:'PASS',csrf:'PASS',cookie_independent_poll:'PASS',status_refresh:'PASS',width:390,js_errors:0,real_oauth_grants:0}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
