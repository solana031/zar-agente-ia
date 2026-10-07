/* No timers, generation, inference or operational trading controls. */
(() => {
  'use strict';
  let csrf = '', snapshot = null;
  const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const notice = text => { const el = document.getElementById('zarIntegrationsNotice'); if (el) el.textContent = text; };
  async function post(path, body = {}) {
    const response = await fetch(path, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-ZAR-Integrations-CSRF':csrf}, body:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok || !data.ok) throw Error(data.error || 'Integración no disponible');
    return data;
  }
  window.zarIntegrationsRefresh = async () => {
    const host = document.getElementById('zarIntegrationsCards');
    if (!host) return;
    try {
      const response = await fetch('/api/integrations', {cache:'no-store'});
      const data = await response.json();
      if (!response.ok || !data.ok || !Array.isArray(data.cards)) throw Error('Inventario restringido/no disponible');
      if (host !== document.getElementById('zarIntegrationsCards')) return;
      csrf = data.csrf; snapshot = data;
      host.innerHTML = data.cards.map(card => `<article class="zarIntegrationCard"><h4>${esc(card.name)} <span>${esc(card.state)}</span></h4><dl><dt>Versión</dt><dd>${esc(card.version)}</dd><dt>Nodo</dt><dd>${esc(card.node)}</dd><dt>Capacidades</dt><dd>${esc((card.capabilities || []).join(', '))}</dd><dt>Heartbeat</dt><dd>${esc(card.last_heartbeat ? new Date(card.last_heartbeat*1000).toISOString() : 'NO VERIFICADO')}</dd><dt>Coste estimado</dt><dd>${esc(card.estimated_cost_eur == null ? 'Desconocido / gasto bloqueado' : card.estimated_cost_eur+' EUR')}</dd><dt>Falta</dt><dd>${esc((card.missing || []).join(', ') || '—')}</dd></dl>${card.probe ? `<button class="zhBtn" data-integration-probe="${esc(card.probe)}" ${card.probe==='conway' && card.mode==='OFF'?'disabled':''}>Probar conexión (sin modelos)</button>` : ''}${card.mode ? `<label>Modo <select ${card.local_controls_allowed===false?'disabled':''} data-integration-mode="${card.name==='Coding Agent'?'coding_mode':'conway_mode'}">${(card.name==='Coding Agent'?['DISABLED','READ_ONLY','PATCH','FULL']:['OFF','OBSERVE','PROPOSE','EXECUTE']).map(mode=>`<option value="${mode}" ${mode===card.mode?'selected':''} ${mode==='EXECUTE'?'disabled':''}>${mode}</option>`).join('')}</select></label>` : ''}</article>`).join('');
      const budget = document.getElementById('zarAutomationBudget');
      // Do not discard a human's pending configuration during status refresh.
      if (budget && !budget.children.length) {
        const p = data.policy;
        budget.innerHTML = `<h4>AI/Automation Budget · ${(p.monthly_cents/100).toFixed(2)} EUR automático/mes</h4><p>Costes desconocidos bloqueados. Un límite positivo no autoriza gastos ni activa proveedores.</p>${[['per_task_cents','Por tarea'],['daily_cents','Diario'],['monthly_cents','Mensual']].map(([key,label])=>`<label>${label} EUR <input type="number" min="0" step="0.01" data-budget="${key}" value="${p[key]/100}"></label>`).join('')}<label>Proveedor <select id="zarBudgetProvider">${['dramaclaw','jev','elevenlabs','codex','conway'].map(x=>`<option>${x}</option>`).join('')}</select></label><label>Límite proveedor EUR/mes <input id="zarProviderLimit" type="number" min="0" step="0.01" value="${(p.providers.dramaclaw||0)/100}"></label><button class="zhBtn" data-budget-save>Guardar límites con confirmación</button><button class="zhBtn danger" data-automation-kill>${p.kill_switch?'Rearmar controles':'Kill switch automatización'}</button>`;
      }
      notice('Estado observado. Generación e inferencia no probadas por este panel.');
    } catch (error) { notice(error.message); }
  };
  document.addEventListener('click', async event => {
    const probe = event.target.closest('[data-integration-probe]');
    const save = event.target.closest('[data-budget-save]');
    const kill = event.target.closest('[data-automation-kill]');
    if (!probe && !save && !kill) return;
    try {
      if (probe) {
        const data = await post('/api/integrations/probe/'+encodeURIComponent(probe.dataset.integrationProbe));
        notice(JSON.stringify(data.result)); return;
      }
      if (!snapshot || !confirm(kill ? '¿Cambiar el kill switch de automatización?' : '¿Guardar estos límites? No autorizan cargos desconocidos.')) return;
      let changes;
      if (kill) changes = {kill_switch: !snapshot.policy.kill_switch};
      else {
        changes = {};
        document.querySelectorAll('[data-budget]').forEach(input => { changes[input.dataset.budget] = Math.round(Number(input.value)*100); });
        changes.providers = {...snapshot.policy.providers, [document.getElementById('zarBudgetProvider').value]:Math.round(Number(document.getElementById('zarProviderLimit').value)*100)};
      }
      await post('/api/integrations/policy', {confirmed:true, changes});
      const budget = document.getElementById('zarAutomationBudget'); if (budget) budget.replaceChildren();
      await window.zarIntegrationsRefresh();
    } catch (error) { notice(error.message); }
  });
  document.addEventListener('change', async event => {
    if (event.target.id==='zarBudgetProvider' && snapshot) {
      document.getElementById('zarProviderLimit').value = (snapshot.policy.providers[event.target.value] || 0)/100; return;
    }
    const select = event.target.closest('[data-integration-mode]');
    if (!select || !snapshot) return;
    const previous = snapshot.policy[select.dataset.integrationMode];
    if (!confirm('¿Cambiar el modo local? Cada tarea Codex necesita además aprobación local. Conway EXECUTE permanece bloqueado.')) { select.value=previous; return; }
    try { await post('/api/integrations/policy', {confirmed:true, changes:{[select.dataset.integrationMode]:select.value}}); await window.zarIntegrationsRefresh(); }
    catch (error) { select.value=previous; notice(error.message); }
  });
})();
