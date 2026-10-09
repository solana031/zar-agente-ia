const fs=require('node:fs'),assert=require('node:assert/strict'),{chromium}=require('playwright');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});try{
 for(const width of [390,1440]){
  const page=await browser.newPage({viewport:{width,height:844}}),posts=[];
  await page.route('**/*',r=>{const p=new URL(r.request().url()).pathname;if(r.request().method()==='POST')posts.push({path:p,data:r.request().postDataJSON()});return r.fulfill({contentType:'application/json',body:JSON.stringify(p==='/api/mail/identities'?{ok:true,accounts:[{email:'zaragente031@gmail.com',label:'ZAR',status:'VERIFIED'}]}:{ok:true,tasks:[],csrf:'fixture'})});});
  await page.goto('https://zar.test/');await page.setContent('<main></main>');
  for(const path of ['app/static/zar-ui.css','app/static/workspace-tabs.css'])await page.addStyleTag({content:fs.readFileSync(path,'utf8')});
  for(const path of ['app/static/zar-ui.js','app/static/mail-identity.js','app/static/task-results.js'])await page.addScriptTag({content:fs.readFileSync(path,'utf8')});
  const task={id:'fixture',outputs:{CREATE_REPORT:{title:'Informe.pdf'},DRAFT_EMAIL:{to:'recipient@example.test',subject:'Informe',body:'Adjunto el informe',artifact_ids:['file1']}}};
  await page.evaluate(t=>{window.ZarTaskResults.reviewEmail(t,'fixture');},task);
  await page.getByRole('dialog').waitFor();assert.match(await page.getByRole('dialog').innerText(),/DESDE QUÉ CUENTA/);
  assert.equal(await page.locator('select option').count(),2,'No imaginary personal account');
  await page.locator('select').selectOption('zaragente031@gmail.com');await page.getByRole('button',{name:'Continuar',exact:true}).click();
  assert.match(await page.getByRole('dialog').innerText(),/DESDE: zaragente031@gmail.com/);assert.match(await page.getByRole('dialog').innerText(),/Informe.pdf/);
  await page.getByRole('button',{name:'ENVIAR INFORME',exact:true}).click();
  await page.getByRole('dialog').waitFor();assert.match(await page.getByRole('dialog').innerText(),/DESDE: zaragente031@gmail.com/);
  assert.equal(posts.length,1,'Only draft saved before final confirmation');assert.equal(posts[0].data.sender_identity,'zaragente031@gmail.com');
  await page.getByRole('button',{name:'Cancelar',exact:true}).click();assert.equal(posts.length,1,'Cancel never sends');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  console.log('PASS explicit sender, preview, attachment and cancellation '+width);await page.close();
 }
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
