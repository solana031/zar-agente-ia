/* Read-only dry-run, then one explicit confirmation for the exact render. */
(()=>{
 const root=document.getElementById('videoPublication');if(!root)return;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const names={instagram:'Instagram Reels',tiktok:'TikTok',youtube:'YouTube Shorts'};
 const states={QUEUED:'En cola para envío confirmado',REQUESTED:'Enviando',PENDING:'Procesando en la red',PUBLISHED:'Publicado',UPLOADED_PRIVATE:'Subido como privado',UPLOADED_UNLISTED:'Subido como no listado',UNKNOWN:'Resultado incierto · revisar la cuenta',FAILED:'La red no completó la publicación',BLOCKED:'Bloqueado antes de enviar',CANCELLED:'Cancelado'};
 const reason=code=>{if(!code)return 'Acceso verificado para preparar el envío';if(code.includes('CONTENT_PUBLISH'))return 'Falta verificar el permiso para publicar en esta cuenta de Instagram.';return ({INSTAGRAM_NOT_CONNECTED:'Instagram no tiene una conexión disponible para publicar.',TIKTOK_NOT_CONNECTED:'TikTok no está conectado.',YOUTUBE_CHANNEL_OR_UPLOAD_PERMISSION_NOT_VERIFIED:'No se ha verificado el canal o el permiso de subida de YouTube.',SELECT_AUTHORIZED_TIKTOK_PRIVACY_OR_REVIEW_DURATION:'Selecciona una privacidad autorizada para TikTok y revisa su duración máxima.',PUBLICATION_ALREADY_REQUESTED_CHECK_EXISTING_RESULT:'Este proyecto ya tiene un envío registrado en esa red; consulta su resultado.',VIDEO_CHANGED_REVIEW_EXACT_RENDER_AGAIN:'El vídeo ha cambiado. Revisa el nuevo render y prepara otra comprobación.',SOCIAL_APPROVAL_EXPIRED_OR_INVALID:'La revisión ha caducado. Comprueba de nuevo las redes.',GLOBAL_STOP_ACTIVE:'ZAR está detenido; el envío permanece bloqueado.',VERIFIED_PRIVATE_VIDEO_REQUIRED:'Espera a que el vídeo privado esté verificado.'})[code]||'La red no ha confirmado que pueda completar esta operación. Consulta el detalle.';};
 let plan=null,busy=false,project=null,connectionState={};
 root.innerHTML='<form data-social-form><fieldset><legend>Redes de destino</legend>'+Object.entries(names).map(([k,v])=>'<label class="tvPlatform"><input type="checkbox" name="platform" value="'+k+'">'+v+'</label>').join('')+'</fieldset><label>Título<input name="title" maxlength="100" required></label><label>Texto de publicación<textarea name="caption" maxlength="2200" rows="4"></textarea></label><div class="tvGrid"><label>Privacidad de YouTube<select name="youtube_privacy" aria-label="Privacidad de YouTube"><option value="private">Privado</option><option value="unlisted">No listado</option><option value="public">Público</option></select></label><label>Privacidad de TikTok<select name="tiktok_privacy" aria-label="Privacidad de TikTok"><option value="">Elige una opción</option><option value="SELF_ONLY">Solo yo</option><option value="PUBLIC_TO_EVERYONE">Público</option><option value="MUTUAL_FOLLOW_FRIENDS">Amigos mutuos</option><option value="FOLLOWER_OF_CREATOR">Seguidores</option></select></label></div><button type="button" data-social-prepare>Comprobar redes · no publica</button><div data-social-checks></div><label class="tvPlatform"><input type="checkbox" name="rights">He revisado este vídeo y los derechos de sus imágenes, voz y música.</label><button type="submit" disabled data-social-confirm>Confirmar publicación en las redes seleccionadas</button></form><p role="status" data-social-feedback></p><details hidden data-social-diagnostic><summary>Ver detalle del bloqueo</summary><p></p></details><h3>Resultado por red</h3><div data-social-results></div>';
 const form=root.querySelector('form'),feedback=root.querySelector('[data-social-feedback]'),confirm=root.querySelector('[data-social-confirm]');
 const center=document.createElement('section');center.id='zarSocialConnections';root.prepend(center);
 for(const checkbox of form.querySelectorAll('[name=platform]'))checkbox.disabled=true;
 async function verifyConnections(){
  center.textContent='Verificando conexiones sociales · solo lectura';
  try{const j=await videoPost('/api/social/connections/readiness',{});connectionState=j.result;
   center.innerHTML='<h3>Conexiones · CUENTAS</h3>'+Object.entries(names).map(([p,name])=>{const c=connectionState[p],account=c.channel?.title||c.account||'Sin verificar';const label=c.connected?'✓ CONECTADA':c.status==='REAUTH_REQUIRED'?'REQUIERE RECONEXIÓN':'SIN CONEXIÓN';return '<article class="tvCard"><h4>'+esc(name)+'</h4><p>'+label+' · '+esc(account)+'</p>'+(c.ready?'<p>Permiso de publicación verificado · requiere tu confirmación</p>':'<p>'+esc(c.human_action||'Revisa esta cuenta')+'</p>')+'<a href="/accounts#'+p+'">'+(c.connected?'VER CUENTA':p==='instagram'?'RECONECTAR':p==='tiktok'?'CONECTAR TIKTOK':'CONECTAR YOUTUBE')+'</a></article>';}).join('')+'<button type="button" data-reverify>REVERIFICAR CONEXIONES</button>';
   for(const checkbox of form.querySelectorAll('[name=platform]')){checkbox.disabled=!connectionState[checkbox.value]?.ready;if(checkbox.disabled)checkbox.checked=false;}
   const privacy=form.elements.tiktok_privacy,allowed=connectionState.tiktok?.privacy_options||[];for(const option of privacy.options)if(option.value)option.disabled=!allowed.includes(option.value);
   center.querySelector('[data-reverify]').onclick=verifyConnections;
  }catch(e){center.textContent='UNKNOWN · No se pudo verificar la conexión. '+e.message;}
 }
 window.addEventListener('focus',()=>{if(busy)return;plan=null;validity();verifyConnections();});
 window.addEventListener('zar-accounts-changed',()=>{plan=null;validity();verifyConnections();});
 function options(){return {platforms:[...form.querySelectorAll('[name=platform]:checked')].map(x=>x.value),title:form.elements.title.value,caption:form.elements.caption.value,youtube_privacy:form.elements.youtube_privacy.value,tiktok_privacy:form.elements.tiktok_privacy.value};}
 function validity(){confirm.disabled=busy||!plan?.ready_to_publish||!options().platforms.length||!form.elements.rights.checked;}
 function error(e){feedback.textContent=reason(e.message);const detail=root.querySelector('[data-social-diagnostic]');detail.hidden=false;detail.querySelector('p').textContent=e.message;}
 form.oninput=form.onchange=e=>{if(e.target.name!=='rights')plan=null;validity();};
 root.querySelector('[data-social-prepare]').onclick=async e=>{
  if(busy)return;busy=true;e.target.disabled=true;validity();feedback.textContent='Comprobando accesos, cuenta y privacidad. No se sube ningún vídeo.';
  try{
   const selected=options();if(!selected.platforms.length)selected.platforms=Object.keys(names);
   const j=await videoPost('/api/video-projects/'+videoId+'/social/prepare',selected);plan=j.result;
   root.querySelector('[data-social-checks]').innerHTML=Object.entries(plan.checks).map(([platform,c])=>'<article class="tvCard"><h4>'+esc(names[platform])+'</h4><p>'+esc(c.ready?'Preparado para tu confirmación':'Acción pendiente')+'</p><p>'+esc(typeof c.account==='object'?c.account?.title||'Cuenta sin verificar':c.account||'Cuenta sin verificar')+'</p><p>'+esc(reason(c.blocker))+'</p><p>Privacidad: '+esc(c.privacy||'Sin seleccionar')+'</p>'+(c.blocker?'<details><summary>Ver detalle</summary><p>'+esc(c.blocker)+'</p></details>':'')+'</article>').join('');
   if(plan.validation){const v=plan.validation;root.querySelector('[data-social-checks]').insertAdjacentHTML('afterbegin','<p>Vídeo verificado: '+esc(v.duration)+' s · '+esc(v.width)+'×'+esc(v.height)+' · '+esc(v.codec)+'/'+esc(v.audio_codec)+' · '+esc(v.size)+' bytes</p>');}
   feedback.textContent=plan.ready_to_publish?'Revisa el vídeo y los destinos. El botón de confirmación autoriza un único envío a cada red seleccionada.':'Hay destinos pendientes. Revisa sus bloqueos o selecciona únicamente las redes disponibles y comprueba de nuevo.';
  }catch(x){plan=null;error(x);}finally{busy=false;e.target.disabled=false;validity();}
 };
 form.onsubmit=async e=>{
  e.preventDefault();if(busy||!plan?.ready_to_publish||!form.elements.rights.checked)return;
  busy=true;validity();
  if(!window.confirm('Publicar '+form.elements.title.value+' en: '+plan.options.platforms.map(p=>names[p]).join(', ')+'?')){busy=false;validity();return;}
  try{await videoPost('/api/video-projects/'+videoId+'/social/confirm',{approval_request:plan.approval_request,options:options(),confirmed:true,rights_confirmed:true});plan=null;feedback.textContent='Confirmación guardada. Los envíos se procesan por separado; recibirás el resultado en la campana.';await refresh();}catch(x){error(x);}finally{busy=false;validity();}
 };
 async function refresh(){
  try{const r=await fetch('/api/video-projects'),j=await r.json();if(!r.ok||!j.ok)return;const next=j.projects.find(p=>p.id===videoId);if(!next)return;
   if(!project){form.elements.title.value=(next.title||next.project?.title||'Vídeo ZAR').slice(0,100);form.elements.caption.value='';}project=next;
   root.querySelector('[data-social-results]').innerHTML=Object.entries(project.publication||{}).map(([platform,p])=>'<article class="tvCard"><h4>'+esc(names[platform])+'</h4><p>'+esc(states[p.status]||p.status)+'</p>'+(p.url&&/^https:\/\/(www\.)?(youtube\.com|instagram\.com|tiktok\.com)\//.test(p.url)?'<a href="'+esc(p.url)+'" target="_blank" rel="noopener">Ver en la red</a>':'')+(p.external_id?'<p>Referencia: '+esc(p.external_id)+'</p>':'')+(p.error?'<details><summary>Ver detalle</summary><p>'+esc(p.error)+'</p></details>':'')+'</article>').join('')||'<p>No hay envíos confirmados para este proyecto.</p>';
  }catch{}
 }
 refresh();verifyConnections();setInterval(()=>{if(!document.hidden&&!busy)refresh();},5000);
})();
