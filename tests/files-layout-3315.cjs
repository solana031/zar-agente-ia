const fs=require('fs'),assert=require('assert'),{chromium}=require('playwright');
(async()=>{
const browser=await chromium.launch({headless:true,executablePath:process.env.ZAR_TEST_BROWSER});
try{for(const width of [1920,1440,1024,768,390]){
 const page=await browser.newPage({viewport:{width,height:1000}});
 const css=[...fs.readFileSync('app/templates/index.html','utf8').matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(x=>x[1]).join('\n')+fs.readFileSync('app/static/media-production.css','utf8');
 await page.setContent('<style>'+css+'</style><div class="zarFileExplorerEnhanced"><aside class="zarFileSidebar">Documentos</aside><main class="zarFileMain"><div class="zarFileToolbar"></div><div id="zarFileStats"></div><div id="zarFileList"></div></main></div>');
 await page.evaluate(()=>{window.zarFileCategory='';window.formatBytes=()=> '2 KB';window.zarFileIcon=()=> 'PDF';window.fileKind=()=> 'pdf';window.fetch=async()=>({ok:true,json:async()=>({ok:true,files:[{id:'fixture',name:'Informe de vivienda y ayudas para jóvenes de Majadahonda.pdf',size:2000,category:'documentos',mime:'application/pdf',created_at:'2026-10-09T12:00:00Z',owner_id:'fixture-owner-with-long-id',storage:'persistent',download_url:'/fixture.pdf'}]})});});
 await page.addScriptTag({content:fs.readFileSync('app/static/file-memory.js','utf8')}); await page.evaluate(()=>loadZarFiles());
 const measures=await page.locator('.zarFileReadable').evaluate(e=>{const n=e.querySelector('.zarFileName'),r=e.getBoundingClientRect();return {nameWidth:n.clientWidth,right:r.right,overflow:document.documentElement.scrollWidth>innerWidth+1,actions:[...e.querySelectorAll('.zarFileActions>button,.zarFileActions>a,.zarFileActions>details>summary')].every(b=>b.getBoundingClientRect().right<=r.right+1)};});
 assert(measures.nameWidth>=180,JSON.stringify({width,measures}));assert(!measures.overflow);assert(measures.actions);
 for(const key of ['preview','rename','move','share','delete'])assert.equal(await page.locator('[data-file-'+key+']').count(),1);
 console.log('PASS Files '+width);await page.close();
}}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
