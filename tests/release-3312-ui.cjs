// Extend the existing focused desktop/mobile harness with plan/result review.
const fs=require('node:fs'),Module=require('node:module');
let source=fs.readFileSync(__dirname+'/release-3310-ui.cjs','utf8');
const fixture=`let task={id:'aaaaaaaaaaaaaaaaaaaaaaaa',goal:'Investiga vivienda y envíamelo',plan_confirmed:false,status:'PLANNED',subtasks:[{kind:'RESEARCH',status:'PLANNED'},{kind:'CREATE_REPORT',status:'PLANNED'},{kind:'SEND_EMAIL',status:'PLANNED'}],outputs:{}};`;
source=source.replace("let conversations=",fixture+"let conversations=");
source=source.replace("if(path==='/api/holdings/orchestration')",`if(path==='/api/subagents/view')return route.fulfill({json:{ok:true,csrf:'fixture',view:{zoom:.7,pan_x:0,pan_y:0,collapsed:[]}}});
 if(path==='/api/semantic/tasks')return route.fulfill({json:{ok:true,csrf:'fixture',tasks:[task]}});
 if(path.endsWith('/confirm-plan')){task={...task,plan_confirmed:true,status:'WAITING',outputs:{RESEARCH:{text:'# Informe\\nResumen real de fixture. https://example.test/source',sources:[{title:'Fuente',url:'https://example.test/source'}]},CREATE_REPORT:{title:'Informe vivienda',type:'pdf',size:100,download_url:'/api/files/f1/download',artifact_id:'f1'},DRAFT_EMAIL:{to:'owner@example.test',subject:'Vivienda',body:'Adjunto informe'}}};return route.fulfill({json:{ok:true,task}});}
 if(path==='/api/holdings/orchestration')`);
const checks=`
 await page.evaluate(()=>ZARAddChatMessage('assistant','PLAN PROPUESTO\\n\\n[Ver plan ZAR](/?task=aaaaaaaaaaaaaaaaaaaaaaaa)'));
 await page.getByRole('button',{name:'CONFIRMAR PLAN',exact:true}).waitFor();
 assert.equal(requests.filter(r=>r.path.endsWith('/run')).length,0);
 await page.getByRole('button',{name:'CONFIRMAR PLAN',exact:true}).click();
 await page.getByRole('button',{name:'VER INFORME',exact:true}).waitFor();
 assert.equal(requests.filter(r=>r.path.endsWith('/run')).length,0);
 await page.getByRole('button',{name:'VER INFORME',exact:true}).click();
 await page.getByRole('dialog',{name:'Informe ZAR'}).waitFor();
 assert.equal(await page.locator('.zarArtifactViewer article a').getAttribute('href'),'https://example.test/source');
 await page.locator('[data-report-close]').click();
 await page.getByRole('button',{name:'REVISAR EMAIL',exact:true}).click();
 assert.equal(await page.locator('[name=to]').inputValue(),'owner@example.test');
 await page.locator('[data-zar-cancel]').click();
 assert.equal(requests.filter(r=>r.path.endsWith('/run')).length,0);
`;
source=source.replace("await page.goto('https://zar.test/');", "await page.goto('https://zar.test/');"+checks);
source=source.replace("await page.locator('#zoViewport').waitFor();",`await page.locator('#zoViewport').waitFor();assert.equal(await page.locator('.zoSceneWrap').evaluate(e=>getComputedStyle(e).resize),'none');assert.equal(await page.locator('.zoToolbar').innerText().then(t=>t.includes('mover la ventana')),false);`);
source=source.replace('PASS 3310 UI','PASS 3312 UI');
const harness=new Module(__filename,module);harness.filename=__filename;harness.paths=module.paths;harness._compile(source,__filename);
