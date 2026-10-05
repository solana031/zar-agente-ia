// Official local editor, no creation/model requests or external network allowed.
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
(async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const page=await browser.newPage();const errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',r=>{
      const u=new URL(r.request().url());
      return u.origin==='http://127.0.0.1:8781'&&r.request().method()==='GET'?r.continue():r.abort();
    });
    const response=await page.goto('http://127.0.0.1:8781/');
    assert.equal(response.status(),200);
    await page.waitForSelector('#root > *',{timeout:30000});
    assert.equal(await page.locator('#root').isVisible(),true);
    assert.deepEqual(errors,[]);
    console.log('PASS official DramaClaw local editor DOM, no JS errors; GET only, no model jobs');
  } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
