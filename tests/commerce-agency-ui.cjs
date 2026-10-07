const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
  try{
    const styles=[...fs.readFileSync('app/templates/index.html','utf8').matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(x=>x[1]).join('\n');
    for(const viewport of [{width:1920,height:1080},{width:390,height:844}]){
      const page=await browser.newPage({viewport}),errors=[],posts=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
      const state={csrf:'offline-csrf',commerce:{niches:[{id:'niche-offline',name:'Hogar',country:'ES',subniches:['cajas'],restrictions:[]}],
        suppliers:[{id:'supplier-offline',name:'Offline supplier'}],products:[{id:'product-offline',name:'Organizador',state:'CANDIDATE'}],
        listings:[],orders:[],quotes:[],fulfillments:[],operations:[],research:[],dashboard:{profit:null}},
        agency:{leads:[{id:'lead-offline',name:'Negocio offline',state:'LEAD',sector:'Jardinería',city:'Offline city',services:'Macetas',proposals:[],emails:[{id:'draft-offline',to:'lead@example.test',subject:'ZAR',body:'Somos ZAR. Baja disponible.',sent:false}],history:[]}],payments:[]}};
      await page.route('**/*',route=>{
        const req=route.request();if(new URL(req.url()).pathname==='/')return route.fulfill({contentType:'text/html',body:`<style>${styles}</style><div class="app orchestration-mode"><section id="orchestrationWorkspace" class="orchestrationWorkspace"><div id="orchestrationWorkspaceInner" class="orchestrationWorkspaceInner"></div></section></div>`});
        assert.equal(req.headers()['x-zar-business-csrf'],'offline-csrf');posts.push({path:new URL(req.url()).pathname,body:req.postDataJSON()});
        return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,result:{state:'OFFLINE_TEST'}})});
      });
      await page.goto('http://zar.invalid/');
      await page.addScriptTag({content:fs.readFileSync('app/static/commerce-agency.js','utf8')});
      await page.evaluate(state=>{
        window.caTestState=state;window.zarWorkflowRefresh=()=>window.dispatchEvent(new CustomEvent('zar-workflow-state',{detail:window.caTestState}));
        window.zarWorkflowRefresh();
      },state);
      await page.locator('#zarCommerceAgency details').first().locator('summary').click();
      const niche=page.locator('[data-ca-form=commerce_niche]').first();await niche.locator('[name=name]').fill('Edited niche');
      await page.evaluate(()=>zarWorkflowRefresh());assert.equal(await niche.locator('[name=name]').inputValue(),'Edited niche');
      await niche.locator('button').click();await page.waitForFunction(()=>document.querySelector('#caNotice').textContent.includes('OFFLINE_TEST'));
      assert.equal(posts[0].body.name,'Edited niche');assert.equal(posts[0].body.id,'niche-offline');
      await page.getByRole('button',{name:'Productos',exact:true}).click();
      await page.getByRole('button',{name:'Organizador · CANDIDATE',exact:true}).click();
      assert.equal(await page.locator('[data-ca-form=commerce_pricing]').count(),1);
      await page.getByRole('button',{name:'Negocio offline',exact:true}).click();
      await page.locator('[data-ca-form=agency_send] button').click();
      await page.waitForFunction(()=>document.querySelector('#caNotice').textContent.includes('OFFLINE_TEST'));
      assert.equal(posts.at(-1).path,'/api/holdings/workflows/agency_send');
      assert.equal(posts.at(-1).body.confirmed,true);
      assert.equal(posts.at(-1).body.draft_id,'draft-offline');
      await page.locator('[data-ca-form=agency_state] [name=state]').selectOption('DO_NOT_CONTACT');
      await page.locator('[data-ca-form=agency_state] button').click();
      await page.waitForFunction(()=>document.querySelector('#caNotice').textContent.includes('OFFLINE_TEST'));
      assert.equal(posts.at(-1).body.state,'DO_NOT_CONTACT');assert.equal(posts.at(-1).body.confirmed,true);
      assert.equal(await page.locator('#zarCommerceAgency').count(),1);assert.deepEqual(errors,[]);
      const geometry=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
      assert.ok(geometry.scroll<=geometry.width,JSON.stringify(geometry));
      await page.close();
    }
    console.log('PASS: Commerce/CRM desktop/mobile, editable niches, product detail, CSRF, explicit approval, no global overflow or JS errors');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
