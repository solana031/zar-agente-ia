/* Graph projection only: never creates agents or inferred edges. */
(()=>{
 const domains=['BUSINESS','INTELLIGENCE','IDENTITY','TRADING'];
 const group=a=>a.domain==='finance'?'TRADING':/semantic|sourceverif|research|artifact|jev|report|spreadsheet|presentation|chart/i.test(a.id+' '+a.name+' '+a.domain)?'INTELLIGENCE':/identity|google|gmail|mail|social|contact|account|provision/i.test(a.id+' '+a.name+' '+a.domain)?'IDENTITY':'BUSINESS';
 const sub=a=>({commerce:'Commerce',web_agency:'Agency',media:'Media',sites:'Sites',finance:'Automaton'})[a.domain];
 let collapsed=new Set();
 function project(j){
  const buckets=new Map(),alias=new Map(),agents=[];
  for(const a of j.agents||[]){if(['zar_supervisor','stonks_supervisor'].includes(a.id)){agents.push(a);continue;}const g=group(a),s=sub(a),key=collapsed.has(g)?g:s&&collapsed.has(s)?s:null;if(!key){agents.push(a);continue;}if(!buckets.has(key))buckets.set(key,[]);buckets.get(key).push(a);alias.set(a.id,'cluster:'+key);}
  for(const [key,rows] of buckets){const active=rows.filter(a=>/running|active|producing/i.test(a.status||'')).length,errors=rows.filter(a=>/error|failed/i.test(a.status||'')||a.errors?.length).length;agents.push({id:'cluster:'+key,name:key,domain:rows[0].domain,type:'orchestrator',status:errors?'ERROR':active?'ACTIVE':'IDLE',role:`${rows.length} agents · ${active} active · ${errors} error`,cluster:key});}
  const seen=new Set(),edges=[];for(const e of j.edges||[]){const from=alias.get(e[0])||e[0],to=alias.get(e[1])||e[1],key=from+'|'+to;if(from!==to&&!seen.has(key)){seen.add(key);edges.push([from,to]);}}
  return {...j,agents,edges};
 }
 function controls(){const tools=document.querySelector('.zoToolbar');if(!tools||tools.querySelector('[data-cluster-controls]'))return;const box=document.createElement('span');box.dataset.clusterControls='';for(const name of [...domains,'Commerce','Agency','Media','Automaton','Sites']){const b=document.createElement('button');b.className='zoBtn';b.dataset.cluster=name;b.onclick=()=>{collapsed.has(name)?collapsed.delete(name):collapsed.add(name);window.zoPersistClusters?.();if(window.__zoState)window.zoRender(window.__zoState);update();};box.append(b);}tools.append(box);update();}
 function update(){document.querySelectorAll('[data-cluster]').forEach(b=>{b.textContent=(collapsed.has(b.dataset.cluster)?'EXPAND ':'COLLAPSE ')+b.dataset.cluster;b.disabled=!window.zoViewState?.().loaded;b.setAttribute('aria-expanded',String(!collapsed.has(b.dataset.cluster)));});}
 window.ZarClusters={project,restore:rows=>{collapsed=new Set((rows||[]).filter(x=>[...domains,'Commerce','Agency','Media','Automaton','Sites'].includes(x)));update();},state:()=>[...collapsed],controls};
 new MutationObserver(controls).observe(document.body,{childList:true,subtree:true});controls();
})();
