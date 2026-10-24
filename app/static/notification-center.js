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
 let state={items:[],historical:{}},csrf='',filter=saved.filter||'TODAS',subfilter=saved.subfilter||'TODAS',sort=saved.sort||'RECIENTES',page=0,busy=false,message='',editing='',archived=false,confirmation=null,acting=false;
 const filters=['TODAS','NO LEÍDAS','REQUIEREN ACCIÓN','REPOSNEWS','SOCIAL','CUENTAS','SISTEMA'];
 const subfilters=['TODAS','PARA PUBLICAR','ACTUALIZACIONES','NECESITAN REVISIÓN','PUBLICADAS','CANCELADAS','ERRORES'];
 const remember=()=>{try{sessionStorage.setItem('zar-notification-view',JSON.stringify({filter,subfilter,sort}));}catch{}};
 const drafts=new Map(),expanded=new Set(),size=8;
 const dialog=document.createElement('dialog');dialog.id='zarNotificationCenter';dialog.setAttribute('aria-label','Centro de notificaciones ZAR');document.body.append(dialog);
 const bell=document.createElement('button');bell.type='button';bell.id='zarNotificationBell';bell.className='topIconBtn';bell.setAttribute('aria-label','Notificaciones');bell.setAttribute('aria-haspopup','dialog');bell.setAttribute('aria-expanded','false');bell.innerHTML=icon+'<span data-unread hidden></span>';
 const slot=document.createElement('div');slot.className='znBellSlot';slot.append(bell);
 (new URLSearchParams(location.search).has('zar_workspace')?document.body:document.querySelector('.topActions')||document.body).prepend(slot);
 Object.assign(labels,{ARTICLE_COVER_GENERATED:'Portada preparada',ARTICLE_COVER_FAILED:'Portada pendiente'});
 const group=n=>n.category||(/^ARTICLE|INSTAGRAM_HISTORY/.test(n.type)?'REPOSNEWS':/^SOCIAL|VIDEO_/.test(n.type)?'SOCIAL':n.type==='ACCOUNT_CONNECTION'?'CUENTAS':'SISTEMA');
 const required=n=>n.requires_action??(!n.completed&&!n.processing&&(/ARTICLE_READY|ARTICLE_UPDATE_READY|ACTION|FAILED|OFFLINE|EXPIRED/.test(n.type+' '+n.status)));
 const rnfilter=n=>n.repos_filter||(n.type==='ARTICLE_UPDATE_READY'?'ACTUALIZACIONES':n.type==='ARTICLE_READY'&&!n.completed?'PARA PUBLICAR':'NECESITAN REVISIÓN');
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
  }else if(n.type==='ARTICLE_NEEDS_DISAMBIGUATION'&&!n.completed){
   if(d.reel)actions=link(d.reel,'Ver Reel');
   form='<form data-resolve="'+esc(n.id)+'"><label>Nombre de herramienta<input name="project" maxlength="80" required value="'+esc(drafts.get(n.id)||'')+'"></label><button>Continuar</button></form>';
  }else if(n.type==='ARTICLE_FAILED'&&!n.completed){actions=d.status==='FAILED_PERMANENT'?'':button('retry',n.id,'Reintentar');if(d.reel)actions+=link(d.reel,'Ver Reel');}
  else if(n.type==='MIRROR_SYNC_FAILED'&&!n.completed)actions=button('mirror-sync',n.id,'REINTENTAR MIRROR')+link(n.deep_link,'VER DETALLES');
  else actions=(n.actions||[{label:'Ver',url:n.deep_link}]).filter(x=>x.url).map(x=>link(x.url,x.label)).join('');
  const at=n.created_at?new Date(n.created_at):null,time=at&&!isNaN(at)?at.toLocaleString('es-ES',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'';
  const detail={estado:n.status,etapa:d.failed_stage,intentos:d.attempts,error:d.diagnostic};
  const cover=a?(a.cover||a.cover_thumb):d.hero||d.image;
  const visual=a?'<div class="znCover">'+(cover?'<img src="'+esc(safe(cover))+'" alt="Portada de '+esc(a.title_es||n.title)+'" loading="lazy" decoding="async">':'<span class="znSkeleton" role="status">'+esc(a.cover_status==='COVER_GENERATION_FAILED'?'Portada pendiente · error del proveedor':'Preparando portada…')+'</span>')+'</div>':'';
  const changes=n.changes?'<dl class="znChanges">'+Object.entries({ADDED:'Añadido',UPDATED:'Actualizado',REMOVED:'Eliminado'}).map(([k,v])=>'<div><dt>'+v+'</dt><dd>'+esc((n.changes[k]||[]).join(', ')||'—')+'</dd></div>').join('')+'</dl>':'';
  return '<article class="znCard" data-note="'+esc(n.id)+'" data-priority="'+c+'" data-unread="'+!n.read_at+'">'+visual+
   '<div class="znMeta"><span class="znType">'+icon+esc(n.processing?'Reel en proceso':labels[n.type]||'Notificación')+'</span><time datetime="'+esc(n.created_at)+'">'+esc(time)+'</time></div>'+
   '<p class="znCategory">'+esc(group(n))+(n.type==='ARTICLE_UPDATE_READY'?' · ARTÍCULO EXISTENTE':'')+'</p><h3>'+esc(a?.title_es||(n.processing?'Reanalizando el Reel':n.title||labels[n.type]||'Notificación'))+'</h3><p class="znMessage">'+esc(n.processing?'ZAR está revisando de nuevo este Reel. Te avisará cuando termine.':a?.summary_es||short(n))+'</p>'+changes+(a?'<p class="znArticleMeta">'+esc((a.languages||['ES','EN']).join(' / ')+' · '+(a.repo||'')+' · '+(a.state||''))+'</p>':'')+
   '<span class="znStatus">'+esc(n.dismissed_at?'Archivada':n.processing?'En proceso':n.completed?'Completada':c==='ERROR'?'Requiere revisión':c==='READY'?'Lista para revisar':c==='ACTION_REQUIRED'?'Pendiente':'Información')+'</span>'+
   '<div class="znActions">'+actions+'</div>'+form+
   '<details data-details="'+esc(n.id)+'" '+(expanded.has(n.id)?'open':'')+'><summary>Ver detalles</summary>'+
   (d.hero||d.image?'<img src="'+esc(safe(d.hero||d.image))+'" alt="Visual de la propuesta" loading="lazy">':'')+
   (d.reel?link(d.reel,'Ver Reel original'):'')+'<pre>'+esc(JSON.stringify(detail,null,2))+'</pre></details>'+
   '<div class="znUtility">'+button('read',n.id,n.read_at?'Marcar no leída':'Marcar leída')+button(n.dismissed_at?'restore':'dismiss',n.id,n.dismissed_at?'Recuperar':'Archivar')+'</div></article>';
 }
 function render(force=false){
  if(!force&&dialog.contains(document.activeElement)&&/INPUT|TEXTAREA/.test(document.activeElement.tagName))return;
  const scrollTop=dialog.querySelector('.znList')?.scrollTop||0;
  dialog.querySelectorAll('[data-details]').forEach(d=>d.open?expanded.add(d.dataset.details):expanded.delete(d.dataset.details));
  const notes=state.items.filter(n=>archived?Boolean(n.dismissed_at):!n.dismissed_at&&(filter==='TODAS'||filter==='NO LEÍDAS'&&!n.read_at||filter==='REQUIEREN ACCIÓN'&&required(n)||group(n)===filter)&&(filter!=='REPOSNEWS'||subfilter==='TODAS'||rnfilter(n)===subfilter));
  notes.sort((a,b)=>sort==='ANTIGUAS'?String(a.created_at||'').localeCompare(b.created_at||''):sort==='PRIORIDAD'?String(a.priority||'P2').localeCompare(b.priority||'P2')||String(b.created_at||'').localeCompare(a.created_at||''):String(b.created_at||'').localeCompare(a.created_at||''));
  page=Math.min(page,Math.max(0,Math.ceil(notes.length/size)-1));
  dialog.innerHTML='<header class="znHeader"><div><span class="znEyebrow">TU BANDEJA DE ACCIONES</span><h2>Notificaciones <small>'+esc(state.unread||0)+' sin leer</small></h2></div>'+button('close','','Cerrar','data-close aria-label="Cerrar notificaciones"')+'</header>'+
   '<nav class="znTabs" aria-label="Filtrar notificaciones">'+filters.map(t=>'<button data-filter="'+t+'" aria-pressed="'+(t===filter&&!archived)+'">'+t+' <small>'+esc(state.counts?.[t]??state.items.filter(n=>!n.dismissed_at&&(t==='TODAS'||t==='NO LEÍDAS'&&!n.read_at||t==='REQUIEREN ACCIÓN'&&required(n)||group(n)===t)).length)+'</small></button>').join('')+'</nav>'+(filter==='REPOSNEWS'?'<nav class="znTabs znSubTabs" aria-label="Filtrar ReposNews">'+subfilters.map(t=>'<button data-subfilter="'+t+'" aria-pressed="'+(t===subfilter)+'">'+t+'</button>').join('')+'</nav>':'')+
   '<div class="znToolbar"><label>Orden <select data-sort aria-label="Ordenar notificaciones">'+[['RECIENTES','Más recientes'],['ANTIGUAS','Más antiguas'],['PRIORIDAD','Prioridad']].map(([v,l])=>'<option value="'+v+'" '+(sort===v?'selected':'')+'>'+l+'</option>').join('')+'</select></label>'+button('allread','','Marcar todo como leído')+button('archive','','Archivadas','aria-pressed="'+archived+'"')+'</div>'+
   (confirmation?'<section class="znConfirm" role="region" aria-label="Confirmar publicación"><h3>'+esc(confirmation.action==='publish'?'Publicar esta revisión en ReposNews':'Actualizar esta revisión en ReposNews')+'</h3><p>'+esc(confirmation.title)+'</p><p>Revisión: <code>'+esc(confirmation.revision)+'</code></p><p>Idiomas: '+esc(confirmation.languages.join(' / '))+' · Destino: www.reposnews.com</p>'+button('confirm','','Confirmar publicación',acting?'disabled':'')+button('abort','','Volver',acting?'disabled':'')+'</section>':'')+'<p class="znFeedback" role="status">'+esc(message)+'</p><div class="znList">'+(notes.slice(page*size,(page+1)*size).map(card).join('')||'<p class="znEmpty">No hay notificaciones en este filtro.</p>')+'</div>'+
   '<footer class="znFooter">'+button('prev','','Anterior',page?'':'disabled')+'<span>'+ (notes.length?page*size+1:0)+'–'+Math.min((page+1)*size,notes.length)+' de '+notes.length+'</span>'+button('next','','Siguiente',(page+1)*size<notes.length?'':'disabled')+'</footer>';
  dialog.querySelector('.znList').scrollTop=scrollTop;
 }
 async function post(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify(data)});const j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||'No se pudo completar. Consulta los detalles.');return j;}
 async function refresh(){if(busy)return;busy=true;try{const r=await fetch('/api/notifications');if(!r.ok)return;state=await r.json();csrf=state.csrf;const count=bell.querySelector('[data-unread]');count.hidden=!state.unread;count.textContent=state.unread||'';bell.setAttribute('aria-label','Notificaciones: '+state.unread+' sin leer');if(dialog.open)render();}catch{}finally{busy=false;}}
 function close(){confirmation=null;dialog.close();bell.setAttribute('aria-expanded','false');bell.focus();}
 async function open(){await refresh();render(true);if(!dialog.open)dialog.showModal();bell.setAttribute('aria-expanded','true');}
 bell.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();dialog.open?close():open();});
 // Only this semantic bell button may open the panel. Containers and cross-frame messages cannot.
 dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)close();}});
 dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
 dialog.addEventListener('change',e=>{if(e.target.matches('[data-sort]')){sort=e.target.value;page=0;remember();render(true);}});
 dialog.addEventListener('input',e=>{const form=e.target.closest('[data-resolve],[data-edit]');if(form)drafts.set(form.dataset.resolve||form.dataset.edit,e.target.value);});
 dialog.addEventListener('click',async e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.filter){filter=b.dataset.filter;archived=false;page=0;remember();render(true);return;}
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
  try{if(form.dataset.resolve)await post('/api/holdings/workflows/reposnews_inbox_resolve',{id:n.inbox_item_id||n.editorial?.inbox_item_id||n.entity_id,name:values.project});else await post('/api/reposnews/editorial/modify',{id:n.article.id,instruction:values.instruction});
   drafts.delete(n.id);editing='';message='ZAR continúa el trabajo. Te avisará cuando termine.';await refresh();render(true);
  }catch(x){message=x.message;render(true);}
 });
 refresh();setInterval(refresh,20000);
})();
