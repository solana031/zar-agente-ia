/* Controls use the existing orchestration workspace and scoped Holdings store. */
(() => {
  let csrf = '', state;
  const esc = x => String(x ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pre = x => `<pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(x,null,2))}</pre>`;
  async function action(name, data) {
    const started=document.getElementById('zarBusinessControl'),revision=started?.dataset.editRevision||'0';
    const r = await fetch('/api/holdings/orchestration/'+name, {method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify(data)});
    const j = await r.json(); if (!r.ok || !j.ok) throw Error(j.error || 'Error');
    const host=document.getElementById('zarBusinessControl');if(host && (host.dataset.editRevision||'0')===revision)delete host.dataset.editing;
    await refresh();
  }
  async function refresh() {
    const workspace = document.getElementById('orchestrationWorkspaceInner');
    if (!workspace || document.getElementById('orchestrationWorkspace')?.hidden) return;
    let host = document.getElementById('zarBusinessControl');
    if (!host) {host=document.createElement('section');host.id='zarBusinessControl';host.className='workspaceCard';workspace.prepend(host);}
    try {
      const r=await fetch('/api/holdings/orchestration',{cache:'no-store'}),j=await r.json();
      if(!r.ok || !j.ok) throw Error(j.error || 'No disponible');
      csrf=j.csrf;state=j;
      if(host.dataset.editing)return;
      host.innerHTML=`<h2>BusinessOrchestrator · Control de negocios</h2><p>CommerceOrchestrator · AgencyOrchestrator · SitesOrchestrator · MediaOrchestrator / DramaClaw. JEV: Decision Layer. Automaton: trading independiente.</p><p>Modo ${esc(j.mode)} · ciclos ${esc(j.cycles)} · último heartbeat ${esc(j.last_heartbeat)} · ${j.global_stop?'STOP GLOBAL':'Disponible'}</p>
      <div>${['OFF','SHADOW','SUPERVISED','ACTIVE'].map(mode=>`<button class="zoBtn" data-mode="${mode}">${mode}</button>`).join('')}<button class="zoBtn" data-refresh>Actualizar</button></div>
      <p>Ejecutores locales: contabilidad, revisión de rentabilidad e inventario. ACTIVE conserva aprobación económica; esta consola no ejecuta pagos.</p>
      <details open><summary>WALLET · ${esc(j.wallet.state)} · Banco ${esc(j.wallet.bank_state)}</summary><p>${esc(j.wallet.note)}</p>${pre(j.wallet.balances)}
      <form data-funding><label>Aportación declarada <input name="amount" type="number" min="0.01" step="0.01" required></label><label>Moneda <input name="currency" value="EUR" maxlength="3" required></label><label>Referencia única <input name="reference" required maxlength="100"></label><button class="zoBtn">Registrar</button></form></details>
      <details open><summary>AGENTES</summary>${Object.values(j.agents).map(a=>`<article><b>${esc(a.name)}</b> · ${esc(a.state)} · ${esc(a.function)} · completadas ${a.completed_tasks.length}<div>${['IDLE','PAUSED','OFF'].map(s=>`<button class="zoBtn" data-agent="${esc(a.id)}" data-state="${s}">${s}</button>`).join('')}<button class="zoBtn" data-task="${esc(a.id)}">Asignar ${esc(a.tools[0])}</button></div></article>`).join('')}</details>
      <details><summary>TAREAS · ${j.tasks.length}</summary>${j.tasks.map(t=>`<p>${esc(t.agent)} · ${esc(t.tool)} · ${esc(t.state)} · intentos ${t.attempts}${t.state==='ERROR'?` <button class="zoBtn" data-retry="${esc(t.id)}">Reintentar</button>`:''}</p>${pre(t.result || t.error)}`).join('') || 'Sin tareas'}</details>
      <details><summary>APROBACIONES · Propuestas contables</summary><p>La aprobación reserva saldo; hace falta un checkout verificable para ejecutar la compra.</p>
      <form data-proposal><input name="item" placeholder="Qué se compra" required><input name="provider" placeholder="Proveedor" required><input name="price" type="number" step="0.01" min="0.01" placeholder="Precio" required><input name="tax" type="number" step="0.01" min="0" placeholder="Impuestos si se conocen"><input name="currency" value="EUR" maxlength="3" required><button class="zoBtn">Preparar</button></form>
      ${j.approvals.map(p=>`<article>${pre(p)}${p.state==='PENDING'?`<button class="zoBtn" data-approve="${esc(p.id)}">Revisar y reservar</button>`:''}${['PENDING','APPROVED'].includes(p.state)?`<button class="zoBtn" data-cancel="${esc(p.id)}">Cancelar</button>`:''}</article>`).join('')}</details>
      <details><summary>CUENTAS · Inventario empresarial</summary><p>Guardar metadatos y nombres de variables. Configura los valores secretos exclusivamente en el servidor. Este inventario no crea cuentas ni inicia sesión.</p>
      <form data-account><select name="type"><option>EMAIL</option><option>GOOGLE</option><option>SHOPIFY</option><option>STRIPE</option><option>YOUTUBE</option><option>INSTAGRAM</option><option>TIKTOK</option><option>ADSENSE</option><option>VERCEL</option><option>SUPPLIER</option><option>DOMAIN</option><option>PHONE</option><option>OTHER</option></select><input name="provider" placeholder="Proveedor" required><input name="identity" placeholder="Email / identidad pública" required><input name="secret_ref" placeholder="NOMBRE_VARIABLE_SECRETA"><select name="human_step"><option value="">Sin paso humano indicado</option>${['CAPTCHA','SMS','KYC','TERMS','HUMAN_VERIFICATION'].map(x=>`<option>${x}</option>`).join('')}</select><button class="zoBtn">Guardar cuenta</button></form>${pre(j.accounts)}</details>
      <details open><summary>NODOS · Configurar / verificar</summary>${['TRADING','COMMERCE','MEDIA','ADS','PAYMENTS','GOOGLE','IDENTITY','SOCIAL','INFRA'].map(group=>`<details open><summary>${group}</summary>${j.connectors.filter(n=>(n.group||'INFRA')===group).map(n=>`<article style="border-bottom:1px solid #334;padding:10px 0"><b>${esc(n.name)}</b> · ${esc(n.status||n.state)}<p>Capacidades: ${esc((n.capabilities||[]).join(', '))}</p><p>Proveedor: ${esc(n.provider||n.name)} · Verificado: ${esc(n.last_verified||n.verified_at)} · Falta: ${esc((n.missing_requirements||n.missing).join(', ')||(n.state==='LISTO'?'Sin requisitos pendientes':'Verificación real'))}</p><details><summary>CONFIGURAR ${esc(n.name)}</summary><p>${esc(n.next_step)}</p>${(n.configuration||[]).map(c=>`<p><b>${esc(c.variable)}</b><br>Valor esperado: ${esc(c.expected)}<br>Dónde obtenerlo: ${c.obtain_at?.startsWith('https://')?`<a href="${esc(c.obtain_at)}" target="_blank" rel="noopener">Proveedor</a>`:esc(c.obtain_at)}<br>Dónde pegarlo: ${esc(c.paste_at)}</p>`).join('')||`<p>${esc(n.next_step)}</p>`}${n.name==='ZAR Mail'?'<a href="/connect/google?force=1">Conectar Google / Gmail</a>':''}</details>${n.verify?`<button class="zoBtn" data-verify-node="${esc(n.name)}">VERIFICAR</button>`:'<p>NO DISPONIBLE: verificación automática todavía no implementada; usar el control del módulo.</p>'}</article>`).join('')}</details>`).join('')}</details>
      <details><summary>INGRESOS / GASTOS · Ledger</summary>${pre(j.ledger)}</details><details><summary>ACTIVIDAD · Decisiones de control</summary>${pre(j.decisions.slice(-20).reverse())}</details><p id="zarBusinessNotice" role="status"></p>`;
    } catch(e) {host.textContent='Control de negocios: '+e.message;}
  }
  document.addEventListener('click',async event=>{
    const b=event.target.closest('#zarBusinessControl button');if(!b || b.closest('form'))return;
    try {
      if(b.dataset.verifyNode){const node=state.connectors.find(n=>n.name===b.dataset.verifyNode);const r=await fetch(node.verify.path,{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify(node.verify.action?{name:node.verify.action}:{})});const j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||'No verificado');await refresh();}
      else if(b.hasAttribute('data-refresh'))await refresh();
      else if(b.dataset.mode)await action('mode',{mode:b.dataset.mode});
      else if(b.dataset.agent)await action('agent',{id:b.dataset.agent,state:b.dataset.state});
      else if(b.dataset.task)await action('task',{agent:b.dataset.task,tool:state.agents[b.dataset.task].tools[0],request_id:crypto.randomUUID()});
      else if(b.dataset.retry)await action('retry',{id:b.dataset.retry});
      else if(b.dataset.cancel)await action('cancel',{id:b.dataset.cancel});
      else if(b.dataset.approve){const p=state.approvals.find(x=>x.id===b.dataset.approve),before=Number(state.wallet.balances[p.currency]?.available || 0);
        if(confirm(`QUÉ: ${p.item}\nPROVEEDOR: ${p.provider}\nPRECIO: ${p.price} ${p.currency}\nIMPUESTOS: ${p.tax ?? 'Desconocidos; total provisional'}\nTOTAL PROPUESTO: ${p.total}\nSALDO ANTES: ${before}\nSALDO DESPUÉS: ${(before-Number(p.total)).toFixed(2)}\nReservar fondos contables, sin enviar dinero.`)) await action('approve',{id:p.id,total:p.total,confirmed:true});}
    }catch(e){document.getElementById('zarBusinessNotice').textContent=e.message;}
  });
  document.addEventListener('submit',async event=>{
    const f=event.target;if(!f.matches('#zarBusinessControl form'))return;event.preventDefault();
    const data=Object.fromEntries(new FormData(f));if(f.hasAttribute('data-proposal'))data.tax=data.tax===''?null:data.tax;
    try{await action(f.hasAttribute('data-account')?'account':f.hasAttribute('data-funding')?'deposit':'prepare',data);}catch(e){document.getElementById('zarBusinessNotice').textContent=e.message;}
  });
  document.addEventListener('input',event=>{if(event.target.closest('#zarBusinessControl form')){const host=document.getElementById('zarBusinessControl');host.dataset.editing='true';host.dataset.editRevision=String(Number(host.dataset.editRevision||0)+1);}});
  window.zarBusinessRefresh=refresh;
})();
