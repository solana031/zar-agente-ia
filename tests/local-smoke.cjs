// Live localhost reads only. No connected accounts; forbid external requests and writes.
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const base=process.env.ZAR_TEST_BASE || 'http://127.0.0.1:8765';
assert.equal(new URL(base).hostname,'127.0.0.1');assert.equal(new URL(base).protocol,'http:');
(async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:900}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',r=>{
      const u=new URL(r.request().url());
      if(u.origin!==base||r.request().method()!=='GET')return r.abort();
      return r.continue();
    });
    await page.goto(base+'/');
    const get=path=>page.evaluate(p=>fetch(p).then(r=>{if(!r.ok)throw new Error(p+' '+r.status);return r.json()}),path);
    assert.equal((await get('/health')).ok,true);
    assert.equal((await get('/api/holdings/state')).ok,true);
    assert.equal((await get('/api/holdings/media/jobs')).ok,true);
    const stonks=await get('/api/stonks/status');
    assert.equal(stonks.live_trading_enabled,false);
    assert.equal(stonks.paper_configured,false);
    const preflight=await get('/api/stonks/lifecycle-test/preflight?symbol=AAPL');
    assert.equal(preflight.ok,true);
    assert.equal(preflight.paper,true);
    assert.ok(['BLOCKED','UNVERIFIED'].includes(preflight.preflight.status));
    const integrations=await get('/api/integrations');
    assert.equal(integrations.cards.length,7);
    assert.equal(integrations.policy.monthly_cents,0);
    assert.equal(integrations.policy.conway_mode,'OFF');
    assert.equal(integrations.policy.coding_mode,'DISABLED');
    await page.evaluate(()=>showHoldings());
    await page.waitForFunction(()=>document.getElementById('zhMediaTopic'));
    assert.equal(await page.locator('#zhMediaTopic').isVisible(),true);
    await page.evaluate(()=>{closeHoldings();showWorkspace()});
    assert.match(await page.locator('#panelBody').innerText(),/Google Workspace/);
    await page.evaluate(()=>{closePanel();showStonks()});
    await page.waitForFunction(()=>document.getElementById('zsTab-dashboard'));
    assert.equal(await page.locator('#zsTab-dashboard').isVisible(),true);
    assert.deepEqual(errors,[]);
    console.log('PASS live localhost: health, Holdings, integrations/budget=0, Media, Workspace, Stonks Paper; no writes or external browser requests');
  } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
