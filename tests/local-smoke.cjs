// Live localhost reads only. No connected accounts; forbid external requests and writes.
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
(async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:900}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',r=>{
      const u=new URL(r.request().url());
      if(u.origin!=='http://127.0.0.1:8765'||r.request().method()!=='GET')return r.abort();
      return r.continue();
    });
    await page.goto('http://127.0.0.1:8765/');
    const get=path=>page.evaluate(p=>fetch(p).then(r=>{if(!r.ok)throw new Error(p+' '+r.status);return r.json()}),path);
    assert.equal((await get('/health')).ok,true);
    assert.equal((await get('/api/holdings/state')).ok,true);
    assert.equal((await get('/api/holdings/media/jobs')).ok,true);
    const stonks=await get('/api/stonks/status');
    assert.equal(stonks.live_trading_enabled,false);
    assert.equal(stonks.paper_configured,false);
    await page.evaluate(()=>showHoldings());
    await page.waitForFunction(()=>document.getElementById('zhMediaTopic'));
    assert.equal(await page.locator('#zhMediaTopic').isVisible(),true);
    await page.evaluate(()=>{closeHoldings();showWorkspace()});
    assert.match(await page.locator('#panelBody').innerText(),/Google Workspace/);
    await page.evaluate(()=>{closePanel();showStonks()});
    await page.waitForFunction(()=>document.getElementById('zsTab-dashboard'));
    assert.equal(await page.locator('#zsTab-dashboard').isVisible(),true);
    assert.deepEqual(errors,[]);
    console.log('PASS live localhost: health, Holdings, Media, Workspace, Stonks Paper; no writes or external browser requests');
  } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
