// Run with Node and Playwright installed. Set ZAR_TEST_BROWSER for a system Chromium.
// All network responses are mocked; this test never contacts a trading service.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {chromium} = require('playwright');
const html = fs.readFileSync('app/templates/index.html', 'utf8');
let scripts = 0;
for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) {
  new vm.Script(match[1], {filename: `index-inline-${++scripts}.js`});
}
for (const file of fs.readdirSync('app/static').filter(f => f.endsWith('.js'))) {
  new vm.Script(fs.readFileSync(`app/static/${file}`, 'utf8'), {filename: file});
}
for (const file of ['VERSION', 'VERSION.txt', 'app/VERSION.txt']) {
  assert.equal(fs.readFileSync(file, 'utf8').trim(), '31.3.20');
}
console.log(`PASS: ${scripts} inline scripts, static JavaScript and three version files`);
(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.ZAR_TEST_BROWSER ? {executablePath: process.env.ZAR_TEST_BROWSER} : {})});
  try {
    for (const viewport of [{width: 1920, height: 1080}, {width: 1440, height: 900}, {width: 390, height: 844}]) {
      const page = await browser.newPage({viewport});
      const errors = [], requests = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => {
        const request = route.request(), url = new URL(request.url());
        requests.push({path: url.pathname, method: request.method(), body: request.postData()});
        if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: html});
        if (url.pathname === '/static/skills.js') return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync('app/static/skills.js', 'utf8')});
        return route.fulfill({contentType: 'application/json', body: JSON.stringify({
          ok: true, paused: true, revoked: false, mode: 'paper', execution_mode: 'decision',
          autonomous_engine: true, paper_configured: true, position_lifecycle_enabled: true,
          stop_loss_pct: 1.5, take_profit_pct: 3, managed_position_count: 2,
          managed_positions: {AAPL: {symbol:'AAPL', client_order_id:'zar-e-test', direction:'LONG', qty:'2', entry_price:100, current_price:101, market_value:202, unrealized_pl:2, unrealized_pl_pct:1, stop_price:98.5, take_price:103, distance_sl_pct:2.4752, distance_tp_pct:1.9802, opened_at:'2026-09-28T10:00:00Z', strategy:'trend', origin:'motor autónomo', status:'PROTEGIDA'}},
          signals: [], positions: [], orders: [], audit: []
        })});
      });
      await page.goto('http://zar.test/');
      await page.evaluate(() => showStonks());
      await page.waitForTimeout(800);
      async function checkLayout() {
        const result = await page.evaluate(() => {
          const root = document.getElementById('zarStonksApp');
          const dock = document.getElementById('zsChatDock');
          const workspace = root.querySelector('.zsWorkspace');
          const footer = root.querySelector('.zsBottom');
          const rect = el => { const r = el.getBoundingClientRect(); return {width: r.width, height: r.height, top: r.top, bottom: r.bottom}; };
          const visible = el => { const s = getComputedStyle(el), r = rect(el); return s.display !== 'none' && s.visibility === 'visible' && Number(s.opacity) > 0 && r.width > 0 && r.height > 0; };
          const ids = [...document.querySelectorAll('[id]')].map(e => e.id);
          return {
            children: [...root.children].map(e => e.className),
            duplicates: ids.filter((id, i) => ids.indexOf(id) !== i),
            visible: [root, workspace, root.querySelector('.zsMain'), dock, footer, root.querySelector('.zsTabPanel.active')].every(visible),
            root: rect(root), workspace: rect(workspace), dock: rect(dock), footer: rect(footer),
            dockInside: dock.parentElement === root,
            riskInside: root.querySelector('#zsRiskStatus').closest('section')?.id
          };
        });
        assert.deepEqual(result.duplicates, []);
        assert.equal(result.visible, true, JSON.stringify(result));
        assert.equal(result.dockInside, true);
        assert.equal(result.riskInside, 'zsTab-risk');
        assert.ok(result.root.width > 300);
        assert.ok(result.workspace.bottom <= result.dock.top + 1, JSON.stringify(result));
        assert.ok(result.dock.bottom <= result.footer.top + 1);
        assert.ok(result.footer.bottom <= result.root.bottom + 1);
      }
      await checkLayout();
      if(viewport.width<720){
        // Existing 460px window minimum exceeds narrow phones (already in 31.3.17).
        // Validate the new table's containment and DOM here, not pointer reachability.
        await page.evaluate(()=>zsTab('risk',null));
        await checkLayout();
        assert.equal(await page.locator('#zsManagedPositionsBody td').count(),15);
        assert.equal(await page.locator('#zsManagedPositionsBody').evaluate(e=>getComputedStyle(e.closest('.zsPortfolioTableWrap')).overflowX),'auto');
        await page.evaluate(()=>zsToggleChat());
        await checkLayout();
        assert.deepEqual(errors,[]);
        console.log('PASS: 390x844 table/DOM/chat layout; existing narrow-phone pointer limitation remains');
        await page.close();continue;
      }
      await page.locator('.zsChatToggle').click();
      await checkLayout();
      assert.equal(await page.locator('#zsChatHistory').isVisible(), true);
      await page.locator('.zsChatToggle').click();
      assert.equal(await page.locator('#zsChatHistory').isVisible(), false);
      await page.evaluate(() => zsTab('risk', document.querySelector('[data-zstab="risk"]')));
      await checkLayout();
      assert.equal(await page.locator('#zsManagedPositionsBody tr').count(), 1);
      assert.match(await page.locator('#zsManagedPositionsBody').textContent(), /AAPL.*LONG.*PROTEGIDA/);
      const stable = await page.evaluate(async () => {
        const row=document.querySelector('#zsManagedPositionsBody tr');
        await zsRefreshStatus();
        return row===document.querySelector('#zsManagedPositionsBody tr');
      });
      assert.equal(stable,true,'Sync must update cells without replacing rows or reloading');
      for(const status of ['ABIERTA','CERRANDO_SL','CERRANDO_TP','CERRADA','ERROR']){
        await page.evaluate(status=>zsRenderManagedPositions({AAPL:{symbol:'AAPL',direction:'SHORT',client_order_id:'zar-e-test',status,strategy:'<script>bad</script>'}}),status);
        assert.match(await page.locator('#zsManagedPositionsBody').textContent(),new RegExp(status));
        assert.equal(await page.locator('#zsManagedPositionsBody script').count(),0);
      }
      await page.evaluate(()=>zsRefreshStatus());
      assert.equal(await page.locator('#stonksStopLoss').inputValue(), '1.5');
      assert.equal(await page.locator('#stonksTakeProfit').inputValue(), '3');
      assert.equal(await page.locator('#stonksLifecycleEnabled').inputValue(), '1');
      assert.equal(await page.locator('#zsLifecycleBadge').textContent(), 'ACTIVA');
      await page.evaluate(() => { window.testSave = saveStonksControls(); });
      await page.locator('#zsConfirmPrimaryBtn').click();
      await page.evaluate(() => window.testSave);
      const saved = JSON.parse(requests.find(r => r.path === '/api/stonks/controls' && r.method === 'POST').body);
      assert.equal(saved.position_lifecycle_enabled, true);
      assert.equal(saved.stop_loss_pct, 1.5);
      assert.equal(saved.take_profit_pct, 3);
      await page.locator('.zsCloseBtn').click();
      assert.equal(await page.locator('#panel').isVisible(), false);
      assert.equal(await page.evaluate(() => zsLiveSyncTimer), null);
      await page.evaluate(() => showStonks());
      await page.waitForTimeout(100);
      await checkLayout();
      assert.notEqual(await page.evaluate(() => zsLiveSyncTimer), null);
      assert.deepEqual(errors, []);
      console.log(`PASS: ${viewport.width}x${viewport.height}: layout, IDs, chat, Risk/Position Management save, close/reopen, sync, no JS errors`);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
