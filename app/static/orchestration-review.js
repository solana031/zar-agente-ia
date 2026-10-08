/* Presentation of existing state; never creates agents, transactions or edges. */
(()=>{
 const esc=x=>String(x??'No disponible').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let loading=false,metrics=null,lastStats='';
 async function decorate(){
  const root=document.getElementById('orchestrationWorkspaceInner');
  if(!root||document.getElementById('orchestrationWorkspace')?.hidden)return;
  const graph=window.__zoState;if(graph){const signature=JSON.stringify([graph.agents,metrics]);if(signature!==lastStats||document.getElementById('zoStats')?.children.length!==7){lastStats=signature;const rows=graph.agents||[],stats=document.getElementById('zoStats');if(stats)stats.innerHTML=[['AGENTES',rows.length],['ACTIVOS',rows.filter(a=>/^(ACTIVE|RUNNING|PRODUCING)$/i.test(a.status||'')).length],['TAREAS',new Set(rows.flatMap(a=>a.task||[])).size],['ERRORES',rows.filter(a=>/ERROR|FAILED/.test(a.status||'')||a.errors?.length).length],['COSTE HOY','No verificado'],['INGRESOS',metrics?.revenue_collected??'No disponible'],['PAPER P&L','Consultar Stonks']].map(([k,v])=>'<div class="zoStat"><small>'+k+'</small><b>'+esc(v)+'</b></div>').join('');}}
  let debug=root.querySelector('#zoDebug');
  if(!debug){debug=document.createElement('details');debug.id='zoDebug';debug.className='workspaceCard';debug.innerHTML='<summary>Debug y controles avanzados</summary>';root.append(debug);}
  for(const id of ['zarBusinessControl','zarBusinessWorkflows','zarIdentityCenter','zarCommerceAgency']){const e=root.querySelector('#'+id);if(e&&e.parentElement!==debug)debug.append(e);}
  let holdings=root.querySelector('#zoHoldings');
  if(!holdings){holdings=document.createElement('section');holdings.id='zoHoldings';holdings.className='workspaceCard';holdings.innerHTML='<h2>Holdings</h2><div>Cargando métricas…</div>';root.querySelector('.zoTimeline')?.before(holdings);}
  if(loading||holdings.dataset.loaded)return;loading=true;
  try{const r=await fetch('/api/holdings/state',{cache:'no-store'}),j=await r.json();if(!r.ok||!j.ok)throw Error('No disponibles');metrics=j.totals||null;holdings.innerHTML='<h2>Holdings</h2><div class="zoHoldingGrid">'+Object.entries(j.companies||{}).map(([id,c])=>{const m=c.metrics||{};return '<article><h3>'+esc(c.name||id)+'</h3><p>'+esc(c.state)+'</p><dl>'+[['Ingresos',m.revenue_collected],['Costes',m.costs],['Beneficio',m.profit_realized],['Tareas',c.tasks?.length]].map(([k,v])=>'<dt>'+k+'</dt><dd>'+esc(v)+'</dd>').join('')+'</dl><button class="zoBtn" data-open-holdings>ABRIR</button></article>';}).join('')+'</div>';holdings.dataset.loaded='1';}catch(e){holdings.dataset.loaded='error';holdings.innerHTML='<h2>Holdings</h2><p>Métricas no disponibles. Actualiza para consultar.</p>';}finally{loading=false;}
 }
 document.addEventListener('click',e=>{
  if(e.target.closest('[data-open-holdings]')){window.exitSubagentOrchestration();window.showHoldings();return;}
  const node=e.target.closest('.zoNode[data-agent]');if(!node)return;
  const a=(window.ZarClusters?.project(window.__zoState||{})?.agents||window.__zoState?.agents||[]).find(x=>x.id===node.dataset.agent);if(!a)return;
  let panel=document.getElementById('zoInspector');if(!panel){panel=document.createElement('section');panel.id='zoInspector';panel.className='workspaceCard';document.querySelector('.zoTimeline')?.before(panel);}
  const children=(window.__zoState.agents||[]).filter(x=>x.parent===a.id).map(x=>x.name);
  panel.innerHTML='<h2>'+esc(a.name)+'</h2><dl>'+[['Estado',a.status],['Padre',a.parent],['Hijos',children.join(', ')||'Ninguno'],['Capacidades',Array.isArray(a.capabilities)?a.capabilities.join(', '):a.role],['Tarea',a.task?.join(', ')],['Última actividad',a.heartbeat],['Health',a.health],['Coste',a.cost],['Errores',a.errors?.join(', ')]].map(([k,v])=>'<dt>'+k+'</dt><dd>'+esc(v)+'</dd>').join('')+'</dl>';
  document.getElementById('zoNodeDetail')?.remove();
 });
 new MutationObserver(()=>{if(document.getElementById('orchestrationWorkspaceInner'))decorate();}).observe(document.body,{childList:true,subtree:true});
})();
