const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
 try {
  for(const [width,height] of [[390,844],[393,852],[412,915],[768,1024],[1440,900]]){
   const page=await browser.newPage({viewport:{width,height}});
   await page.setContent(`<style>body{margin:12px;background:#15110e}*{box-sizing:border-box}${fs.readFileSync('app/static/subapp-consolidation.css','utf8')}</style><section id="zarCommerceAgency"><h2>ZAR Commerce</h2><nav><button data-ca-op="tab">BusinessOrchestrator</button><button data-ca-op="tab">Proveedores</button></nav><h3>Nichos editables</h3><form data-ca-form="commerce_product"><label>Producto<input name="name" value="Conservar producto"></label><button>Guardar candidato</button></form></section><section data-zar-media><h3>🎬 ZAR Media</h3><button data-media-action="retry">CONTINUAR / CONSULTAR IDs</button><div data-media-preview></div></section><details id="zwSites" open><summary>ZAR Sites · SiteProject / AdSense</summary><form data-form="site"><input name="name" value="Proyecto existente"><input name="language" value="es"><input name="files" type="file" multiple><button>Guardar / importar web</button></form></details><select id="zhLedgerCompany"><option value="commerce">ZAR Commerce</option><option value="media">ZAR Media</option></select>`);
   await page.addScriptTag({path:'app/static/subapp-consolidation.js'});
   await page.waitForFunction(()=>document.querySelectorAll('[data-subapp-guide]').length===3);
   assert.match(await page.locator('#zarCommerceAgency h2').innerText(),/ZAR Dropshipping/);
   assert.match(await page.locator('[data-zar-media] h3').innerText(),/ZAR Clipper/);
   assert.equal(await page.locator('input[name=name]').first().inputValue(),'Conservar producto');
   assert.equal(await page.locator('#zwSites input[name=name]').inputValue(),'Proyecto existente');
   assert.equal(await page.locator('#zhLedgerCompany option').first().getAttribute('value'),'commerce');
   assert.equal(await page.locator('#zwSites input[type=file]').getAttribute('multiple'),'');
   await page.evaluate(()=>{const p=document.createElement('p');p.textContent='Progreso actualizado';document.querySelector('[data-zar-media]').append(p)});
   await page.waitForTimeout(100);
   assert.equal(await page.locator('[data-subapp-guide]').count(),3,'Guides remain unique after updates');
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No page overflow');
   assert(await page.evaluate(()=>[...document.querySelectorAll('button')].every(el=>el.getBoundingClientRect().right<=innerWidth)),'Actions fit viewport');
   await page.close();
  }
  console.log('Subapp naming, field preservation, idempotence and five responsive viewports: PASS');
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
