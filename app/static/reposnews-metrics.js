/* Search traffic and monetization approval for the authenticated ReposNews owner. */
(() => {
  let csrf = '';
  let state = null;
  let busy = false;
  let timer = null;
  let error = '';
  let bootstrapping = false;
  const expanded = new Set();
  const interval = 60000;
  const hostId = 'zarReposNewsMetrics';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, character =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
  const labels = {
    READY: 'Conectado', NOT_CONNECTED: 'Conectar Google', NEEDS_PERMISSION: 'Falta permiso o acceso',
    ERROR: 'Consulta fallida', STATE_UNSPECIFIED: 'Sin verificar', NO_ACCOUNT: 'Sin cuenta AdSense',
    NEEDS_ATTENTION: 'Requiere atención', CLOSED: 'Cuenta cerrada', NOT_ADDED: 'Sitio sin vincular',
    GETTING_READY: 'En preparación / revisión', REQUIRES_REVIEW: 'Requiere revisión',
    MULTIPLE_SITE_STATES: 'Ver estados por dominio',
  };
  function stamp(value) {
    return value ? new Date(value).toLocaleString('es-ES') : 'Sin consulta completada';
  }
  function number(value, digits = 0) {
    return typeof value === 'number' && Number.isFinite(value)
      ? value.toLocaleString('es-ES', {maximumFractionDigits: digits}) : '—';
  }
  function visible() {
    const host = document.getElementById(hostId);
    if (document.hidden || !host) return false;
    return host.checkVisibility
      ? host.checkVisibility({checkVisibilityCSS: true})
      : host.getClientRects().length > 0;
  }
  function mount() {
    const summary = document.getElementById('zarReposNewsSiteSummary');
    if (!summary) return null;
    let host = document.getElementById(hostId);
    if (!host) {
      host = document.createElement('section');
      host.id = hostId;
      host.setAttribute('aria-label', 'Estadísticas y conexiones de ReposNews');
      summary.append(host);
    }
    return host;
  }
  function accountPicker(service, provider) {
    const options = (state.accounts || []).map(account =>
      '<option value="' + esc(account.id) + '" ' +
      (provider.selected_account === account.id ? 'selected' : '') + '>' +
      esc(account.email || 'Cuenta vinculada') + '</option>').join('');
    return '<label class="rn-metrics-account">Cuenta de Google<select data-rn-metrics-account="' +
      service + '"><option value="">Cuenta activa en ZAR</option>' + options +
      '</select></label><a href="' + esc(state.connect_url) +
      '" target="_blank" rel="noopener">Conectar / autorizar lectura</a>';
  }
  function availability(provider) {
    const messages = {
      NEEDS_PERMISSION: 'Autoriza el permiso de lectura y comprueba que esta cuenta tenga acceso al sitio.',
      NOT_CONNECTED: 'Conecta una cuenta de Google para consultar los datos.',
      ACCOUNT_AMBIGUOUS: 'La cuenta tiene varios editores y no se ha podido identificar el de ReposNews.',
      PUBLISHER_MISMATCH: 'El editor de esta cuenta no coincide con el configurado para ReposNews.',
    };
    const message = messages[provider.error] || (provider.status === 'ERROR'
      ? 'No se ha podido consultar Google. Puedes volver a actualizar.' : '');
    return '<p class="rn-metrics-meta">' + esc(labels[provider.status] || provider.status) +
      ' · Última consulta correcta: ' + esc(stamp(provider.checked_at)) + '</p>' +
      (provider.stale ? '<p class="rn-metrics-warning">Datos anteriores conservados. Pendiente de actualización.</p>' : '') +
      (message ? '<p role="status">' + esc(message) + '</p>' : '');
  }
  function details(key, title, content) {
    return '<details data-rn-metrics-details="' + key + '" ' + (expanded.has(key) ? 'open' : '') +
      '><summary>' + title + '</summary>' + content + '</details>';
  }
  function sparkline(rows, metric) {
    if (!rows.length) return '';
    const max = Math.max(1, ...rows.map(row => row[metric]));
    const points = rows.map((row, index) =>
      (index * 280 / Math.max(1, rows.length - 1)).toFixed(1) + ',' +
      (46 - row[metric] / max * 42).toFixed(1)).join(' ');
    return '<svg class="rn-metrics-spark" viewBox="0 0 280 50" role="img" aria-label="' +
      (metric === 'clicks' ? 'Clics diarios disponibles' : 'Impresiones diarias disponibles') +
      '"><polyline points="' + points + '" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
  }
  function metric(label, value, previous, chart = '') {
    return '<div class="rn-metrics-stat"><span>' + label + '</span><strong>' + value +
      '</strong><small>Periodo anterior: ' + number(previous) + '</small>' + chart + '</div>';
  }
  function traffic(provider) {
    const data = provider.data;
    let content = '<div class="rn-metrics-heading"><h3>Rendimiento en Google</h3>' +
      '<span>Últimos 28 días · búsqueda web</span></div>' + availability(provider);
    if (data) {
      const total = data.totals;
      content += '<p class="rn-metrics-meta">' + esc(data.start_date) + ' — ' + esc(data.end_date) +
        ' · Fechas de Google: ' + esc(data.timezone) + '</p>';
      content += '<div class="rn-metrics-stats">' +
        metric('Clics en resultados de búsqueda', number(total?.clicks), data.previous?.clicks, sparkline(data.daily, 'clicks')) +
        metric('Impresiones en resultados de búsqueda', number(total?.impressions), data.previous?.impressions, sparkline(data.daily, 'impressions')) +
        '<div class="rn-metrics-stat"><span>CTR</span><strong>' + number(total ? total.ctr * 100 : null, 2) +
        (total ? ' %' : '') + '</strong></div><div class="rn-metrics-stat"><span>Posición media</span><strong>' +
        number(total?.position, 1) + '</strong></div></div>';
      if (data.empty) content += '<p>Google no devuelve filas para este periodo.</p>';
      if (data.first_incomplete_date) {
        content += '<p class="rn-metrics-warning">Datos provisionales desde el ' +
          esc(data.first_incomplete_date) + '. Google puede revisarlos.</p>';
      }
      content += '<p class="rn-metrics-meta">Último día con datos: ' + esc(data.latest_date || 'Sin datos') +
        '. La actualización automática muestra lo último que ofrece Google, con su retraso de procesamiento.</p>';
      content += details('daily', 'Ver clics e impresiones por día',
        '<div class="rn-metrics-scroll"><table><caption>Datos diarios devueltos por Search Console</caption>' +
        '<thead><tr><th>Fecha</th><th>Clics</th><th>Impresiones</th><th>CTR</th><th>Posición</th></tr></thead><tbody>' +
        data.daily.map(row => '<tr><td>' + esc(row.date) + '</td><td>' + number(row.clicks) +
          '</td><td>' + number(row.impressions) + '</td><td>' + number(row.ctr * 100, 2) +
          ' %</td><td>' + number(row.position, 1) + '</td></tr>').join('') + '</tbody></table></div>');
      const pages = data.top_pages.filter(row => {
        try {
          const url = new URL(row.url);
          return url.protocol === 'https:' && ['reposnews.com', 'www.reposnews.com'].includes(url.host);
        } catch { return false; }
      });
      content += details('pages', 'Contenido con más clics',
        '<div class="rn-metrics-scroll"><table><thead><tr><th>Página</th><th>Clics</th><th>Impresiones</th></tr></thead><tbody>' +
        pages.map(row => '<tr><td><a href="' + esc(row.url) + '" target="_blank" rel="noopener">' +
          esc(row.title || new URL(row.url).pathname) + '</a></td><td>' + number(row.clicks) +
          '</td><td>' + number(row.impressions) + '</td></tr>').join('') +
        '</tbody></table></div><p class="rn-metrics-meta">El desglose por páginas puede diferir del total agregado del sitio.</p>');
    } else {
      content += '<div class="rn-metrics-stats">' + metric('Clics', '—', null) + metric('Impresiones', '—', null) + '</div>';
    }
    return content + accountPicker('search_console', provider);
  }
  function monetization(provider) {
    const data = provider.data;
    const siteLabels = {...labels, READY: 'Listo para mostrar anuncios'};
    const accountLabels = {...labels, READY: 'Cuenta lista para anuncios'};
    let content = '<h3>Vinculación con AdSense</h3>' + availability(provider);
    if (data) {
      content += '<dl class="rn-metrics-approval"><div><dt>Cuenta AdSense</dt><dd>' +
        esc(accountLabels[data.account_state] || data.account_state) + '</dd></div><div><dt>Aprobación de ReposNews</dt><dd>' +
        esc(siteLabels[data.site_state] || data.site_state) + '</dd></div><div><dt>Anuncios automáticos</dt><dd>' +
        (data.auto_ads_enabled === true ? 'Activados en Google' : data.auto_ads_enabled === false ? 'Desactivados en Google' : 'Sin verificar') +
        '</dd></div></dl>';
      if (data.site_state === 'NEEDS_ATTENTION' || data.account_state === 'NEEDS_ATTENTION') {
        content += '<p class="rn-metrics-warning">Google indica que requiere atención. Consulta el motivo en AdSense.</p>';
      }
      if (data.sites?.length) content += details('adsense-sites', 'Ver estados por dominio',
        data.sites.map(site => '<p>' + esc(site.domain) + ' · ' +
          esc(siteLabels[site.state] || site.state) + '</p>').join(''));
    } else {
      content += '<p>Aprobación actual del sitio: sin verificar por API.</p>';
    }
    content += '<p class="rn-metrics-meta">La conexión OAuth y la aprobación del sitio se muestran por separado. Estado leído de Google AdSense API.</p>';
    return content + accountPicker('adsense', provider) +
      '<a href="https://adsense.google.com/" target="_blank" rel="noopener">Abrir AdSense</a>';
  }
  function render() {
    const host = mount();
    if (!host) return;
    if (!state) {
      host.innerHTML = '<h3>Estadísticas y conexiones</h3><p role="status">' +
        esc(error || 'Consultando métricas de ReposNews…') + '</p>';
      return;
    }
    host.innerHTML = '<div class="rn-metrics-toolbar"><h3>Estadísticas y conexiones</h3>' +
      '<button type="button" data-rn-metrics-refresh ' + (busy ? 'disabled' : '') + '>' +
      (busy ? 'Actualizando…' : 'Actualizar ahora') + '</button></div>' +
      '<p class="rn-metrics-meta">Consulta automática mientras el panel está visible. Caché de Google de hasta 5 minutos.</p>' +
      (error ? '<p role="status">' + esc(error) + '</p>' : '') +
      '<div class="rn-metrics-block">' + traffic(state.providers.search_console) + '</div>' +
      '<div class="rn-metrics-block">' + monetization(state.providers.adsense) + '</div>';
  }
  async function post(operation, body = {}) {
    const response = await fetch('/api/holdings/workflows/reposnews_metrics_' + operation, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-ZAR-Business-CSRF': csrf},
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw Error('No se pudieron consultar las métricas. Recarga ZAR para renovar la sesión.');
    return result.result;
  }
  async function refresh(manual = false, selection = null) {
    if (!csrf || busy || !visible()) return;
    busy = true;
    error = '';
    render();
    try {
      if (!state) state = await post('view');
      const services = selection ? [selection.provider] : ['search_console', 'adsense'];
      const results = await Promise.allSettled(services.map(provider =>
        post('refresh', {provider, refresh: manual, ...(selection || {})})));
      for (let index = 0; index < results.length; index++) {
        const result = results[index];
        if (result.status === 'fulfilled') {
          // Each concurrent response may predate the other provider's completion.
          state.providers[services[index]] = result.value.providers[services[index]];
          state.accounts = result.value.accounts;
        } else error = result.reason.message;
      }
    } catch (failure) {
      error = failure.message;
    } finally {
      busy = false;
      render();
    }
  }
  async function bootstrap() {
    if (csrf || bootstrapping || !visible()) return;
    bootstrapping = true;
    try {
      const response = await fetch('/api/notifications');
      const result = response.ok ? await response.json() : null;
      if (result?.ok && result.csrf) {
        csrf = result.csrf;
        await refresh();
        schedule();
      }
    } finally {
      bootstrapping = false;
    }
  }
  function schedule() {
    if (document.hidden) {
      clearTimeout(timer);
      timer = null;
      return;
    }
    if (timer !== null) return;
    timer = setTimeout(async () => {
      timer = null;
      await refresh();
      schedule();
    }, interval);
  }
  window.addEventListener('zar-workflow-state', event => {
    csrf = event.detail.csrf;
    mount();
    if (!state) refresh();
    schedule();
  });
  window.addEventListener('zar-reposnews-summary-rendered', () => {
    render();
    if (!state) refresh();
    if (!csrf) bootstrap().catch(() => {});
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh();
    schedule();
  });
  window.addEventListener('pagehide', () => {
    clearTimeout(timer);
    timer = null;
  });
  window.addEventListener('pageshow', schedule);
  document.addEventListener('toggle', event => {
    const key = event.target.dataset?.rnMetricsDetails;
    if (!key) return;
    if (event.target.open) expanded.add(key); else expanded.delete(key);
  }, true);
  document.addEventListener('click', event => {
    if (event.target.closest('#' + hostId + ' [data-rn-metrics-refresh]')) refresh(true);
  });
  document.addEventListener('change', event => {
    const provider = event.target.dataset?.rnMetricsAccount;
    if (provider) refresh(true, {provider, account_id: event.target.value || null});
  });
  render();
  bootstrap().catch(() => {});
})();
