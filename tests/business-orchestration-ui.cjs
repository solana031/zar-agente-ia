const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
(async () => {
  const browser=await chromium.launch({headless:true,...(process.env.ZAR_TEST_BROWSER?{executablePath:process.env.ZAR_TEST_BROWSER}:{})});
  try {
    const page=await browser.newPage();const errors=[],posts=[];
    page.on('pageerror',e=>errors.push(e.message));
    const state={ok:true,csrf:'test-csrf',mode:'OFF',cycles:0,last_heartbeat:null,global_stop:false,
      wallet:{state:'NO CONECTADO',bank_state:'NO CONECTADO',balances:{},note:'Saldo no verificado'},
      agents:{RevenueAgent:{id:'RevenueAgent',name:'RevenueAgent',state:'IDLE',function:'wallet_snapshot',tools:['wallet_snapshot'],completed_tasks:[]}},
      tasks:[],approvals:[],accounts:[],connectors:[{name:"Alpaca Paper",group:"TRADING",state:"POR CONFIGURAR",missing:["ALPACA_API_KEY"],configuration:[{variable:"ALPACA_API_KEY",expected:"Paper key",obtain_at:"https://app.alpaca.markets",paste_at:"Railway Variables"}],verify:{path:"/api/stonks/alpaca/verify"}}],ledger:[],decisions:[]};
    await page.route('**/*',route=>{
      const req=route.request(),path=new URL(req.url()).pathname;
      if(path==='/')return route.fulfill({contentType:'text/html',body:'<section id="orchestrationWorkspace"><div id="orchestrationWorkspaceInner"></div></section>'});
      if(req.method()==='POST'){
        assert.equal(req.headers()['x-zar-business-csrf'],'test-csrf');
        const body=req.postDataJSON();posts.push({path,body});
        if(path.endsWith('/mode'))state.mode=body.mode;
        if(path.endsWith('/agent'))state.agents.RevenueAgent.state=body.state;
      }
      return route.fulfill({contentType:'application/json',body:JSON.stringify(state)});
    });
    await page.goto('http://zar.invalid/');
    await page.addScriptTag({content:fs.readFileSync('app/static/business-orchestration.js','utf8')});
    await page.evaluate(()=>zarBusinessRefresh());
    await page.getByRole('button',{name:'SUPERVISED',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#zarBusinessControl').textContent.includes('Modo SUPERVISED'));
    await page.getByRole('button',{name:'PAUSED',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#zarBusinessControl article').textContent.includes('PAUSED'));
    await page.locator('[data-funding] [name=amount]').fill('125.50');
    await page.locator('[data-funding] [name=reference]').fill('pablo-funding');
    await page.evaluate(()=>zarBusinessRefresh());
    assert.equal(await page.locator('[data-funding] [name=amount]').inputValue(),'125.50');
    await page.locator('[data-funding] button').click();
    await page.waitForFunction(()=>document.querySelector('[data-funding] [name=amount]').value==='');
    assert.equal(posts.find(x=>x.path.endsWith('/deposit')).body.amount,'125.50');
    await page.locator('summary').filter({hasText:'CONFIGURAR Alpaca Paper'}).click();
    assert.ok((await page.locator('#zarBusinessControl').innerText()).includes('Railway Variables'));
    await page.locator('[data-verify-node]').click();
    await page.waitForFunction(()=>!document.querySelector('#zarBusinessControl').dataset.editing);
    assert.equal(posts.at(-1).path,'/api/stonks/alpaca/verify');
    assert.equal(await page.locator('#zarBusinessControl').count(),1);
    assert.deepEqual(errors,[]);
    console.log('PASS: workspace controls, CSRF header, modes, pause, funding, preserved form edits, no browser errors');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
