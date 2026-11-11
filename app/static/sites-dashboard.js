/* ZAR Sites · clean ReposNews dashboard and tabbed organisation of the existing panels.
   Reuses existing endpoints and the existing editor's confirmed actions; adds no new permissions. */
(()=>{
 const TABS=[['resumen','Resumen'],['articulos','Artículos'],['instagram','Instagram'],['editorial','Mesa editorial'],['adsense','AdSense y legal'],['herramientas','Herramientas']];
 const GROUPS={zarReposNewsSiteSummary:'adsense',zarAdsenseReadiness:'adsense',zwtIntegrations:'adsense',zarReposNewsMirror:'adsense',
  reposnewsEditor:'editorial',zarEditorial:'editorial',zwtDashboard:'herramientas',zwtPreview:'herramientas',zarSitesNative:'herramientas'};
 const STATE_LABEL={PUBLISHED:'Publicado',READY_PRIVATE:'Listo',READY:'Listo',DRAFT:'Borrador',MODIFYING:'En revisión',CANCELLED:'Cancelado',PUBLISHING:'Publicando',REVIEW:'Revisión',SCHEDULED:'Programado',IDEA:'Idea',RESEARCH:'Investigando'};
 const REEL_LABEL={RECEIVED:'En cola',WAITING_LOCAL_WORKER:'Esperando descarga',OPENING_INSTAGRAM:'Abriendo Instagram',FETCHING_VIDEO:'Descargando vídeo',VIDEO_DOWNLOADED:'Vídeo descargado',
  FETCHING_MEDIA:'Leyendo vídeo',VISION_ANALYSIS:'Analizando vídeo',TRANSCRIBING:'Transcribiendo',ANALYZING:'Analizando',BROWSING:'Consultando fuentes',IDENTIFYING:'Identificando proyecto',
  RESEARCHING:'Investigando',DRAFTING_ES:'Redactando ES',DRAFTING_EN:'Redactando EN',DRAFTING:'Redactando',IMAGES:'Portada',ASSETS:'Portada',SEO:'SEO',COVER_PENDING:'Creando portada',
  READY_PRIVATE:'Artículo listo',PUBLISHED:'Publicado',NEEDS_DISAMBIGUATION:'Necesita tu ayuda',FAILED_RETRYABLE:'Reintentando',FAILED_SOURCE:'Fuente no verificada',
  FAILED_PERMANENT:'No se pudo procesar',FAILED:'Error',ARTICLE_UPDATE_DRAFT:'Actualización propuesta',NO_CHANGE:'Sin cambios',CANCELLED:'Cancelado',DISCARDED:'Descartado',ACTION_REQUIRED:'Acción necesaria'};
 const DONE=new Set(['PUBLISHED','READY_PRIVATE','NO_CHANGE','ARTICLE_UPDATE_DRAFT','CANCELLED','DISCARDED']);
 const BAD=new Set(['NEEDS_DISAMBIGUATION','FAILED_SOURCE','FAILED_PERMANENT','FAILED','ACTION_REQUIRED']);
 let csrf='',data=null,tab='resumen',filter='all',query='',loading=false,notice='';
 try{tab=sessionStorage.getItem('zsd_tab')||'resumen'}catch{}
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const when=v=>{if(!v)return '—';const d=new Date(v);return isNaN(d)?esc(v):d.toLocaleString('es-ES',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})};
 async function api(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify(body||{})});let j={};try{j=await r.json()}catch{}if(!r.ok||j.ok===false)throw Error(j.error||('HTTP '+r.status));return j.result??j;}
 async function load(){if(!csrf||loading)return;loading=true;try{data=await api('/api/holdings/workflows/reposnews_status');}catch(e){if(!data)notice=e.message;}finally{loading=false;}render();}
 function host(){return document.getElementById('zwSites')}

 function organise(){const h=host();if(!h)return;let shell=document.getElementById('zsd');
  if(!shell){shell=document.createElement('section');shell.id='zsd';shell.className='zsd';h.insertBefore(shell,h.querySelector(':scope > summary')?.nextSibling||h.firstChild);}
  else{const first=[...h.children].find(c=>c.tagName!=='SUMMARY');if(shell.parentElement!==h||first!==shell)h.insertBefore(shell,first||null);}
  let group='herramientas';
  for(const el of h.children){if(el===shell||el.tagName==='SUMMARY')continue;
   if(GROUPS[el.id])group=GROUPS[el.id];else if(/^AdSense/.test(el.textContent.trim())&&el.tagName==='H3')group='adsense';else if(el.matches('form[data-form=site], .zarSubappGuide, .zarSubappEmpty, .zwtOptions'))group='herramientas';
   const g=GROUPS[el.id]||(el.tagName==='PRE'||el.tagName==='H3'||(el.tagName==='P'&&/ESTIMATED|FUENTE: Google AdSense/.test(el.textContent))||(el.tagName==='DETAILS'&&/AdSense/.test(el.textContent))||(el.tagName==='FORM'&&/AdSense/.test(el.textContent))?'adsense':group);
   if(el.dataset.zsdGroup!==g)el.dataset.zsdGroup=g;}
  h.dataset.zsdTab=tab;if(!h.open)h.open=true;}

 function kpi(label,value,hint,tone){return `<div class="zsdKpi ${tone||''}"><span>${esc(label)}</span><b>${esc(value)}</b>${hint?`<small>${esc(hint)}</small>`:''}</div>`}
 function cover(a){return a.display_cover?`<img loading="lazy" src="${esc(a.display_cover)}" alt="">`:`<div class="zsdNoCover">${esc((a.title_es||a.repo||'?').slice(0,1))}</div>`}
 function publicUrl(a){return a.published?(a.seo?.es?.canonical||''):'/reposnews-preview/es/'+encodeURIComponent(a.id)}
 function card(a){const st=a.published?'PUBLISHED':a.state;return `<article class="zsdCard"><a class="zsdThumb" href="${esc(publicUrl(a))}" target="_blank" rel="noopener">${cover(a)}</a><div class="zsdCardBody"><span class="zsdChip s-${esc(st)}">${esc(STATE_LABEL[st]||st)}</span><h4 title="${esc(a.title_es)}">${esc(a.title_es||a.repo)}</h4><p>${esc(a.repo||'')} · ${when(a.published_at||a.updated_at||a.created_at)}</p><div class="zsdActions"><a class="zsdBtn ghost" href="${esc(publicUrl(a))}" target="_blank" rel="noopener">${a.published?'Ver en la web':'Vista previa'}</a><button class="zsdBtn ghost" data-zsd-edit="${esc(a.id)}">Editar</button>${['READY','READY_PRIVATE'].includes(a.state)&&!a.published?`<button class="zsdBtn primary" data-zsd-publish="${esc(a.id)}">Publicar</button>`:''}</div></div></article>`}

 function overview(){const arts=data.articles||[],pub=arts.filter(a=>a.published),ready=arts.filter(a=>!a.published&&['READY','READY_PRIVATE'].includes(a.state));
  const inbox=data.instagram_inbox||[],working=inbox.filter(r=>!DONE.has(r.status)&&!BAD.has(r.status)),help=inbox.filter(r=>BAD.has(r.status));
  const auto=data.autonomous_editorial_status||{},on=auto.enabled&&auto.daily_policy,h=data.instagram_history_summary||{},worker=data.local_instagram_worker||{};
  const blockers=[];if(auto.blocker)blockers.push(auto.blocker==='Revisión legal pendiente'?'Falta aprobar los datos legales (pestaña Mesa editorial → Datos legales ReposNews). Sin esto no se publica nada.':auto.blocker);
  if(!on)blockers.push('La publicación automática está pausada.');
  return `<div class="zsdKpis">${kpi('Publicados',pub.length,'artículos en reposnews.com')}${kpi('Listos',ready.length,ready.length?'pendientes de publicar':'nada pendiente',ready.length?'warn':'')}${kpi('Reels en proceso',working.length,working.length?'ZAR los está analizando':'cola vacía')}${kpi('Necesitan ayuda',help.length,help.length?'revisa la pestaña Instagram':'todo en orden',help.length?'bad':'')}${kpi('Hoy',auto.today??0,'publicados hoy')}</div>
  <div class="zsdRow"><section class="zsdPanel"><header><h3>Piloto automático</h3><span class="zsdPill ${on&&!auto.blocker?'ok':on?'warn':'off'}">${on&&!auto.blocker?'Activo':on?'Bloqueado':'Pausado'}</span></header>
   <p>ZAR revisa la conversación de Instagram cada 20 minutos, analiza cada reel nuevo o antiguo, escribe el artículo ES/EN con fuentes oficiales, crea una portada única y lo publica. Cada día a las 18:00 completa hasta 6 guías.</p>
   ${blockers.map(b=>`<p class="zsdAlert">${esc(b)}</p>`).join('')}
   <dl class="zsdFacts"><div><dt>Próxima ronda</dt><dd>${when(auto.next_run)}</dd></div><div><dt>Última ejecución</dt><dd>${esc(auto.last_day||'—')} · ${esc(auto.last_status||'—')}</dd></div></dl>
   <div class="zsdActions"><button class="zsdBtn ${on?'ghost':'primary'}" data-zsd-auto="${on?'pause':'enable'}">${on?'Pausar piloto automático':'Activar piloto automático'}</button><a class="zsdBtn ghost" href="https://www.reposnews.com/es/" target="_blank" rel="noopener">Abrir reposnews.com</a></div></section>
  <section class="zsdPanel"><header><h3>Instagram</h3><span class="zsdPill ${h.status==='COMPLETED'?'ok':h.status==='AUTH_REQUIRED'||h.error?'warn':'off'}">${esc({COMPLETED:'Al día',SYNCING:'Revisando',AUTH_REQUIRED:'Reconectar',RATE_LIMITED:'En pausa (Meta)',FAILED_RETRYABLE:'Reintentando',NOT_STARTED:'Sin revisar'}[h.status]||h.status||'Sin revisar')}</span></header>
   <dl class="zsdFacts"><div><dt>Reels encontrados</dt><dd>${esc(Math.max(h.reels_found||0,inbox.length))}</dd></div><div><dt>Procesados</dt><dd>${esc(Math.max(h.processed||0,inbox.filter(r=>DONE.has(r.status)).length))}</dd></div><div><dt>Pendientes</dt><dd>${esc(working.length)}</dd></div><div><dt>Última revisión</dt><dd>${when(h.last_sync)}</dd></div></dl>
   <p class="zsdMuted">Descarga de vídeo: ${worker.state==='ONLINE'?'PC de ZAR conectado':'Railway (el PC de ZAR no está conectado; Railway continúa solo tras 15 min)'}.</p>
   <div class="zsdActions"><button class="zsdBtn primary" data-zsd-sync>Revisar conversación ahora</button><button class="zsdBtn ghost" data-zsd-backfill>Procesar y publicar reels antiguos</button></div></section></div>
  <section class="zsdPanel"><header><h3>Últimos artículos</h3><button class="zsdLink" data-zsd-tab="articulos">Ver todos (${arts.length}) →</button></header><div class="zsdGrid">${arts.slice().sort((a,b)=>String(b.published_at||b.created_at||'').localeCompare(String(a.published_at||a.created_at||''))).slice(0,8).map(card).join('')||'<p class="zsdMuted">Todavía no hay artículos.</p>'}</div></section>`;}

 function articles(){const arts=(data.articles||[]).filter(a=>{const st=a.published?'pub':['READY','READY_PRIVATE'].includes(a.state)?'ready':a.state==='CANCELLED'?'cancel':'draft';return (filter==='all'||filter===st)&&(!query||((a.title_es||'')+' '+(a.repo||'')).toLowerCase().includes(query))}).sort((a,b)=>String(b.published_at||b.created_at||'').localeCompare(String(a.published_at||a.created_at||'')));
  const f=[['all','Todos'],['pub','Publicados'],['ready','Listos'],['draft','Borradores']];
  return `<section class="zsdPanel"><header><h3>Artículos</h3><input class="zsdSearch" type="search" placeholder="Buscar por título o repositorio" value="${esc(query)}" data-zsd-search aria-label="Buscar artículos"></header><div class="zsdFilters">${f.map(([k,l])=>`<button class="zsdFilter ${filter===k?'on':''}" data-zsd-filter="${k}">${l}</button>`).join('')}</div><div class="zsdGrid">${arts.map(card).join('')||'<p class="zsdMuted">Sin resultados.</p>'}</div></section>`;}

 function instagram(){const rows=(data.instagram_inbox||[]).slice().sort((a,b)=>String(b.received_at||'').localeCompare(String(a.received_at||'')));const arts=Object.fromEntries((data.articles||[]).map(a=>[a.id,a]));
  return `<section class="zsdPanel"><header><h3>Reels recibidos</h3><div class="zsdActions"><button class="zsdBtn primary" data-zsd-sync>Revisar ahora</button><button class="zsdBtn ghost" data-zsd-backfill>Procesar reels antiguos</button></div></header>
  <div class="zsdList">${rows.map(r=>{const a=arts[r.article_id];const st=r.status||'RECEIVED';return `<div class="zsdItem"><span class="zsdDot ${DONE.has(st)?'ok':BAD.has(st)?'bad':'run'}"></span><div class="zsdItemMain"><b>${esc(a?.title_es||r.repo||'Reel recibido')}</b><small>${when(r.received_at)}${r.backfill?' · historial':''}${r.source_url?` · <a href="${esc(r.source_url)}" target="_blank" rel="noopener">ver reel</a>`:''}</small></div><span class="zsdChip s-${esc(st)}">${esc(REEL_LABEL[st]||st)}</span>${a?`<a class="zsdBtn ghost sm" href="${esc(publicUrl(a))}" target="_blank" rel="noopener">Artículo</a>`:''}</div>`}).join('')||'<p class="zsdMuted">Todavía no hay reels. Envía un reel por mensaje a @zaragente031 desde @solana031.</p>'}</div>
  <p class="zsdMuted">Los casos marcados como "Necesita tu ayuda" pueden resolverse indicando el repositorio en Mesa editorial → Diagnóstico de Reels.</p></section>`;}

 function adsense(){const e=data.enrichment||{},legal=data.legal_status?.status,rows=[
  ['bad','Datos de la cuenta de AdSense','Google avisó: «Los datos de la cuenta son imprecisos o están incompletos». Revisa en AdSense → Cuenta → Información de la cuenta y Pagos: nombre del beneficiario idéntico al de tu DNI y cuenta bancaria, dirección completa (calle, número, piso, código postal), teléfono verificado y que no exista otra cuenta AdSense con tus datos.','https://adsense.google.com/adsense/u/0/pub-4119869448727531/settings/account/info','Abrir datos de la cuenta'],
  [e.short?'warn':'ok','Calidad y extensión del contenido',e.published?`${e.published} guías publicadas · mediana ${e.median_words} palabras · ${e.short} por debajo de ${e.target_words}. ZAR las está ampliando con fuentes oficiales (casos de uso, errores comunes, alternativas, FAQ).${e.pending?` ${e.pending} ampliaciones listas para aprobar.`:''}`:'Sin datos todavía.',null,null],
  [legal==='LEGAL_READY'?'ok':'bad','Identidad legal y páginas obligatorias',legal==='LEGAL_READY'?'Aviso legal, privacidad, cookies, contacto y «Acerca de» publicados.':'Falta aprobar los datos legales en Mesa editorial.',null,null],
  ['ok','Verificación del sitio y ads.txt','Etiqueta google-adsense-account y ads.txt con pub-4119869448727531 publicados en www.reposnews.com.',null,null],
  ['ok','Contenido duplicado','Las páginas de listado ya no se envían al índice (noindex) y el sitemap solo incluye guías y páginas legales.',null,null]];
  return `<section class="zsdPanel"><header><h3>Por qué AdSense rechazó ReposNews</h3><a class="zsdBtn ghost" href="https://adsense.google.com/adsense/u/0/pub-4119869448727531/sites/my-sites" target="_blank" rel="noopener">Abrir Sitios en AdSense ↗</a></header>
  <div class="zsdDiag">${rows.map(([tone,title,text,url,label])=>`<div class="zsdDiagRow" data-tone="${tone}"><span class="zsdDot ${tone==='ok'?'ok':tone==='bad'?'bad':'run'}"></span><div><b>${esc(title)}</b><p>${esc(text)}</p>${url?`<a class="zsdLink" href="${esc(url)}" target="_blank" rel="noopener">${esc(label)} ↗</a>`:''}</div></div>`).join('')}</div>
  ${e.pending?`<div class="zsdActions"><button class="zsdBtn primary" data-zsd-enrich>Aprobar ${e.pending} guía${e.pending>1?'s':''} ampliada${e.pending>1?'s':''}</button><span class="zsdMuted">Puedes revisar cada una antes en la campana de notificaciones.</span></div>`:''}
  <p class="zsdMuted">Cuando lo anterior esté corregido, solicita una nueva revisión desde AdSense → Sitios. Google tarda de unos días a 2-4 semanas; si el botón no está disponible, indica la fecha a partir de la cual se puede volver a pedir.</p></section>`;}
 function render(){organise();const shell=document.getElementById('zsd');if(!shell)return;
  const nav=`<nav class="zsdTabs" role="tablist">${TABS.map(([k,l])=>`<button role="tab" aria-selected="${tab===k}" class="zsdTab ${tab===k?'on':''}" data-zsd-tab="${k}">${l}</button>`).join('')}</nav>`;
  let body='';
  if(tab==='adsense'&&data?.project_id)body=adsense();
  if(['resumen','articulos','instagram'].includes(tab))body=!data?`<p class="zsdMuted">${esc(notice||'Cargando ReposNews…')}</p>`:!data.project_id?`<section class="zsdPanel"><p>Proyecto ReposNews sin inicializar.</p><button class="zsdBtn primary" data-zsd-tab="editorial">Abrir mesa editorial</button></section>`:tab==='resumen'?overview():tab==='articulos'?articles():instagram();
  const focus=document.activeElement?.matches?.('[data-zsd-search]');
  shell.innerHTML=`<header class="zsdHead"><div><h2>ReposNews</h2><p>www.reposnews.com · reels de Instagram convertidos en guías ES/EN</p></div><a class="zsdBtn ghost" href="https://www.reposnews.com/es/" target="_blank" rel="noopener">Ver web ↗</a></header>${nav}<div class="zsdNotice" role="status">${esc(notice)}</div><div class="zsdBody">${body}</div>`;
  if(focus){const s=shell.querySelector('[data-zsd-search]');s?.focus();s?.setSelectionRange(s.value.length,s.value.length);}}

 function setTab(t){tab=t;try{sessionStorage.setItem('zsd_tab',t)}catch{}render();document.getElementById('zsd')?.scrollIntoView({block:'start',behavior:'smooth'});}
 function editorButton(sel){return document.querySelector('#reposnewsEditor '+sel)}
 document.addEventListener('click',async e=>{const t=e.target.closest('[data-zsd-tab],[data-zsd-filter],[data-zsd-edit],[data-zsd-publish],[data-zsd-auto],[data-zsd-sync],[data-zsd-backfill],[data-zsd-enrich]');
  if(!t||!t.closest('#zsd'))return;e.preventDefault();e.stopPropagation();
  if(t.dataset.zsdTab)return setTab(t.dataset.zsdTab);
  if(t.dataset.zsdFilter){filter=t.dataset.zsdFilter;return render();}
  if(t.dataset.zsdEdit){setTab('editorial');setTimeout(()=>{editorButton('[data-edit="'+CSS.escape(t.dataset.zsdEdit)+'"]')?.click();setTimeout(()=>document.querySelector('#reposnewsEditor [data-edit-form]')?.scrollIntoView({block:'start'}),60)},0);return;}
  if(t.dataset.zsdPublish){const b=editorButton('[data-publish="'+CSS.escape(t.dataset.zsdPublish)+'"]');if(b){b.click();setTimeout(load,4000);}return;}
  t.disabled=true;try{
   if(t.dataset.zsdAuto){const enable=t.dataset.zsdAuto==='enable';if(enable&&!await ZarUI.confirm('¿Activar el piloto automático? ZAR publicará en reposnews.com los artículos de reels (nuevos y antiguos) y hasta 6 guías diarias, siempre con fuentes oficiales y portada propia.'))return;
    data=await api('/api/holdings/workflows/reposnews_autonomous_configure',{enabled:enable,authorize_publication:enable});notice=enable?'Piloto automático activado.':'Piloto automático pausado.';}
   if(t.hasAttribute('data-zsd-sync')){await api('/api/reposnews/history/sync',{});notice='Revisión de Instagram solicitada. Los reels nuevos aparecerán en unos minutos.';}
   if(t.hasAttribute('data-zsd-enrich')){if(!await ZarUI.confirm('¿Publicar las guías ampliadas? Sustituyen el texto de las versiones cortas en reposnews.com (mismas URLs y portadas).'))return;data=await api('/api/holdings/workflows/reposnews_enrich_approve_all',{});notice='Guías ampliadas publicadas: '+(data.enrich_result?.applied??0)+'.';}
   if(t.hasAttribute('data-zsd-backfill')){if(!await ZarUI.confirm('ZAR volverá a revisar todos los reels de la conversación, analizará los que falten o fallaron y publicará los artículos de forma escalonada (uno cada 20 minutos). ¿Continuar?'))return;
    await api('/api/reposnews/history/start',{reprocess_unresolved:true,reuse_media:true,authorize_publication:true});notice='Procesamiento de reels antiguos en marcha.';}
   await load();}catch(x){notice='No se pudo completar: '+x.message;render();}finally{t.disabled=false;}},true);
 document.addEventListener('input',e=>{if(e.target.matches('#zsd [data-zsd-search]')){query=e.target.value.trim().toLowerCase();render();}});
 // Header shortcuts of the Sites workspace point at tools now grouped in tabs.
 document.addEventListener('click',e=>{const j=e.target.closest('[data-zwt-jump]');if(!j||!host())return;const map={create:'herramientas',import:'herramientas',preview:'herramientas',projects:'herramientas',publish:'resumen'};if(map[j.dataset.zwtJump]){tab=map[j.dataset.zwtJump];render();}},true);
 window.addEventListener('zar-workflow-state',e=>{csrf=e.detail?.csrf||csrf;organise();if(!data)load();});
 const observer=new MutationObserver(()=>{const h=host();if(h&&([...h.children].some(el=>el.id!=='zsd'&&el.tagName!=='SUMMARY'&&!el.dataset.zsdGroup)||[...h.children].find(c=>c.tagName!=='SUMMARY')?.id!=='zsd'))organise();});
 function boot(){const h=host();if(!h)return setTimeout(boot,500);observer.observe(h,{childList:true});render();}
 boot();setInterval(()=>{if(host()&&!document.hidden&&['resumen','instagram'].includes(tab))load();},30000);
})();
