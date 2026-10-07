const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
  try{
    for(const viewport of [{width:1920,height:1080},{width:390,height:844}]){
      const page=await browser.newPage({viewport}),errors=[],posts=[];
      page.on('pageerror',e=>errors.push(e.message));
      const state={ok:true,csrf:'offline-csrf',jev:[{decision:'DEFER',requesting_agent:'DirectorAgent',output:{risk_score:null,expected_cost:null,expected_profit:null}}],
        media:[{id:'media-test',payload:{master_brief:'A full story'},result:{project:{title:'Film'},project_state:'REVIEW',scenes:[],characters:[],subtitles:{position:'top',text:''}}}],sites:[],adsense:{state:'POR CONFIGURAR',metrics:null,payments:[]}};
      await page.route('**/*',route=>{
        const req=route.request();
        if(new URL(req.url()).pathname==='/')return route.fulfill({contentType:'text/html',body:'<section id="orchestrationWorkspace"><div id="orchestrationWorkspaceInner"></div></section>'});
        if(req.method()==='POST'){
          assert.equal(req.headers()['x-zar-business-csrf'],'offline-csrf');posts.push(req.postDataJSON());
          return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,result:{}})});
        }
        return route.fulfill({contentType:'application/json',body:JSON.stringify(state)});
      });
      await page.goto('http://zar.invalid/');
      await page.addScriptTag({content:fs.readFileSync('app/static/business-workflows.js','utf8')});
      await page.evaluate(()=>zarWorkflowRefresh());
      await page.locator('[data-op=detail]').click();
      await page.getByText('Subtítulos sincronizados',{exact:true}).click();
      await page.waitForSelector('[data-form=subtitles]');
      assert.equal(await page.locator('[data-form=subtitles] [name=position]').inputValue(),'top');
      await page.locator('[data-form=media] [name=story]').fill('Persist this draft');
      await page.evaluate(()=>zarWorkflowRefresh());
      assert.equal(await page.locator('[data-form=media] [name=story]').inputValue(),'Persist this draft');
      await page.locator('[data-form=jev] [name=task]').fill('Inspect');
      await page.locator('[data-form=jev] [name=action]').fill('Read only');
      await page.locator('[data-form=jev] button').click();
      await page.waitForFunction(()=>document.querySelector('[data-form=media] [name=story]').value==='');
      assert.equal(posts[0].proposal.expected_cost,null);
      assert.equal(posts[0].proposal.expected_revenue,null);
      assert.equal(await page.locator('#zarBusinessWorkflows').count(),1);
      assert.deepEqual(errors,[]);
      await page.close();
    }
    console.log('PASS: desktop/mobile DOM, JEV unknowns, CSRF, media detail and preserved edits');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
