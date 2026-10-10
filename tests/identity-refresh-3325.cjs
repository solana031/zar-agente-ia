const fs=require('node:fs'),assert=require('node:assert/strict'),{chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
 try{
  const context=await browser.newContext();let probes=0;
  const center={google:{email:'zaragente031@gmail.com',status:'ACTIVE',last_verified:'2000-01-01T00:00:00Z'},integrations:[{service:'GMAIL',status:'ACTION_REQUIRED',reason:'Verificación anterior'}],capabilities:{},onboarding:[],plans:[],human_actions:[],mail_audit:[]};
  const snapshot=()=>({csrf:'fixture',identity_center:center});
  await context.route('**/*',r=>{
   const path=new URL(r.request().url()).pathname;
   if(path==='/')return r.fulfill({contentType:'text/html',body:'<div id="orchestrationWorkspaceInner"></div><script src="/static/identity-provisioning.js"></script>'});
   if(path==='/static/identity-provisioning.js')return r.fulfill({contentType:'application/javascript',body:fs.readFileSync('app/static/identity-provisioning.js')});
   if(r.request().method()==='POST'){
    assert.equal(path,'/api/holdings/workflows/identity_center_verify');probes++;
    center.google.last_verified=new Date().toISOString();center.integrations[0].status='CONNECTED';
    return r.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,result:center})});
   }
   return r.fulfill({contentType:'application/json',body:JSON.stringify(snapshot())});
  });
  for(let i=0;i<2;i++){
   const page=await context.newPage();await page.goto('https://zar.test/');
   await page.evaluate(async()=>{window.zarWorkflowRefresh=async()=>{const j=await fetch('/api/holdings/workflows').then(r=>r.json());dispatchEvent(new CustomEvent('zar-workflow-state',{detail:j}));};await zarWorkflowRefresh();});
   await page.waitForFunction(()=>document.getElementById('zarIdentityCenter')?.innerText.includes('CONNECTED'));
   assert.equal(probes,1,'One read-only verification is shared across workspaces');
  }
  console.log('PASS stale Google capabilities refresh automatically; no duplicate probes or external writes');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
