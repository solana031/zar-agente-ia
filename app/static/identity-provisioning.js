/* Public metadata only. Signup and interactive checks remain on official providers. */
(()=>{
 let csrf='',snapshot,signature='';
 const esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const input=(name,label,value='')=>`<label>${label}<input name="${name}" value="${esc(value)}"></label>`;
 async function post(action,data){const r=await fetch('/api/holdings/workflows/identity_provision_'+action,{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify(data)});const j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||'Identidad no verificada');return j.result;}
 function render(j){
  const parent=document.getElementById('orchestrationWorkspaceInner');if(!parent||!j.identity)return;csrf=j.csrf;snapshot=j.identity;
  let host=document.getElementById('zarIdentityCenter');if(!host){host=document.createElement('section');host.id='zarIdentityCenter';host.className='workspaceCard';parent.append(host);}
  if(host.dataset.editing)return;const next=JSON.stringify(snapshot);if(next===signature&&host.innerHTML)return;signature=next;
  host.innerHTML=`<h2>CUENTAS DE ZAR · Identidad</h2><p>Identidad base verificada: ${esc(snapshot.base_identity||'POR CONFIGURAR')}</p><p>Nombre sugerido no significa disponible. Contraseñas, CAPTCHA, SMS, recuperación y términos se completan exclusivamente en el proveedor.</p>
  <form data-identity-prepare><h3>CREAR NUEVA CUENTA PARA ZAR</h3><label>Servicio<select name="service">${['GOOGLE','SHOPIFY','STRIPE','YOUTUBE','INSTAGRAM','TIKTOK','ADSENSE','VERCEL'].map(x=>`<option>${x}</option>`).join('')}</select></label>${input('objective','Objetivo')}${input('identity','Email ZAR existente o propuesto',snapshot.base_identity||'')}${input('desired_name','Nombre deseado')}${input('display_name','Nombre público','ZAR')}${input('notes','Notas públicas; nunca contraseñas/tokens')}<button class="zoBtn">Preparar cuenta</button><button type="button" class="zoBtn" data-identity-suggest>Generar alternativas Gmail</button><div id="zarIdentitySuggestions"></div></form>
  <p id="zarIdentityNotice" role="status"></p>${snapshot.plans.map(p=>`<article><h3>${esc(p.service)} · ${esc(p.identity||p.desired_name)}</h3><p>${esc(p.status)} · OAuth ${esc(p.oauth_state)} · Verificado ${esc(p.last_verified)} · ${esc(p.capabilities.join(', '))}</p><p>${esc(p.notice||p.human_step)}</p><ol>${p.steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol><a class="zoBtn" href="${esc(p.url)}" target="_blank" rel="noopener">ABRIR registro oficial</a><button type="button" class="zoBtn" data-identity-op="start" data-id="${esc(p.id)}">CREAR CUENTA</button><a class="zoBtn" href="/connect/google?force=1">CONECTAR / REAUTENTICAR Google</a><button type="button" class="zoBtn" data-identity-op="verify" data-id="${esc(p.id)}">VERIFICAR</button><button type="button" class="zoBtn" data-identity-op="disconnect" data-id="${esc(p.id)}">DESCONECTAR</button><form data-identity-complete><input type="hidden" name="id" value="${esc(p.id)}">${input('identity','Email creado realmente',p.identity)}<label>Recovery<select name="recovery_status"><option>UNKNOWN</option><option>USER_CONFIRMED_CONFIGURED</option></select></label><button class="zoBtn">He completado la creación; continuar a OAuth</button></form></article>`).join('')}`;
 }
 window.addEventListener('zar-workflow-state',e=>render(e.detail));
 document.addEventListener('input',e=>{const host=e.target.closest('#zarIdentityCenter');if(host)host.dataset.editing='true';});
 document.addEventListener('click',async e=>{
  const b=e.target.closest('#zarIdentityCenter button');if(!b||b.type==='submit')return;
  try{
   if(b.hasAttribute('data-identity-suggest')){const r=await post('suggest',{desired_name:b.closest('form').elements.desired_name.value});document.getElementById('zarIdentitySuggestions').textContent=r.alternatives.map(x=>x.email+' · disponibilidad no verificada').join('\n');return;}
   if(b.dataset.identityOp){const data={id:b.dataset.id};if(b.dataset.identityOp==='disconnect'){if(!confirm('Desconectar OAuth local de esta identidad y suspenderla en el inventario; sus módulos Google dejarán de acceder.'))return;data.confirmed=true;}const r=await post(b.dataset.identityOp,data);document.getElementById('zarIdentityCenter').dataset.editing='';signature='';await window.zarWorkflowRefresh?.();document.getElementById('zarIdentityNotice').textContent=r.status+' · '+(r.human_step||'');}
  }catch(err){document.getElementById('zarIdentityNotice').textContent=err.message;}
 });
 document.addEventListener('submit',async e=>{
  const f=e.target;if(!f.matches('#zarIdentityCenter form'))return;e.preventDefault();const data=Object.fromEntries(new FormData(f));
  try{const action=f.hasAttribute('data-identity-complete')?'human_completed':'prepare';if(action==='human_completed'){if(!confirm('Confirmas que esta cuenta fue creada realmente. ZAR todavía comprobará OAuth e identidad.'))return;data.confirmed=true;}await post(action,data);document.getElementById('zarIdentityCenter').dataset.editing='';signature='';await window.zarWorkflowRefresh?.();}
  catch(err){document.getElementById('zarIdentityNotice').textContent=err.message;}
 });
})();
