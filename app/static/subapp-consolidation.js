/* Presentation only: internal company IDs and action contracts remain unchanged. */
(() => {
  const labels = {'ZAR Commerce':'ZAR Reselling','ZAR Media':'ZAR Clipper'};
  function text(el, value) { if (el && el.textContent !== value) el.textContent = value; }
  function guide(host, key, title, steps, description) {
    if (!host || host.querySelector(`[data-subapp-guide="${key}"]`)) return;
    const box = document.createElement('section');
    box.className = 'zarSubappGuide'; box.dataset.subappGuide = key;
    const heading = document.createElement('strong'); heading.textContent = title;
    const paragraph = document.createElement('p'); paragraph.textContent = description;
    const list = document.createElement('ol'); list.setAttribute('aria-label','Etapas del flujo');
    steps.forEach(step => { const item = document.createElement('li'); item.textContent = step; list.append(item); });
    box.append(heading, paragraph, list);
    const anchor = host.querySelector(':scope > h2, :scope > h3, :scope > summary, :scope > b');
    if (anchor) anchor.after(box); else host.prepend(box);
  }
  function fieldLabels(form, mapping) {
    if (!form) return;
    Object.entries(mapping).forEach(([name,label]) => {
      const input = form.elements.namedItem(name);
      if (!input || input.closest('label')) return;
      const wrapper = document.createElement('label'); wrapper.className = 'zarSubappField';
      const caption = document.createElement('span'); caption.textContent = label;
      input.before(wrapper); wrapper.append(caption,input);
    });
  }
  function decorate() {
    document.querySelectorAll('#zarCommerceAgency > h2, [data-zar-media] > h3, .zhCard > b, #zhLedgerCompany option, #orchestrationWorkspace article > h3').forEach(el => {
      const current = el.textContent;
      for (const [oldName,newName] of Object.entries(labels)) if (current.includes(oldName)) text(el,current.replace(oldName,newName));
    });
    const commerce = document.getElementById('zarCommerceAgency');
    guide(commerce,'dropshipping','Producto, proveedor y margen en un solo flujo', ['Investigar','Calcular margen','Revisar proveedor','Preparar Shopify','Gestionar pedidos'], 'Empieza por Nichos o Productos. Conserva las fuentes y revisa los costes antes de preparar un borrador para Shopify.');
    document.querySelectorAll('[data-zar-media]').forEach(host => {
      guide(host,'clipper','De historia a clip revisado', ['Historia','Escenas','Render MP4','Preview','Publicación'], 'Genera clips con DramaClaw, revisa el vídeo y edita sus metadatos antes de preparar YouTube, Instagram o TikTok. Cada publicación mantiene su confirmación.');
      const names = {refresh:'Actualizar progreso',pause:'Pausar avance',retry_stage:'Reintentar etapa',retry:'Continuar proyecto',configure:'Conexión y diagnóstico',render_final:'Render final con subtítulos'};
      host.querySelectorAll('[data-media-action]').forEach(button => { if (names[button.dataset.mediaAction]) text(button,names[button.dataset.mediaAction]); });
      const duration = host.querySelector('input[name="duration"]'); if (duration) duration.setAttribute('aria-label','Duración objetivo en segundos');
      const preview = host.querySelector('[data-media-preview]'); if (preview) preview.setAttribute('aria-label','Previsualización del clip');
    });
    const sites = document.getElementById('zwSites');
    text(sites?.querySelector(':scope > summary'),'ZAR Sites · Ideas, web y monetización');
    guide(sites,'sites','Construye sobre una idea validada',['Idea','Validación','Web y SEO','Contenido','Monetización'], 'Guarda una idea o importa una web existente. Revisa HTML y SEO, abre su preview y consulta las métricas reales de AdSense cuando la cuenta esté conectada.');
    fieldLabels(sites?.querySelector('[data-form="site"]'),{name:'Nombre del proyecto',topic:'Idea o nicho',language:'Idioma',country:'País',domain:'Dominio existente (opcional)',code:'HTML (opcional)',files:'Archivos de la web'});
    fieldLabels(sites?.querySelector('[data-form="adsense"]'),{account:'Cuenta AdSense (opcional)',domain:'Filtrar por dominio (opcional)'});
    if (sites && !sites.querySelector('iframe') && !sites.querySelector('[data-subapp-empty]')) {
      const empty = document.createElement('p'); empty.dataset.subappEmpty = ''; empty.className = 'zarSubappEmpty';
      empty.textContent = 'El preview aparecerá cuando un proyecto tenga una web construida o importada.';
      sites.querySelector('[data-form="site"]')?.after(empty);
    }
    const workflows = document.getElementById('zarBusinessWorkflows');
    text(workflows?.querySelector(':scope > h2'),'JEV · ZAR Clipper · ZAR Sites');
    text(workflows?.querySelector('a[href="#zarMediaWorkflowMount"]'),'ZAR Clipper');
  }
  let scheduled = false;
  const observer = new MutationObserver(() => {
    if (scheduled) return; scheduled = true;
    requestAnimationFrame(() => { scheduled = false; observer.disconnect(); decorate(); observe(); });
  });
  function observe() { observer.observe(document.body,{childList:true,subtree:true}); }
  function start() { decorate(); observe(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',start,{once:true}); else start();
})();
