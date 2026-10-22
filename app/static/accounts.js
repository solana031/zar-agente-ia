(()=>{
 const host=document.getElementById('providers'),notice=document.getElementById('notice');
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const labels={CONNECTED:'✓ CONECTADA',UPLOAD_READY:'✓ CONECTADA',PARTIAL:'CONECTADA PARCIALMENTE',AUTH_REQUIRED:'SIN CONEXIÓN',REAUTH_REQUIRED:'REQUIERE RECONEXIÓN',PERMISSION_REQUIRED:'FALTAN PERMISOS',CHANNEL_REQUIRED:'FALTA VERIFICAR EL CANAL',DISCONNECTED:'SIN CONEXIÓN',ERROR:'ERROR DE CONEXIÓN',UNKNOWN:'SIN VERIFICAR'};
 const capNames={messaging:'Mensajes',reel_discovery:'Recepción de Reels',publishing:'Publicación',channel:'Canal',identity:'Identidad',GMAIL:'Gmail',DRIVE:'Drive',DOCS:'Docs',SHEETS:'Sheets',SLIDES:'Slides',FORMS:'Forms',CALENDAR:'Calendar',CONTACTS:'Contacts',TASKS:'Tasks'};
 const good=c=>['CONNECTED','UPLOAD_READY','PARTIAL'].includes(c.status);
 const attention=c=>!['CONNECTED','UPLOAD_READY','UNKNOWN'].includes(c.status);
 let providers=[],csrf='',filter='all',checking=false;
 const webview=/Android/i.test(navigator.userAgent)&&(/; wv[);]/i.test(navigator.userAgent)||/Version\/4\.0.*Chrome/i.test(navigator.userAgent));
 let oauthTimer=null;
 function stopOAuth(){clearTimeout(oauthTimer);oauthTimer=null;sessionStorage.removeItem('zar-accounts-oauth');document.getElementById('oauthHandoff')?.remove();}
 async function pollOAuth(){
  const saved=JSON.parse(sessionStorage.getItem('zar-accounts-oauth')||'null');if(!saved)return;
  if(Date.now()>saved.expires){stopOAuth();notice.textContent='La conexión ha caducado. Puedes iniciarla de nuevo.';return;}
  if(!document.hidden){try{
   const r=await fetch('/api/accounts/oauth/status/'+encodeURIComponent(saved.id),{cache:'no-store'});const j=await r.json();
   if(j.status!=='PENDING'){stopOAuth();await load();notice.textContent=j.status==='CONNECTED'?'Conexión completada.':'Conexión cancelada o no completada. Puedes reintentarlo desde CUENTAS.';return;}
  }catch(e){notice.textContent='Esperando la conexión del navegador. Vuelve a ZAR al terminar.';}}
  clearTimeout(oauthTimer);oauthTimer=setTimeout(pollOAuth,3000);
 }
 function openExternal(j){
  stopOAuth();sessionStorage.setItem('zar-accounts-oauth',JSON.stringify({id:j.poll_id,expires:Date.now()+600000}));
  const u=new URL(j.url);if(u.protocol!=='https:'||u.origin!==location.origin)throw Error('Origen OAuth no válido.');
  const intent='intent://'+u.host+u.pathname+'#Intent;scheme=https;action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;package=com.android.chrome;S.browser_fallback_url='+encodeURIComponent(u.href)+';end';
  const box=document.createElement('div');box.id='oauthHandoff';
  const link=document.createElement('a');link.textContent='ABRIR NAVEGADOR SEGURO';link.href=intent;
  const cancel=document.createElement('button');cancel.textContent='CANCELAR';cancel.onclick=()=>{stopOAuth();notice.textContent='Conexión cerrada en ZAR.';};
  box.append(link,' ',cancel);notice.after(box);notice.textContent='Conectando… Termina en Chrome y vuelve a ZAR. Si no se abre, pulsa ABRIR NAVEGADOR SEGURO.';
  location.assign(intent);pollOAuth();
 }
 window.addEventListener('pagehide',()=>clearTimeout(oauthTimer));
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollOAuth();});
 function elapsed(value){if(!value)return 'Sin verificación todavía';const seconds=Math.max(0,(Date.now()-Date.parse(value))/1000);if(!Number.isFinite(seconds))return 'Sin verificación todavía';return 'Verificado '+(seconds<60?'ahora':seconds<3600?'hace '+Math.floor(seconds/60)+' min':seconds<86400?'hace '+Math.floor(seconds/3600)+' h':'hace '+Math.floor(seconds/86400)+' días');}
 function render(){
  document.getElementById('summary').textContent=providers.filter(good).length+' conectadas · '+providers.filter(attention).length+' requieren atención · '+providers.filter(c=>c.status==='UNKNOWN').length+' sin verificar';
  const selected=providers.filter(c=>filter==='all'||(filter==='connected'?good(c):attention(c)));
  host.innerHTML=[...new Set(selected.map(c=>c.category))].map(category=>'<section><h2 class="category">'+esc(category)+'</h2><div class="grid">'+selected.filter(c=>c.category===category).map(c=>{
   const connected=good(c),reconnect=['REAUTH_REQUIRED','PERMISSION_REQUIRED','PARTIAL','ERROR'].includes(c.status);
   const caps=Object.entries(c.capabilities||{}).map(([k,v])=>'<span class="capability '+(v==='READY'?'ready':'')+'">'+esc(capNames[k]||k)+' · '+(v==='READY'?'✓':v==='ERROR'?'Error':v==='PERMISSION_REQUIRED'?'Faltan permisos':'Por verificar')+'</span>').join('');
   return '<article class="card" id="'+esc(c.id)+'"><div class="cardHead"><span class="icon" aria-hidden="true">'+esc(c.icon)+'</span><h2>'+esc(c.name)+'</h2><button class="menu" data-menu="'+esc(c.id)+'" aria-label="Opciones de '+esc(c.name)+'" aria-expanded="false">⋯</button></div><p class="identity">'+esc(c.account_identity||c.store||'Identidad pendiente de verificar')+'</p><p class="status '+(connected?'good':'')+'">'+esc(labels[c.status]||labels.UNKNOWN)+'</p>'+ (c.channel?'<p class="identity">'+esc(c.channel.title)+'<br><small>'+esc(c.channel.id)+'</small></p>':'')+'<div class="capabilities">'+caps+'</div><p class="actionText">'+esc(c.human_action||(connected?'Acceso verificado para los servicios indicados.':'Comprueba esta cuenta para completar la conexión.'))+'</p><p class="used">Usado por: '+esc(c.used_by.join(' · '))+'</p><p class="verified">'+esc(elapsed(c.last_verified))+'</p><div class="actions">'+(!connected||c.status==='PARTIAL'?'<button class="primary" data-provider="'+esc(c.id)+'" data-action="'+(reconnect?'reconnect':'connect')+'">'+(reconnect?'RECONECTAR':'CONECTAR')+'</button>':'')+'<button data-provider="'+esc(c.id)+'" data-action="reverify">REVERIFICAR</button></div><div class="menuPanel" data-options="'+esc(c.id)+'" hidden><button data-provider="'+esc(c.id)+'" data-action="reconnect">Reconectar</button><button data-details="'+esc(c.id)+'">Ver permisos</button></div><details class="details"><summary>Ver detalles</summary><pre>'+esc(JSON.stringify({status:c.status,kind:c.kind,account_id:c.account_id,store:c.store,last_verified:c.last_verified,permissions:c.permissions,capabilities:c.capabilities,diagnostic:c.diagnostic},null,2))+'</pre></details></article>';
  }).join('')+'</div></section>').join('')||'<p>No hay cuentas en este filtro.</p>';
  if(location.hash){const card=document.getElementById(decodeURIComponent(location.hash.slice(1)));card?.scrollIntoView({block:'start'});}
 }
 async function load(){const r=await fetch('/api/accounts/connections',{cache:'no-store'});if(!r.ok)throw Error(r.status===401?'Inicia sesión en ZAR para ver tus cuentas.':'No se pudo leer el estado de las cuentas.');const j=await r.json();csrf=j.csrf;providers=j.providers;render();}
 async function action(id,operation){
  const r=await fetch('/api/accounts/connections/'+encodeURIComponent(id)+'/'+operation,{method:'POST',headers:{'X-ZAR-Business-CSRF':csrf,'Content-Type':'application/json'},body:JSON.stringify({external:webview&&['google','instagram'].includes(id)&&operation!=='reverify'})});const j=await r.json();if(!r.ok)throw Error(j.message||'No se pudo completar la comprobación.');
  if(operation==='reverify'){const i=providers.findIndex(c=>c.id===id);providers[i]={...providers[i],...j.result};render();return;}
  if(j.external){openExternal(j);return;}
  if(j.assistant){assistant(j.assistant);return;}
  // The server supplies only existing same-origin authorization routes.
  const url=new URL(j.url,location.origin);if(url.origin!==location.origin)throw Error('La autorización requiere revisar el proveedor.');location.assign(url.href);
 }
 const instructions={
  tiktok:{title:'Conectar TikTok',text:'ZAR utiliza la app de TikTok existente y un acceso guardado en el servidor. Todavía no hay OAuth de TikTok dentro de ZAR.',url:'https://developers.tiktok.com/apps/',steps:['Abre TikTok Developers con la cuenta responsable y selecciona la app existente de ZAR. No crees otra app.','Comprueba que Content Posting API y el permiso video.publish estén aprobados y autoriza la cuenta operativa @zaragente031 mediante el flujo de esa app.','Guarda el acceso autorizado como TIKTOK_ACCESS_TOKEN en las variables protegidas del servicio web de energetic-charisma. Si falta la autorización o la revisión de la app, completa primero ese paso en TikTok.','Vuelve a CUENTAS y pulsa REVERIFICAR. Solo una respuesta válida de creator_info confirma la cuenta y sus opciones de publicación.']},
  shopify:{title:'Conectar Shopify',text:'Reutiliza la tienda y su integración Admin API existentes. Esta conexión se configura en el servidor.',url:'https://admin.shopify.com/',steps:['Abre la tienda existente y su aplicación de integración ZAR autorizada. No crees una tienda ni inicies una compra.','Comprueba el dominio real *.myshopify.com y el acceso Admin API concedido a la aplicación existente.','Guarda SHOPIFY_SHOP_DOMAIN y SHOPIFY_ADMIN_ACCESS_TOKEN en las variables protegidas del servicio web de energetic-charisma.','Vuelve a CUENTAS y pulsa REVERIFICAR: ZAR leerá únicamente la identidad de tienda y los permisos de la instalación.']},
  stripe:{title:'Revisar Stripe',text:'La integración existente utiliza acceso protegido del servidor.',url:'https://dashboard.stripe.com/',steps:['Abre la cuenta Stripe ya utilizada por Web Agency.','Revisa su acceso de servidor y configura STRIPE_SECRET_KEY exclusivamente en Railway principal.','Pulsa REVERIFICAR. La comprobación lee la identidad de cuenta; no crea pagos.']}
 };
 function assistant(id){const data=instructions[id];if(!data)return;const dialog=document.getElementById('assistant');dialog.querySelector('h2').textContent=data.title;dialog.querySelector('p').textContent=data.text;dialog.querySelector('ol').innerHTML=data.steps.map(s=>'<li>'+esc(s)+'</li>').join('');dialog.querySelector('a').href=data.url;dialog.showModal();}
 document.getElementById('assistant').querySelector('button').onclick=()=>document.getElementById('assistant').close();
 document.addEventListener('click',async e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.filter){filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));render();return;}
  if(b.dataset.menu){const options=host.querySelector('[data-options="'+b.dataset.menu+'"]');options.hidden=!options.hidden;b.setAttribute('aria-expanded',String(!options.hidden));return;}
  if(b.dataset.details){const d=document.getElementById(b.dataset.details).querySelector('details');d.open=true;return;}
  if(!b.dataset.action||checking)return;checking=true;b.disabled=true;notice.textContent=b.dataset.action==='reverify'?'Comprobando la cuenta · solo lectura…':'Abriendo conexión…';
  try{await action(b.dataset.provider,b.dataset.action);if(!sessionStorage.getItem('zar-accounts-oauth'))notice.textContent='Estado actualizado.';}catch(err){notice.textContent=err.message;}finally{checking=false;b.disabled=false;}
 });
 async function verifyAll(unknownOnly=false){if(checking)return;checking=true;const b=document.getElementById('verifyAll');b.disabled=true;try{for(const provider of providers.filter(c=>!unknownOnly||c.status==='UNKNOWN')){notice.textContent='Comprobando '+provider.name+' · solo lectura…';await action(provider.id,'reverify');}notice.textContent='Comprobación terminada.';}catch(err){notice.textContent=err.message;}finally{b.disabled=false;checking=false;}}
 document.getElementById('verifyAll').onclick=()=>verifyAll();
 window.addEventListener('focus',()=>{if(!checking)load().catch(e=>notice.textContent=e.message);});
 window.addEventListener('hashchange',()=>{filter='all';render();});
 window.addEventListener('message',e=>{if(e.origin===location.origin&&e.data?.type==='zar-oauth-success'&&!checking)verifyAll();});
 load().then(()=>sessionStorage.getItem('zar-accounts-oauth')?pollOAuth():verifyAll(true)).catch(e=>notice.textContent=e.message);
})();
