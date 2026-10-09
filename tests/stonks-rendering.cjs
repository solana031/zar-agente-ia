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
  assert.equal(fs.readFileSync(file, 'utf8').trim(), '33.3.22');
}
console.log(`PASS: ${scripts} inline scripts, static JavaScript and three version files`);
(async () => {
  const browser = await chromium.launch({headless: true,
    ...(process.env.ZAR_TEST_BROWSER ? {executablePath: process.env.ZAR_TEST_BROWSER} : {})});
  try {
    for (const viewport of [{width: 1920, height: 1080}, {width: 1440, height: 900}, {width: 360, height: 800}, {width: 390, height: 844}, {width: 412, height: 915}, {width: 430, height: 932}, {width: 768, height: 1024}]) {
      const page = await browser.newPage({viewport});
      const errors = [], requests = [];
      let controlledReady=false, testSnapshot={active:false,status:'SIN_PRUEBA',steps:[],can_close:false};
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => {
        const request = route.request(), url = new URL(request.url());
        requests.push({path: url.pathname, method: request.method(), body: request.postData()});
        if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: html});
        // Component regression keeps the original Stonks controls/close cycle.
        // Real tab integration is covered separately by workspace-tabs-3318.cjs.
        if (url.pathname === '/static/workspace-tabs.js') return route.fulfill({contentType:'application/javascript',body:''});
        if(url.pathname==='/api/stonks/lifecycle-test/preflight'){
          return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,preflight:{
            status:controlledReady?'READY':'BLOCKED',symbol:url.searchParams.get('symbol'),
            checked_at:new Date().toISOString(),market_open:controlledReady,
            checks:[{code:'MOCK_ACCOUNT',label:'Cuenta simulada',status:controlledReady?'PASS':'BLOCKED'}]
          }})});
        }
        if(url.pathname==='/api/stonks/lifecycle-test/start'){
          testSnapshot={id:'zar-e-ui-test',symbol:'AAPL',active:true,status:'ESPERANDO_FILL',can_close:false,steps:[{event:'TEST_LIFECYCLE_STARTED'},{event:'TEST_ENTRY_REQUESTED'}]};
          return route.fulfill({status:202,contentType:'application/json',body:JSON.stringify({ok:true,paper:true,lifecycle_test:testSnapshot})});
        }
        if(url.pathname==='/api/stonks/lifecycle-test/close'){
          testSnapshot={...testSnapshot,status:'ESPERANDO_CIERRE',can_close:false,steps:[...testSnapshot.steps,{event:'TEST_CLOSE_REQUESTED'}]};
          return route.fulfill({status:202,contentType:'application/json',body:JSON.stringify({ok:true,paper:true,lifecycle_test:testSnapshot})});
        }

        if (url.pathname === '/static/zar-silhouette.png') return route.fulfill({contentType:'image/png',body:fs.readFileSync('app/static/zar-silhouette.png')});
        if (['/static/ui-polish.css','/static/ui-polish.js','/static/nodes.css','/static/nodes.js','/static/business-orchestration.js','/static/business-workflows.js','/static/commerce-agency.js','/static/trading-capital.js','/static/identity-provisioning.js'].includes(url.pathname)) return route.fulfill({contentType:url.pathname.endsWith('.css')?'text/css':'application/javascript',body:fs.readFileSync('app'+url.pathname)});
        if (url.pathname.startsWith('/static/') && /\.(js|css)$/.test(url.pathname) && fs.existsSync('app'+url.pathname))return route.fulfill({contentType:url.pathname.endsWith('.css')?'text/css':'application/javascript',body:fs.readFileSync('app'+url.pathname)});
        if (url.pathname === '/static/skills.js') return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync('app/static/skills.js', 'utf8')});
        return route.fulfill({contentType: 'application/json', body: JSON.stringify({
          ok: true, paused: !controlledReady, revoked: false, mode: 'paper', execution_mode: controlledReady?'paper_auto':'decision',
          paper_connected:controlledReady,engine_owned_by_current_user:true,lifecycle_test:testSnapshot,
          autonomous_engine: true, paper_configured: true, position_lifecycle_enabled: true,
          stop_loss_pct: 1.5, take_profit_pct: 3, managed_position_count: 2,
          managed_positions: {AAPL: {symbol:'AAPL', client_order_id:'zar-e-test', direction:'LONG', qty:'2', entry_price:100, current_price:101, market_value:202, unrealized_pl:2, unrealized_pl_pct:1, stop_price:98.5, take_price:103, distance_sl_pct:2.4752, distance_tp_pct:1.9802, opened_at:'2026-09-28T10:00:00Z', strategy:'trend', origin:'motor autónomo', status:'PROTEGIDA'}},
          signals: [], positions: [], orders: [], audit: []
        })});
      });
      await page.goto('https://zar.test/');
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
      async function checkResponsive() {
        const issues = await page.evaluate(() => {
          const issues=[];
          const root=document.querySelector('#zarStonksApp');
          const inside=(el,label)=>{const r=el.getBoundingClientRect();if(r.left < -1 || r.right > innerWidth+1 || r.width<=0)issues.push(label+': '+JSON.stringify(r.toJSON()));};
          if(document.documentElement.scrollWidth>innerWidth)issues.push('global overflow');
          for(const selector of ['#panel','.zsTop','.zsBottom','.zsCloseBtn']){
            const el=document.querySelector(selector);inside(el,selector);
            const r=el.getBoundingClientRect();if(r.top< -1||r.bottom>innerHeight+1)issues.push(selector+' vertical overflow');
          }
          if(innerWidth<=900){
            for(const selector of ['.zsNav','.zsCard','.zsLiveCard','.zsCanvas','.zsField']){
              root.querySelectorAll(selector).forEach(el=>{if(el.getClientRects().length)inside(el,selector)});
            }
            if(getComputedStyle(document.querySelector('#chatContent .composer')).visibility!=='hidden')issues.push('main composer overlays');
            if(getComputedStyle(document.querySelector('#panel')).resize!=='none')issues.push('window resizable');
            const nav=root.querySelector('.zsNav');if(getComputedStyle(nav).overflowX!=='auto')issues.push('nav cannot scroll');
          }
          for(const table of root.querySelectorAll('table')){
            if(!table.getClientRects().length)continue;
            const wrap=table.parentElement;inside(wrap,'table wrapper');
            if(!['auto','scroll'].includes(getComputedStyle(wrap).overflowX))issues.push('table not contained');
          }
          const button=root.querySelector('.zsCloseBtn'),r=button.getBoundingClientRect();
          if(innerWidth<=900&&!button.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)))issues.push('close obstructed: '+document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.outerHTML.slice(0,400));
          return issues;
        });
        assert.deepEqual(issues,[],`${viewport.width}x${viewport.height}`);
      }
      await checkLayout();
      await checkResponsive();
      if(viewport.width<=900){
        // Exercise resize/orientation while the same window remains open.
        await page.setViewportSize({width:800,height:430});
        await checkLayout();await checkResponsive();
        await page.setViewportSize(viewport);
        await checkLayout();await checkResponsive();
        if(process.env.ZAR_TEST_SCREENSHOTS)await page.screenshot({path:`data/stonks-${viewport.width}.png`});
      }
      // Real clicks also scroll the compact horizontal navigation into view.
      for(const tab of ['strategies','orders','wallets','backtesting','risk','dashboard']){
        await page.locator(`[data-zstab="${tab}"]`).click();
        assert.equal(await page.locator(`#zsTab-${tab}`).isVisible(),true);
        assert.equal(await page.locator(`[data-zstab="${tab}"]`).evaluate(e=>e.classList.contains('active')),true);
        await checkResponsive();
      }
      await page.locator('#zsChatInput').fill('Mensaje de prueba sin enviar');
      assert.equal(await page.locator('#zsChatInput').inputValue(),'Mensaje de prueba sin enviar');
      await page.locator('.zsChatToggle').click();
      await checkLayout();
      assert.equal(await page.locator('#zsChatHistory').isVisible(), true);
      await page.locator('.zsChatToggle').click();
      assert.equal(await page.locator('#zsChatHistory').isVisible(), false);
      await page.locator('[data-zstab="risk"]').click();
      await checkLayout();
      assert.equal(await page.locator('#zsManagedPositionsBody tr').count(), 1);
      if(viewport.width<=900){
        await page.locator('#zsManagedPositionsBody td').last().evaluate(e=>{e.textContent='TEST_LIFECYCLE_'.repeat(15);e.style.whiteSpace='nowrap'});
        const wrap=page.locator('#zsManagedPositionsBody').locator('xpath=../..');
        assert.equal(await wrap.evaluate(e=>{e.scrollLeft=100;return e.scrollLeft>0}),true,'wide table scrolls locally');
        await checkResponsive();
        await page.evaluate(()=>zsRefreshStatus());
      }
      assert.match(await page.locator('#zsManagedPositionsBody').textContent(), /AAPL.*LONG.*PROTEGIDA/);
      const stable = await page.evaluate(async () => {
        const row=document.querySelector('#zsManagedPositionsBody tr');
        await zsRefreshStatus();
        return row===document.querySelector('#zsManagedPositionsBody tr');
      });
      assert.equal(stable,true,'Sync must update cells without replacing rows or reloading');
      for(const status of ['ABIERTA','CERRANDO_SL','CERRANDO_TP','CERRADA','ERROR']){
        const snapshot=await page.evaluate(status=>{
          zsRenderManagedPositions({AAPL:{symbol:'AAPL',direction:'SHORT',client_order_id:'zar-e-test',status,strategy:'<script>bad</script>'}});
          const body=document.getElementById('zsManagedPositionsBody');
          return {text:body.textContent,scripts:body.querySelectorAll('script').length};
        },status);
        assert.match(snapshot.text,new RegExp(status));
        assert.equal(snapshot.scripts,0);
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
      // Controlled Paper test UI uses server snapshots and explicit confirmation.
      assert.equal(await page.locator('#zsLifecycleTestStart').isDisabled(),true);
      controlledReady=true;
      await page.evaluate(()=>zsRefreshStatus());
      assert.equal(await page.locator('#zsLifecycleTestStart').isEnabled(),true);
      for(const flag of [{paper_connected:false},{engine_owned_by_current_user:false},{autonomous_engine:false},{mode:'live'},{position_lifecycle_enabled:false},{paused:true},{revoked:true}]){
        await page.evaluate(flag=>zsRenderLifecycleTest({...zsLifecycleTestState,...flag}),flag);
        assert.equal(await page.locator('#zsLifecycleTestStart').isDisabled(),true);
        await page.evaluate(()=>zsRefreshStatus());
      }
      await page.locator('#zsLifecycleTestStart').click();
      assert.equal(await page.locator('#zsLifecycleTestStart').isDisabled(),true);
      await page.locator('#zsConfirmPrimaryBtn').click();
      await page.waitForFunction(()=>document.getElementById('zsLifecycleTestState').textContent.includes('ESPERANDO_FILL'));
      assert.equal(await page.locator('#zsLifecycleTestClose').isDisabled(),true);
      const starts=requests.filter(r=>r.path==='/api/stonks/lifecycle-test/start');
      assert.equal(starts.length,1);
      const startPayload=JSON.parse(starts[0].body);
      assert.equal(startPayload.confirm,true);
      assert.match(startPayload.request_id,/^[0-9a-f-]{36}$/);
      testSnapshot={...testSnapshot,status:'POSICION_DETECTADA',can_close:true,steps:[...testSnapshot.steps,{event:'TEST_POSITION_DETECTED'}]};
      await page.evaluate(()=>zsRefreshStatus());
      assert.equal(await page.locator('#zsLifecycleTestClose').isEnabled(),true);
      await page.locator('#zsLifecycleTestClose').click();
      await page.locator('#zsConfirmPrimaryBtn').click();
      await page.waitForFunction(()=>document.getElementById('zsLifecycleTestState').textContent.includes('ESPERANDO_CIERRE'));
      const closes=requests.filter(r=>r.path==='/api/stonks/lifecycle-test/close');
      assert.equal(closes.length,1);
      assert.equal(JSON.parse(closes[0].body).id,'zar-e-ui-test');
      testSnapshot={...testSnapshot,active:false,status:'OK',steps:[...testSnapshot.steps,{event:'TEST_POSITION_CLOSED'},{event:'TEST_LIFECYCLE_OK'}]};
      await page.evaluate(()=>zsRefreshStatus());
      assert.equal(await page.locator('#zsLifecycleTestSteps li').count(),6);
      assert.equal(await page.locator('#zsLifecycleTestSteps li').evaluateAll(rows=>rows.every(r=>r.textContent.startsWith('✓'))),true);
      await checkLayout();
      await checkResponsive();
      await page.locator('[data-zstab="automaton"]').click();
      assert.equal(await page.locator('#zsTab-automaton').isVisible(),true);
      assert.equal(await page.locator('#zsTab-risk').isVisible(),false);
      assert.equal(await page.locator('#zsAutomatonStart').isVisible(),true);
      assert.match(await page.locator('#zsTab-automaton').innerText(),/KILL SWITCH/);
      assert.equal(await page.locator('#zsAutomatonMode option').last().evaluate(e=>e.disabled),true);
      await page.locator('.zsCloseBtn').click();
      assert.equal(await page.locator('#panel').isVisible(), false);
      assert.equal(await page.evaluate(() => StonksRealtimeBus.state().running), false);
      assert.equal(await page.locator('#chatContent .composer').evaluate(e=>getComputedStyle(e).visibility),'visible');
      await page.evaluate(() => showStonks());
      await page.waitForTimeout(100);
      await checkLayout();
      assert.equal(await page.evaluate(() => StonksRealtimeBus.state().running), true);
      assert.deepEqual(errors, []);
      console.log(`PASS: ${viewport.width}x${viewport.height}: layout, IDs, chat, Risk/Position Management save, close/reopen, sync, no JS errors`);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
