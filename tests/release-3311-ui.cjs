// Reuse the focused regression harness and add cluster/SRT surface checks.
const fs=require('node:fs'),Module=require('node:module');
let source=fs.readFileSync(__dirname+'/release-3310-ui.cjs','utf8');
source=source.replace("if(path==='/api/holdings/orchestration')","if(path==='/api/subagents/view')return route.fulfill({json:{ok:true,csrf:'fixture',view:{zoom:.7,pan_x:0,pan_y:0,collapsed:[]}}});if(path==='/api/holdings/orchestration')");
const checks=`
 await page.getByRole('button',{name:'COLLAPSE Media',exact:true}).waitFor();
 const graph={agents:[{id:'zar_supervisor',name:'ZAR',domain:'core'},{id:'MediaOrchestrator',name:'Media',domain:'media'},{id:'child1',name:'Visual',domain:'media',status:'RUNNING'},{id:'child2',name:'Audio',domain:'media',status:'FAILED'},{id:'outside',name:'Shop',domain:'commerce'}],edges:[['zar_supervisor','MediaOrchestrator'],['MediaOrchestrator','child1'],['child1','outside']]};
 await page.evaluate(g=>{window.__zoState=g;zoRender(g);zoSetZoom(.7,false);},graph);
 const zoom=await page.evaluate(()=>zoViewState().zoom);
 await page.getByRole('button',{name:'COLLAPSE Media',exact:true}).click();
 await page.locator('[data-agent="cluster:Media"]').waitFor();
 assert.equal(await page.locator('[data-agent="child1"]').count(),0);
 assert.match(await page.locator('[data-agent="cluster:Media"]').innerText(),/3 agents.*1 active.*1 error/);
 assert.ok(await page.locator('#zoEdges [data-from="cluster:Media"][data-to="outside"]').count());
 assert.equal(await page.evaluate(()=>zoViewState().zoom),zoom);
 assert.ok((await page.evaluate(()=>ZarClusters.state())).includes('Media'));
 await page.getByRole('button',{name:'EXPAND Media',exact:true}).click();
 await page.locator('[data-agent="child1"]').waitFor();
 assert.equal(await page.locator('[data-agent="cluster:Media"]').count(),0);
 assert.equal(await page.evaluate(()=>zoViewState().zoom),zoom);
 await page.evaluate(()=>{ZarClusters.restore(['TRADING']);});
 assert.deepEqual(await page.evaluate(()=>ZarClusters.state()),['TRADING']);
 assert.equal(await page.getByRole('button',{name:'EXPAND TRADING',exact:true}).getAttribute('aria-expanded'),'false');
 await page.evaluate(()=>ZarClusters.restore([]));
`;
source=source.replace('await page.evaluate(()=>exitSubagentOrchestration());',checks+'await page.evaluate(()=>exitSubagentOrchestration());');
source=source.replace('PASS 3310 UI','PASS 3311 UI');
const harness=new Module(__filename,module);harness.filename=__filename;harness.paths=module.paths;harness._compile(source,__filename);
