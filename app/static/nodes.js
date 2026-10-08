/* Node administration never receives or displays a worker token. */
(() => {
  let csrf = '', busy = false;
  const esc = value => String(value ?? '—').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const age = seconds => `${Math.max(0, Math.round(seconds || 0))} s`;
  async function refresh() {
    const host = document.getElementById('zarNodesCards');
    if (!host || busy) return;
    busy = true;
    try {
      const response = await fetch('/api/nodes', {cache:'no-store', credentials:'same-origin'});
      if (!response.ok) throw new Error(response.status === 403 ? 'Acceso a nodos pendiente de autorización del administrador.' : 'No se pudo consultar el coordinador.');
      const data = await response.json(); csrf = data.csrf;
      if (!host.isConnected) return;
      host.innerHTML = data.nodes.length ? data.nodes.map(node => {
        const resource = node.resources || {}, job = node.current_job;
        return `<article class="zarNodeCard"><header><b>${esc(node.name)}</b><span class="zarNodeState" data-state="${esc(node.state)}">● ${esc(node.state)}</span></header>
        <dl><dt>CPU</dt><dd>${esc(resource.cpu_count)} núcleos · carga ${esc(resource.load?.[0])}</dd><dt>RAM</dt><dd>${resource.ram_bytes ? (resource.ram_bytes / 1073741824).toFixed(1) + ' GiB' : '—'}</dd><dt>Jobs</dt><dd>${esc(node.jobs)}</dd><dt>Uptime</dt><dd>${age(node.uptime)}</dd><dt>Last heartbeat</dt><dd>${node.last_seen ? age(Date.now()/1000-node.last_seen)+' atrás' : 'Pendiente'}</dd><dt>Sistema</dt><dd>${esc(resource.os)} / ${esc(resource.architecture)}</dd><dt>Versión</dt><dd>ZAR ${esc(node.version)} · worker ${esc(node.worker_version)}</dd></dl>
        <div class="zarNodeCapabilities">${(node.capabilities || []).map(cap => `<span>${esc(cap)}</span>`).join('')}</div>
        <p>Job actual: ${job ? esc(job.kind)+' · '+esc(job.state) : '—'}</p><label>Progreso <progress max="100" value="${Number(job?.progress) || 0}"></progress> ${Number(job?.progress) || 0}%</label>
        <details><summary>Último resultado</summary><pre>${esc(JSON.stringify(node.last_result ?? null,null,2))}</pre></details><p>Último error: ${esc(node.last_error)}</p>
        <div class="zarNodeActions">${['pause','resume','revoke'].map((action,i) => `<button class="zhBtn" data-node="${esc(node.id)}" data-action="${action}" ${node.state === 'REVOKED' ? 'disabled' : ''}>${['PAUSAR','REANUDAR','REVOCAR'][i]}</button>`).join('')}</div></article>`;
      }).join('') : '<p>No hay nodos enrolados.</p>';
      document.getElementById('zarNodesNotice').textContent = '';
    } catch (error) {
      const notice = document.getElementById('zarNodesNotice');
      if (notice) notice.textContent = error.message;
    } finally { busy = false; }
  }
  document.addEventListener('click', async event => {
    const button = event.target.closest('#zarNodesCards button[data-action]');
    if (!button || button.disabled) return;
    if (button.dataset.action === 'revoke' && !await ZarUI.confirm('¿Revocar este nodo? Su token dejará de permitir la conexión.')) return;
    button.disabled = true;
    try {
      const response = await fetch(`/api/nodes/${encodeURIComponent(button.dataset.node)}/${button.dataset.action}`, {method:'POST', credentials:'same-origin', headers:{'X-ZAR-Nodes-CSRF':csrf}});
      if (!response.ok) throw new Error('No se pudo cambiar el estado del nodo.');
      await refresh();
    } catch (error) { const notice = document.getElementById('zarNodesNotice'); if (notice) notice.textContent = error.message; }
    finally { if (button.isConnected) button.disabled = false; }
  });
  window.zarNodesRefresh = refresh;
})();
