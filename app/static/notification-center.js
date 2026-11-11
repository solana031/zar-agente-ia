/* One action inbox over the existing Human Action Center. */
(()=>{
 if(window.parent!==window){try{if(parent.location.origin===location.origin)return;}catch{}}
 if(document.getElementById('zarNotificationBell'))return;
 const css=document.createElement('link');css.rel='stylesheet';css.href='/static/notification-center.css'+new URL(document.currentScript?.src||location.href).search;document.head.append(css);
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const safe=v=>{try{const u=new URL(v,location.origin);return ['https:','http:'].includes(u.protocol)?u.href:'#';}catch{return '#';}};
 const icon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4M10 2h4"/></svg>';
 const labels={ACCOUNT_CONNECTION:'Cuenta requiere atención',ARTICLE_READY:'Artículo listo',ARTICLE_UPDATE_READY:'Actualización disponible',ARTICLE_NEEDS_DISAMBIGUATION:'Necesito un dato',ARTICLE_FAILED:'No se pudo completar',DOC_READY:'Documento listo',SLIDES_READY:'Presentación lista',SHEET_READY:'Hoja lista',FORM_READY:'Formulario listo',VIDEO_READY:'Vídeo listo',PUBLISH_SUCCESS:'Publicación completada',PUBLISH_FAILED:'Publicación fallida',WORKER_OFFLINE:'Worker desconectado',WORKER_SESSION_EXPIRED:'Sesión caducada',SYSTEM_ACTION_REQUIRED:'Acción pendiente'};
 Object.assign(labels,{MIRROR_SYNC_SUCCESS:'Mirror actualizado',MIRROR_SYNC_FAILED:'Mirror sin sincronizar',MIRROR_OUTDATED:'Mirror pendiente'});
 Object.assign(labels,{INSTAGRAM_HISTORY_SYNC:'Historial de Instagram revisado',SOCIAL_ACCOUNT_READY:'Cuenta preparada',SOCIAL_ACCOUNT_BLOCKED:'Cuenta requiere atención'});
 let saved={};try{saved=JSON.parse(sessionStorage.getItem('zar-notification-view')||'{}');}catch{}
 let state={items:[],historical:{}},csrf='',filter=saved.filter||'TODAS',subfilter=saved.subfilter||'TODAS',sort=saved.sort||'PRIORIDAD',page=0,busy=false,message='',editing='',archived=false,confirmation=null,acting=false;
 const filters=['TODAS','NO LEÍDAS','REQUIEREN ACCIÓN','REPOSNEWS','SOCIAL','CUENTAS','SISTEMA'];
 const filterLabel={TODAS:'Todas','NO LEÍDAS':'Sin leer','REQUIEREN ACCIÓN':'Pendientes',REPOSNEWS:'ReposNews',SOCIAL:'Redes',CUENTAS:'Cuentas',SISTEMA:'Sistema'};
 const groupIcon={REPOSNEWS:'<path d="M4 5h12v14H6a2 2 0 0 1-2-2zM16 9h4v8a2 2 0 0 1-2 2M8 9h4M8 13h4"/>',SOCIAL:'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m10 9 5 3-5 3z"/>',CUENTAS:'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',SISTEMA:'<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/>'};
 const svg=p=>'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+p+'</svg>';
 const ago=v=>{const t=new Date(v);if(!v||isNaN(t))return '';const m=Math.round((Date.now()-t)/60000);if(m<1)return 'ahora';if(m<60)return 'hace '+m+' min';const h=Math.round(m/60);if(h<24)return 'hace '+h+' h';const d=Math.round(h/24);return d<7?'hace '+d+' d':t.toLocaleDateString('es-ES',{day:'numeric',month:'short'});};
 const dayGroup=v=>{const t=new Date(v);if(!v||isNaN(t))return 'Anteriores';const today=new Date();today.setHours(0,0,0,0);const diff=(today-new Date(t.getFullYear(),t.getMonth(),t.getDate()))/86400000;return diff<=0?'Hoy':diff===1?'Ayer':diff<7?'Esta semana':'Anteriores';};
 const subfilters=['TODAS','PARA PUBLICAR','ACTUALIZACIONES','NECESITAN IDENTIFICACIÓN','NECESITAN REVISIÓN','PUBLICADAS','CANCELADAS','ERRORES'];
 const remember=()=>{try{sessionStorage.setItem('zar-notification-view',JSON.stringify({filter,subfilter,sort}));}catch{}};
 const drafts=new Map(),expanded=new Set(),techOpen=new Set();let size=12,settingsView=false,notify=null,notifyMsg='';
 const dialog=document.createElement('dialog');dialog.id='zarNotificationCenter';dialog.setAttribute('aria-label','Centro de notificaciones ZAR');document.body.append(dialog);
 const bell=document.createElement('button');bell.type='button';bell.id='zarNotificationBell';bell.className='topIconBtn';bell.setAttribute('aria-label','Notificaciones');bell.setAttribute('aria-haspopup','dialog');bell.setAttribute('aria-expanded','false');bell.innerHTML=icon+'<span data-unread hidden></span>';
 const slot=document.createElement('div');slot.className='znBellSlot';slot.append(bell);
 (new URLSearchParams(location.search).has('zar_workspace')?document.body:document.querySelector('.topActions')||document.body).prepend(slot);
 Object.assign(labels,{ARTICLE_COVER_GENERATED:'Portada preparada',ARTICLE_COVER_FAILED:'Portada pendiente'});
 const group=n=>n.category||(/^ARTICLE|INSTAGRAM_HISTORY/.test(n.type)?'REPOSNEWS':/^SOCIAL|VIDEO_/.test(n.type)?'SOCIAL':n.type==='ACCOUNT_CONNECTION'?'CUENTAS':'SISTEMA');
 const required=n=>n.requires_action??(!n.completed&&!n.processing&&(/ARTICLE_READY|ARTICLE_UPDATE_READY|ACTION|FAILED|OFFLINE|EXPIRED/.test(n.type+' '+n.status)));
 const rnfilter=n=>n.repos_filter||(n.type==='ARTICLE_IDENTIFICATION_REQUIRED'?'NECESITAN IDENTIFICACIÓN':n.type==='ARTICLE_UPDATE_READY'?'ACTUALIZACIONES':n.type==='ARTICLE_READY'&&!n.completed?'PARA PUBLICAR':'NECESITAN REVISIÓN');
 const category=n=>n.processing?'INFO':/FAILED|ERROR/.test(n.type+' '+n.status)?'ERROR':n.completed?'SUCCESS':/_READY$/.test(n.type)?'READY':/ACTION|DISAMBIGUATION|OFFLINE|EXPIRED/.test(n.type+' '+n.status)?'ACTION_REQUIRED':'INFO';
 const link=(href,text)=>'<a href="'+esc(safe(href))+'" target="_blank" rel="noopener">'+esc(text)+'</a>';
 const button=(action,id,text,extra='')=>'<button type="button" data-action="'+action+'" data-id="'+esc(id)+'" '+extra+'>'+esc(text)+'</button>';
 function short(n){if(n.type==='ARTICLE_READY')return 'Artículo ES/EN preparado desde tu Reel.';if(n.type==='ARTICLE_UPDATE_READY')return 'Hay cambios para revisar en el artículo existente.';if(n.type==='ARTICLE_NEEDS_DISAMBIGUATION')return 'No he podido identificar la herramienta de este Reel.';if(n.type==='ARTICLE_FAILED')return 'El trabajo se conserva. Puedes reintentarlo o consultar el detalle.';return String(n.message||n.reason||'').slice(0,160);}
 function card(n){
  const d=n.editorial||n.details||{},a=n.article,c=category(n),item=n.inbox_item_id||d.inbox_item_id||n.entity_id;
  let actions='',form='';
  if(n.processing){if(d.reel)actions=link(d.reel,'Ver Reel');}
  else if(n.type==='ARTICLE_READY'&&a){
   actions=link(d.preview_es||'/reposnews-preview/es/'+a.id,'Ver borrador');
   if(!n.completed&&a.approval_request)actions+=button('publish',n.id,'Publicar')+link(a.preview||'/?zar_workspace=sites&edit_article='+encodeURIComponent(a.id)+'#reposnewsEditor','Revisar / modificar')+button('cancel',n.id,'Cancelar');
   if(editing===n.id)form='<form data-edit="'+esc(n.id)+'"><label>¿Qué quieres cambiar?<textarea name="instruction" required maxlength="3000">'+esc(drafts.get(n.id)||'')+'</textarea></label><button>Aplicar cambio</button></form>';
  }else if(n.type==='ARTICLE_UPDATE_READY'){
   actions=link(n.deep_link,'Revisar cambios');
   if(!n.completed&&n.approval_request)actions+=button('update',n.id,'Actualizar')+button('ignore',n.id,'Ignorar');
  }else if(n.type==='ARTICLE_IDENTIFICATION_REQUIRED'&&!n.completed){
   form=(n.details?.items||[]).map(item=>{const date=new Date(item.date),when=item.date&&!isNaN(date)?date.toLocaleString('es-ES'):String(item.date||'Fecha no disponible');return '<form data-resolve="'+esc(n.id)+'" data-item="'+esc(item.id)+'">'+(item.thumbnail?'<img src="'+esc(safe(item.thumbnail))+'" alt="Reel pendiente de identificación" loading="lazy">':'')+'<p>'+esc(when)+'</p><p>'+esc(item.caption||'')+'</p><p>'+esc((item.candidates||[]).slice(0,3).map(c=>c.candidate).join(' · ')||'Sin candidato fiable')+'</p><label>¿Qué herramienta/proyecto es?<input name="project" maxlength="80" required value="'+esc(drafts.get(item.id)||'')+'"></label><button>CONFIRMAR</button></form>';}).join('');
  }else if(n.type==='ARTICLE_NEEDS_DISAMBIGUATION'&&!n.completed){
   if(d.reel)actions=link(d.reel,'Ver Reel');
   form='<form data-resolve="'+esc(n.id)+'"><label>Nombre de herramienta<input name="project" maxlength="80" required value="'+esc(drafts.get(n.id)||'')+'"></label><button>Continuar</button></form>';
  }else if(n.type==='ARTICLE_FAILED'&&!n.completed){actions=d.status==='FAILED_PERMANENT'?'':button('retry',n.id,'Reintentar');if(d.reel)actions+=link(d.reel,'Ver Reel');}
  else if(n.type==='MIRROR_SYNC_FAILED'&&!n.completed)actions=button('mirror-sync',n.id,'REINTENTAR MIRROR')+link(n.deep_link,'VER DETALLES');
  else actions=(n.actions||[{label:'Ver',url:n.deep_link}]).filter(x=>x.url).map(x=>link(x.url,x.label)).join('');
  const detail={estado:n.status,etapa:d.failed_stage,intentos:d.attempts,error:d.diagnostic};
  const cover=a?(a.cover||a.cover_thumb):d.hero||d.image;
  const changes=n.changes?'<dl class="znChanges">'+Object.entries({ADDED:'Añadido',UPDATED:'Actualizado',REMOVED:'Eliminado'}).map(([k,v])=>'<div><dt>'+v+'</dt><dd>'+esc((n.changes[k]||[]).join(', ')||'—')+'</dd></div>').join('')+'</dl>':'';
  const g=group(n),open=expanded.has(n.id),pending=!n.completed&&!n.processing&&(form||c==='READY'||c==='ACTION_REQUIRED'||c==='ERROR');
  const status=n.dismissed_at?'Archivada':n.processing?'En proceso':n.completed?'Completada':c==='ERROR'?'Error':c==='READY'?'Para revisar':c==='ACTION_REQUIRED'?'Pendiente':'';
  const title=a?.title_es||(n.processing?'Reanalizando el Reel':n.title||labels[n.type]||'Notificación');
  const text=n.processing?'ZAR está revisando de nuevo este Reel. Te avisará cuando termine.':a?.summary_es||short(n);
  const thumb=cover?'<img class="znThumb" src="'+esc(safe(cover))+'" alt="" loading="lazy" decoding="async">':'';
  return '<article class="znCard'+(open?' znOpen':'')+'" data-note="'+esc(n.id)+'" data-priority="'+c+'" data-unread="'+!n.read_at+'" data-group="'+esc(g)+'">'+
   '<div class="znRow" data-toggle="'+esc(n.id)+'" role="button" tabindex="0" aria-expanded="'+open+'"><span class="znIcon">'+svg(groupIcon[g]||groupIcon.SISTEMA)+'</span>'+
   '<div class="znText"><div class="znLine"><span class="znKind">'+esc(n.processing?'Reel en proceso':(labels[n.type]&&labels[n.type]!==title?labels[n.type]:filterLabel[g]||g))+'</span><time datetime="'+esc(n.created_at)+'" title="'+esc(n.created_at?new Date(n.created_at).toLocaleString('es-ES'):'')+'">'+esc(ago(n.created_at))+'</time></div>'+
   '<h3>'+esc(title)+'</h3><p class="znMessage">'+esc(text)+'</p>'+(status?'<span class="znStatus" data-tone="'+c+'">'+esc(status)+'</span>':'')+'</div>'+thumb+(n.read_at?'':'<span class="znDot" aria-label="Sin leer"></span>')+'</div>'+
   ((pending||open)&&(actions||form)?'<div class="znActions">'+actions+'</div>'+form:'')+
   (open?'<div class="znMore">'+changes+(a?'<p class="znArticleMeta">'+esc((a.languages||['ES','EN']).join(' / ')+' · '+(a.repo||'')+' · '+(a.state||''))+'</p>':'')+(d.reel?link(d.reel,'Ver Reel original'):'')+
   '<details data-details="'+esc(n.id)+'" '+(techOpen.has(n.id)?'open':'')+'><summary>Datos técnicos</summary><pre>'+esc(JSON.stringify(detail,null,2))+'</pre></details>'+
   '<div class="znUtility">'+button('read',n.id,n.read_at?'Marcar no leída':'Marcar leída')+button(n.dismissed_at?'restore':'dismiss',n.id,n.dismissed_at?'Recuperar':'Archivar')+'</div></div>':'')+'</article>';
 }
 function render(force=false){
  if(settingsView){renderSettings();return;}
  if(!force&&dialog.contains(document.activeElement)&&/INPUT|TEXTAREA/.test(document.activeElement.tagName))return;
  const scrollTop=dialog.querySelector('.znList')?.scrollTop||0;
  dialog.querySelectorAll('[data-details]').forEach(d=>d.open?techOpen.add(d.dataset.details):techOpen.delete(d.dataset.details));
  const notes=state.items.filter(n=>archived?Boolean(n.dismissed_at):!n.dismissed_at&&(filter==='TODAS'||filter==='NO LEÍDAS'&&!n.read_at||filter==='REQUIEREN ACCIÓN'&&required(n)||group(n)===filter)&&(filter!=='REPOSNEWS'||subfilter==='TODAS'||rnfilter(n)===subfilter));
  const rank=n=>!n.completed&&n.type==='ARTICLE_READY'?0:!n.completed&&n.type==='ARTICLE_UPDATE_READY'?1:required(n)?2:3;
  notes.sort((a,b)=>sort==='ANTIGUAS'?String(a.created_at||'').localeCompare(b.created_at||''):sort==='PRIORIDAD'?rank(a)-rank(b)||String(a.priority||'P2').localeCompare(b.priority||'P2')||String(b.created_at||'').localeCompare(a.created_at||''):String(b.created_at||'').localeCompare(a.created_at||''));
  const iconBtn=(action,label,path,extra='')=>'<button type="button" class="znIconBtn" data-action="'+action+'" aria-label="'+esc(label)+'" title="'+esc(label)+'" '+extra+'>'+svg(path)+'</button>';
  dialog.innerHTML='<header class="znHeader"><div><h2>Notificaciones</h2><small>'+(state.unread?esc(state.unread)+' sin leer':'Todo leído')+'</small></div><div class="znHeadActions">'+iconBtn('settings','Ajustes de avisos (email, WhatsApp)','<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>')+iconBtn('allread','Marcar todo como leído','<path d="m2 13 4 4L16 7M10 17l1 1L22 7"/>')+iconBtn('archive',archived?'Volver a la bandeja':'Ver archivadas','<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10h14V9M10 13h4"/>','aria-pressed="'+archived+'"')+iconBtn('close','Cerrar notificaciones','<path d="M6 6l12 12M18 6 6 18"/>','data-close')+'</div></header>'+
   (archived?'<p class="znArchivedNote">Archivadas</p>':'')+'<nav class="znTabs" aria-label="Filtrar notificaciones">'+filters.map(t=>'<button data-filter="'+t+'" aria-pressed="'+(t===filter&&!archived)+'">'+esc(filterLabel[t]||t)+' <small>'+esc(state.counts?.[t]??state.items.filter(n=>!n.dismissed_at&&(t==='TODAS'||t==='NO LEÍDAS'&&!n.read_at||t==='REQUIEREN ACCIÓN'&&required(n)||group(n)===t)).length)+'</small></button>').join('')+'</nav>'+(filter==='REPOSNEWS'?'<nav class="znTabs znSubTabs" aria-label="Filtrar ReposNews">'+subfilters.map(t=>'<button data-subfilter="'+t+'" aria-pressed="'+(t===subfilter)+'">'+t+'</button>').join('')+'</nav>':'')+
   '<div class="znToolbar"><label>Ordenar <select data-sort aria-label="Ordenar notificaciones">'+[['PRIORIDAD','Prioridad'],['RECIENTES','Más recientes'],['ANTIGUAS','Más antiguas']].map(([v,l])=>'<option value="'+v+'" '+(sort===v?'selected':'')+'>'+l+'</option>').join('')+'</select></label></div>'+
   (confirmation?'<section class="znConfirm" role="region" aria-label="Confirmar publicación"><h3>'+esc(confirmation.action==='publish'?'Publicar esta revisión en ReposNews':'Actualizar esta revisión en ReposNews')+'</h3><p>'+esc(confirmation.title)+'</p><p>Revisión: <code>'+esc(confirmation.revision)+'</code></p><p>Idiomas: '+esc(confirmation.languages.join(' / '))+' · Destino: www.reposnews.com</p>'+button('confirm','','Confirmar publicación',acting?'disabled':'')+button('abort','','Volver',acting?'disabled':'')+'</section>':'')+'<p class="znFeedback" role="status">'+esc(message)+'</p><div class="znList">'+(()=>{let last='';return notes.slice(0,size).map(n=>{const h=sort==='PRIORIDAD'?'':dayGroup(n.created_at);const head=h&&h!==last?'<h4 class="znDay">'+h+'</h4>':'';last=h||last;return head+card(n);}).join('');})()+(notes.length?'':'<div class="znEmpty">'+svg('<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>')+'<p>No hay notificaciones aquí.</p></div>')+(notes.length>size?'<button type="button" class="znMoreBtn" data-action="more">Mostrar más ('+(notes.length-size)+')</button>':'')+'</div>';
  dialog.querySelector('.znList').scrollTop=scrollTop;
 }

 const DAYS=['lunes','martes','miércoles','jueves','viernes','sábado','domingo'];
 const periodText=p=>p.unit==='hour'?(p.every>1?'cada '+p.every+' horas':'cada hora'):p.unit==='minute'?'cada '+p.every+' min':p.unit==='day'?(p.every>1?'cada '+p.every+' días':'cada día')+' · '+String(p.hour??9).padStart(2,'0')+':00':p.unit==='week'?'cada '+DAYS[p.weekday||0]+' · '+String(p.hour??9).padStart(2,'0')+':00':p.unit==='month'?'cada mes, día '+(p.day||1)+' · '+String(p.hour??9).padStart(2,'0')+':00':'periódico';
 const chLabel={email:'Email',whatsapp:'WhatsApp',call:'Llamada'};
 async function loadNotify(){try{const r=await fetch('/api/notify/settings',{cache:'no-store'});const j=await r.json();if(r.ok&&j.ok){notify=j.settings;csrf=j.csrf||csrf;}}catch{}}
 function renderSettings(){
  const n=notify;const iconBtn=(action,label,path)=>'<button type="button" class="znIconBtn" data-action="'+action+'" aria-label="'+esc(label)+'" title="'+esc(label)+'">'+svg(path)+'</button>';
  const head='<header class="znHeader"><div><h2>Ajustes de avisos</h2><small>Email, WhatsApp y avisos periódicos</small></div><div class="znHeadActions">'+iconBtn('settings-back','Volver a notificaciones','<path d="M15 18l-6-6 6-6"/>')+iconBtn('close','Cerrar','<path d="M6 6l12 12M18 6 6 18"/>')+'</div></header>';
  if(!n){dialog.innerHTML=head+'<div class="znList"><p class="znEmpty">Cargando…</p></div>';return;}
  const toggle=(name,on,label)=>'<label class="znSwitch"><input type="checkbox" data-set="'+name+'" '+(on?'checked':'')+'><span></span>'+esc(label)+'</label>';
  const subs=(n.subscriptions||[]).map(x=>'<div class="znSub"><div><b>'+esc(x.label)+'</b><small>'+esc(periodText(x.period||{}))+' · '+esc(chLabel[x.channel]||x.channel)+'</small></div><button type="button" class="znIconBtn" data-action="sub-cancel" data-id="'+esc(x.id)+'" aria-label="Cancelar aviso" title="Cancelar aviso">'+svg('<path d="M6 6l12 12M18 6 6 18"/>')+'</button></div>').join('')||'<p class="znHint">No hay avisos periódicos.</p>';
  const out=(n.outbox||[]).slice(0,5).map(x=>'<li><span class="znOut" data-s="'+esc(x.status)+'">'+esc({SENT:'Enviado',PENDING:'Pendiente',FAILED:'Fallido',SKIPPED:'Omitido'}[x.status]||x.status)+'</span>'+esc(x.subject)+' <small>'+esc(chLabel[x.channel]||x.channel)+(x.error?' · '+esc(x.error):'')+'</small></li>').join('');
  dialog.innerHTML=head+'<p class="znFeedback" role="status">'+esc(notifyMsg)+'</p><div class="znList znSettings">'+
   '<section><h4>Email</h4><p class="znHint">Desde <b>'+esc(n.email.from)+'</b></p><label class="znField">Enviar a<input type="email" data-field="email.to" value="'+esc(n.email.to||'')+'"></label>'+toggle('email.enabled',n.email.enabled!==false,'Avisos por email activados')+'<div class="znActions znInline"><button type="button" data-action="notify-test" data-channel="email">Enviar prueba</button><button type="button" data-action="notify-report">Enviar resumen ahora</button></div></section>'+
   '<section><h4>Avisos importantes</h4><p class="znHint">Errores, cuentas a reconectar, artículos listos o reels que necesitan tu ayuda, al momento.</p>'+toggle('important.enabled',n.important.enabled!==false,'Avisarme al momento')+'<div class="znChecks">'+['email','whatsapp','call'].map(c=>'<label><input type="checkbox" data-important="'+c+'" '+((n.important.channels||[]).includes(c)?'checked':'')+'> '+chLabel[c]+'</label>').join('')+'</div></section>'+
   '<section><h4>WhatsApp '+(n.whatsapp.configured?'<span class="znOk">conectado</span>':'<span class="znWarn">sin configurar</span>')+'</h4><label class="znField">Tu número<input type="tel" placeholder="+34 600 000 000" data-field="whatsapp.to" value="'+esc(n.whatsapp.to||'')+'"></label>'+(n.whatsapp.configured?'<div class="znActions znInline"><button type="button" data-action="notify-test" data-channel="whatsapp">Enviar prueba</button></div><p class="znHint">Responde a ZAR por WhatsApp con «qué avisos tengo» o «notifícame de … cada …». Si un artículo está listo, puedes publicarlo con un botón.</p>':'<p class="znHint">Falta conectar WhatsApp Business (Meta). Mientras tanto, lo que pidas por WhatsApp te llegará por email.</p>')+'</section>'+
   '<section><h4>Llamadas '+(n.call.configured?'<span class="znOk">conectado</span>':'<span class="znWarn">próximamente</span>')+'</h4><label class="znField">Número para llamadas urgentes<input type="tel" placeholder="+34 600 000 000" data-field="call.to" value="'+esc(n.call.to||'')+'"></label></section>'+
   '<section><h4>Avisos periódicos</h4>'+subs+'<form class="znAdd" data-notify-add><select name="topic" aria-label="Tema">'+Object.entries(n.topics||{}).map(([k,v])=>'<option value="'+esc(k)+'">'+esc(v)+'</option>').join('')+'</select><select name="unit" aria-label="Frecuencia"><option value="week">Cada semana</option><option value="day">Cada día</option><option value="month">Cada mes</option></select><select name="weekday" aria-label="Día">'+DAYS.map((d,i)=>'<option value="'+i+'">'+d+'</option>').join('')+'</select><select name="hour" aria-label="Hora">'+Array.from({length:24},(_,h)=>'<option value="'+h+'" '+(h===9?'selected':'')+'>'+String(h).padStart(2,'0')+':00</option>').join('')+'</select><select name="channel" aria-label="Canal"><option value="email">Email</option><option value="whatsapp">WhatsApp</option></select><button>Añadir aviso</button></form><p class="znHint">También puedes pedírselo a ZAR en el chat: «notifícame de las visitas de ReposNews cada lunes a las 9» o «avísame por whatsapp del precio del bitcoin cada 6 horas».</p></section>'+
   (out?'<section><h4>Últimos envíos</h4><ul class="znOutbox">'+out+'</ul></section>':'')+'</div>';
 }
 async function saveNotify(patch){try{const r=await fetch('/api/notify/settings',{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify(patch)});const j=await r.json();if(!r.ok||!j.ok)throw Error(j.message||'No se pudo guardar.');notify=j.settings;notifyMsg='Guardado.';}catch(x){notifyMsg=x.message;}renderSettings();}
 async function notifyPost(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify(body||{})});const j=await r.json().catch(()=>({}));if(!r.ok||j.ok===false)throw Error(j.message||j.error||'No se pudo completar.');if(j.settings)notify=j.settings;return j;}
 dialog.addEventListener('change',e=>{if(!settingsView)return;const t=e.target;
  if(t.dataset.set){const [g,k]=t.dataset.set.split('.');saveNotify({[g]:{[k]:t.checked}});}
  else if(t.dataset.field){const [g,k]=t.dataset.field.split('.');saveNotify({[g]:{[k]:t.value.trim()}});}
  else if(t.dataset.important){const channels=[...dialog.querySelectorAll('[data-important]:checked')].map(x=>x.dataset.important);saveNotify({important:{channels}});}
 });
 dialog.addEventListener('submit',async e=>{const f=e.target.closest('[data-notify-add]');if(!f)return;e.preventDefault();e.stopImmediatePropagation();const v=Object.fromEntries(new FormData(f));try{await notifyPost('/api/notify/subscriptions',{topic:v.topic,unit:v.unit,every:1,weekday:Number(v.weekday),hour:Number(v.hour),day:1,channel:v.channel});notifyMsg='Aviso añadido.';}catch(x){notifyMsg=x.message;}renderSettings();},true);
 async function post(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify(data)});const j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||'No se pudo completar. Consulta los detalles.');return j;}
 async function refresh(){if(busy)return;busy=true;try{const r=await fetch('/api/notifications');if(!r.ok)return;state=await r.json();csrf=state.csrf;const count=bell.querySelector('[data-unread]');count.hidden=!state.unread;count.textContent=state.unread||'';bell.setAttribute('aria-label','Notificaciones: '+state.unread+' sin leer');if(dialog.open)render();}catch{}finally{busy=false;}}
 function close(){confirmation=null;settingsView=false;dialog.close();bell.setAttribute('aria-expanded','false');bell.focus();}
 async function open(){await refresh();render(true);if(!dialog.open)dialog.showModal();bell.setAttribute('aria-expanded','true');}
 bell.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();dialog.open?close():open();});
 // Only this semantic bell button may open the panel. Containers and cross-frame messages cannot.
 dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)close();}});
 dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
 dialog.addEventListener('keydown',e=>{const row=e.target.closest?.('[data-toggle]');if(row&&(e.key==='Enter'||e.key===' ')){e.preventDefault();row.click();}});
 dialog.addEventListener('change',e=>{if(e.target.matches('[data-sort]')){sort=e.target.value;page=0;remember();render(true);}});
 dialog.addEventListener('input',e=>{const form=e.target.closest('[data-resolve],[data-edit]');if(form)drafts.set(form.dataset.item||form.dataset.resolve||form.dataset.edit,e.target.value);});
 dialog.addEventListener('click',async e=>{
  const row=e.target.closest('[data-toggle]');if(row&&!e.target.closest('a,button,form')){const id=row.dataset.toggle;expanded.has(id)?expanded.delete(id):expanded.add(id);const n=state.items.find(x=>x.id===id);if(n&&!n.read_at&&expanded.has(id)){n.read_at=new Date().toISOString();post('/api/notifications/read',{id,unread:false}).then(refresh).catch(()=>{});}render(true);return;}
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.action==='more'){size+=12;render(true);return;}
  if(b.dataset.action==='settings'){settingsView=true;notifyMsg='';renderSettings();await loadNotify();renderSettings();return;}
  if(b.dataset.action==='settings-back'){settingsView=false;render(true);return;}
  if(['notify-test','notify-report','sub-cancel'].includes(b.dataset.action)){b.disabled=true;try{if(b.dataset.action==='notify-test'){await notifyPost('/api/notify/test',{channel:b.dataset.channel});notifyMsg='Prueba enviada. Revisa tu '+(b.dataset.channel==='email'?'correo':'WhatsApp')+'.';}else if(b.dataset.action==='notify-report'){await notifyPost('/api/notify/report-now');notifyMsg='Resumen enviado a tu correo.';}else{await notifyPost('/api/notify/subscriptions/'+encodeURIComponent(b.dataset.id)+'/cancel');notifyMsg='Aviso cancelado.';}}catch(x){notifyMsg=x.message;}renderSettings();return;}
  if(b.dataset.filter){filter=b.dataset.filter;archived=false;size=12;remember();render(true);return;}
  if(b.dataset.subfilter){subfilter=b.dataset.subfilter;page=0;remember();render(true);return;}
  const action=b.dataset.action,n=state.items.find(x=>x.id===b.dataset.id);
  if(action==='abort'){confirmation=null;render(true);return;}
  if(['publish','update'].includes(action)){const a=n.article||{};confirmation={action,id:n.id,article_id:a.id,entity_id:n.entity_id,title:a.title_es||n.title,revision:a.revision||n.editorial?.revision||'',languages:a.languages||['ES','EN'],approval_request:action==='publish'?a.approval_request:n.approval_request};render(true);dialog.querySelector('[data-action=confirm]')?.focus();return;}
  if(action==='close'){close();return;}if(action==='archive'){archived=!archived;page=0;render(true);return;}
  if(action==='prev'||action==='next'){page+=action==='next'?1:-1;render(true);dialog.querySelector('.znList').scrollTop=0;return;}
  if(action==='modify'){editing=editing===n.id?'':n.id;render(true);dialog.querySelector('[data-edit] textarea')?.focus();return;}
  if(!action||acting)return;b.disabled=true;
  try{
   if(action==='confirm'){if(!confirmation?.approval_request)throw Error('Revisa el borrador antes de confirmar.');acting=true;const c={...confirmation};render(true);try{await post(c.action==='publish'?'/api/reposnews/editorial/decision':'/api/reposnews/revisions/decision',{id:c.action==='publish'?c.article_id:c.entity_id,decision:c.action==='publish'?'PUBLICAR':'ACTUALIZAR',approval_request:c.approval_request});confirmation=null;}finally{acting=false;}}
   else if(action==='allread'||['read','dismiss','restore'].includes(action))await post('/api/notifications/read',action==='allread'?{all:true}:action==='read'?{id:n.id,unread:Boolean(n.read_at)}:{id:n.id,dismissed:action==='dismiss'});
   else if(['publish','cancel'].includes(action))await post('/api/reposnews/editorial/decision',{id:n.article.id,decision:action==='publish'?'PUBLICAR':'CANCELAR',approval_request:n.article.approval_request});
   else if(['update','ignore'].includes(action))await post('/api/reposnews/revisions/decision',{id:n.entity_id,decision:action==='update'?'ACTUALIZAR':'IGNORAR',approval_request:n.approval_request});
   else if(action==='retry')await post('/api/holdings/workflows/reposnews_inbox_recover',{id:n.inbox_item_id||n.editorial?.inbox_item_id||n.entity_id});
   else if(action==='mirror-sync')await post('/api/reposnews/mirror/sync',{});
   message='Acción guardada.';await refresh();render(true);
  }catch(x){message=x.message;render(true);}
 });
 dialog.addEventListener('submit',async e=>{
  const form=e.target.closest('[data-resolve],[data-edit]');if(!form)return;e.preventDefault();const n=state.items.find(x=>x.id===(form.dataset.resolve||form.dataset.edit));const values=Object.fromEntries(new FormData(form));form.querySelector('button').disabled=true;
  try{if(form.dataset.resolve)await post('/api/holdings/workflows/reposnews_inbox_resolve',{id:form.dataset.item||n.inbox_item_id||n.editorial?.inbox_item_id||n.entity_id,name:values.project});else await post('/api/reposnews/editorial/modify',{id:n.article.id,instruction:values.instruction});
   drafts.delete(form.dataset.item||n.id);editing='';message='ZAR continúa el trabajo. Te avisará cuando termine.';await refresh();render(true);
  }catch(x){message=x.message;render(true);}
 });
 refresh();setInterval(refresh,20000);
})();
