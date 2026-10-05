const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const {chromium} = require('playwright');
const html = fs.readFileSync('app/templates/index.html','utf8');
for (const [i,m] of [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].entries()) new vm.Script(m[1],{filename:'inline-'+i});
(async () => {
  const browser = await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
  try {
    for (const size of [{width:1440,height:900},{width:390,height:844}]) {
      const page = await browser.newPage({viewport:size}); const errors=[], writes=[];
      page.on('pageerror',e=>errors.push(e.message));
      let state = 'ONLINE';
      await page.route('**/*',r=> {
        const path = new URL(r.request().url()).pathname;
        if (path === '/') return r.fulfill({contentType:'text/html',body:html});
        if (path.startsWith('/static/') && fs.existsSync('app'+path)) return r.fulfill({contentType:path.endsWith('.css')?'text/css':path.endsWith('.js')?'application/javascript':'image/png',body:fs.readFileSync('app'+path)});
        let data = {ok:true};
        if (path === '/api/holdings/state') data = {ok:true,totals:{},companies:{},connectors:{},ledger:[]};
        if (path === '/api/holdings/media/jobs') data = {ok:true,tasks:[],connector:{ready:false}};
        if (path === '/api/nodes') data = {csrf:'test-csrf',nodes:[{id:'d8ee5a76-2a0b-43f8-aca5-a09b1d840b14',name:'ZAR-NODE-02-MAC',state,resources:{os:'Darwin',architecture:'x86_64',cpu_count:4,ram_bytes:8589934592,load:[.2]},version:'33.2.0',worker_version:'1.0.0',uptime:120,last_seen:Date.now()/1000,capabilities:['python','node','filesystem'],jobs:1,current_job:null,last_result:{hostname:'mac-test'},last_error:'<script>bad()</script>'}]};
        if (r.request().method() === 'POST' && path.startsWith('/api/nodes/')) {
          assert.equal(r.request().headers()['x-zar-nodes-csrf'],'test-csrf'); writes.push(path);
          state = path.endsWith('/pause') ? 'PAUSED' : path.endsWith('/resume') ? 'ONLINE' : 'REVOKED';
        }
        return r.fulfill({contentType:'application/json',body:JSON.stringify(data)});
      });
      await page.goto('https://zar.test/');
      await page.evaluate(()=>showHoldings());
      await page.waitForSelector('.zarNodeCard');
      assert.match(await page.locator('#zarNodesSection').textContent(),/NODOS ZAR.*ZAR-NODE-02-MAC/s);
      const box = await page.locator('.zarNodeCard').boundingBox();
      assert.ok(box.width>200 && box.x>=0 && box.x+box.width<=size.width+1,JSON.stringify(box));
      assert.equal(await page.locator('.zarNodeCard script').count(),0);
      assert.equal(await page.locator('.zarNodeActions button').count(),3);
      await page.click('[data-action="pause"]'); await page.waitForFunction(()=>document.querySelector('.zarNodeState').textContent.includes('PAUSED'));
      await page.click('[data-action="resume"]'); await page.waitForFunction(()=>document.querySelector('.zarNodeState').textContent.includes('ONLINE'));
      page.once('dialog',d=>d.dismiss()); await page.click('[data-action="revoke"]'); assert.equal(writes.length,2);
      page.once('dialog',d=>d.accept()); await page.click('[data-action="revoke"]'); await page.waitForFunction(()=>document.querySelector('.zarNodeState').textContent.includes('REVOKED'));
      assert.equal(await page.locator('.zarNodeActions button:disabled').count(),3);
      assert.deepEqual(errors,[]);
      const duplicates = await page.evaluate(()=>{const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);return ids.filter((id,i)=>ids.indexOf(id)!==i)});
      assert.deepEqual(duplicates,[]);
      await page.evaluate(()=>closeHoldings()); await page.close();
      console.log(`PASS nodes UI ${size.width}x${size.height}: full ZAR page/CSS, Holdings cards, controls, CSRF, escape, revocation, no card overflow`);
    }
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1)});
