/* Existing AdSense pane: three actions, no account values and no ad activation. */
(() => {
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function render(r={}){
  const checks=r.checklist||{},fields=r.account_fields||{},legal=r.legal_review||{};
  const checked=r.checked_at?new Date(r.checked_at).toLocaleString('es-ES',{timeZone:'Europe/Madrid'}):'';
  return `<section id="zarAdsenseReadiness" aria-label="Preparación de ReposNews para AdSense" style="border:1px solid #665130;border-radius:14px;padding:16px;margin:18px 0;max-width:100%;overflow-wrap:anywhere">
  <h3>ReposNews · preparación de AdSense</h3><p>${esc(r.status||'UNKNOWN')}</p>
  <dl style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 16px">${Object.entries(checks).map(([label,status])=>`<dt>${esc(label)}</dt><dd style="margin:0">${esc(status)}</dd>`).join('')}</dl>
  <p>Publicidad desactivada. Esta preparación no acredita aprobación de cuenta o sitio, no activa anuncios y no envía solicitudes a Google.</p>
  <p>Último aviso observado de la cuenta: ${esc(r.account_message||'Revisión pendiente en la cuenta existente.')}</p>
  <a href="https://adsense.google.com/" target="_blank" rel="noopener">Abrir la cuenta AdSense existente</a>
  <details ${r.account_reviewed?'':'open'}><summary>REVISAR DATOS DE CUENTA ADSENSE · CRITICAL</summary>
  <p>Revisa directamente en Google. ZAR solo guarda las comprobaciones, nunca los valores personales o documentos. Si beneficiario, perfil de pagos, formulario fiscal o dirección difieren, resuelve esa diferencia en Google antes de confirmar.</p>
  <form data-form="adsense-account-review">${Object.entries(fields).map(([key,label])=>`<label style="display:block;margin:10px 0"><input type="checkbox" name="${esc(key)}" ${r.account_checks?.[key]?'checked':''} required> ${esc(label)}</label>`).join('')}
  <label style="display:block">Estado fiscal actual comprobado en Google <select name="tax_status"><option value="UNKNOWN">Sin evidencia de aceptación actual</option>${[['IN_REVIEW','En revisión en Google; todavía no aceptado'],['ACCEPTED','W-8BEN vigente aceptado, comprobado personalmente'],['PENDING','Pendiente en Google'],['REJECTED','Rechazado en Google'],['NOT_APPLICABLE','No aplicable, comprobado personalmente']].map(([v,t])=>`<option value="${v}" ${r.tax_status===v?'selected':''}>${t}</option>`).join('')}</select></label>
  <label style="display:block;margin:12px 0"><input type="checkbox" name="confirmed" required> He revisado los puntos y su aplicabilidad; los datos son coherentes.</label>
  <button class="zoBtn" type="submit">Guardar revisión de datos</button></form></details>
  <details><summary>Estado observado en Google · ${esc(r.tax_status||'UNKNOWN')}</summary>
  <p>Registra solo el estado comprobado y los campos pendientes. No confirma la checklist de cuenta, no modifica Google y no acredita aprobación. Si Google muestra «En revisión», no envíes otro formulario solo por ese estado.</p>
  <p>${esc(r.provider_observation_at?new Date(r.provider_observation_at).toLocaleString('es-ES',{timeZone:'Europe/Madrid'}):'Sin comprobación registrada.')}</p>
  <form data-form="adsense-provider-observation"><label style="display:block">Estado fiscal observado <select name="tax_status">${[['UNKNOWN','Desconocido'],['IN_REVIEW','En revisión'],['ACCEPTED','Aceptado'],['PENDING','Pendiente de completar'],['REJECTED','Rechazado'],['NOT_APPLICABLE','No aplicable']].map(([v,t])=>`<option value="${v}" ${r.tax_status===v?'selected':''}>${t}</option>`).join('')}</select></label>
  ${Object.entries(r.finding_options||{}).map(([key,label])=>`<label style="display:block;margin:10px 0"><input type="checkbox" name="${esc(key)}" ${r.account_findings?.[key]?'checked':''}> ${esc(label)}</label>`).join('')}
  <label style="display:block"><input type="checkbox" name="confirmed" required> He comprobado este estado en Google y registro únicamente lo observado.</label>
  <button class="zoBtn">Guardar comprobación de Google</button></form></details>
  <details><summary>CONFIGURAR CMP ADSENSE · ${esc(r.cmp_status||'UNKNOWN')}</summary>
  <ol>${(r.cmp_steps||[]).map(s=>`<li>${esc(s)}</li>`).join('')}</ol>
  <p>La detección registra solo disponibilidad, estado TCF, ID de CMP y presencia de cadena; nunca guarda la cadena ni las preferencias individuales. Solo Google CMP 300 está verificada como certificada para esta integración.</p>
  <form data-form="adsense-cmp-setup"><label style="display:block">URL pública de la etiqueta CMP independiente oficial proporcionada por Google <input style="width:100%" name="official_url" type="url" value="${esc(r.cmp_loader||'')}"></label>
  <label style="display:block"><input name="confirmed" type="checkbox" required> He publicado el mensaje y esta URL procede de su etiqueta CMP oficial para el publisher actual. No es una etiqueta de anuncios.</label>
  <button class="zoBtn">Guardar etiqueta CMP</button></form></details>
  <details><summary>Disponibilidad de la CMP en AdSense · ${esc(r.cmp_configuration_status||'UNKNOWN')}</summary>
  <p>El <a href="https://support.google.com/adsense/answer/7584263" target="_blank" rel="noopener">proceso oficial de Google</a> sitúa la selección de CMP como opcional después de solicitar revisión. Sigue siendo necesaria para la publicidad correspondiente; aquí no se activan anuncios. La ausencia del menú en este onboarding se registra como espera del proveedor, sin dar la CMP por instalada.</p>
  <form data-form="adsense-provider-availability"><label style="display:block">Configuración CMP en la cuenta actual <select name="cmp"><option value="UNKNOWN">Sin verificar</option><option value="AVAILABLE">Menú disponible</option><option value="WAITING_FOR_ADSENSE_AVAILABILITY" ${r.cmp_availability==='WAITING_FOR_ADSENSE_AVAILABILITY'?'selected':''}>Menú no disponible en el onboarding</option></select></label>
  <label style="display:block"><input name="account_not_approved" type="checkbox"> Google muestra que la cuenta todavía no está aprobada.</label>
  <label style="display:block"><input name="confirmed" type="checkbox" required> He comprobado el menú y el estado de esta cuenta en Google. No se modifica información fiscal.</label>
  <button class="zoBtn">Guardar disponibilidad de CMP</button></form></details>
  <details><summary>CONFIRMAR IDENTIFICACIÓN LEGAL PARA MONETIZACIÓN</summary>
  <p>PUBLIC_REQUIRED: información que autorizas expresamente a mostrar en el aviso legal. PRIVATE_ADMINISTRATIVE: documentación fiscal, bancos, pagos y contactos privados; no se importan ni se solicitan aquí.</p>
  <p>Para actividad económica, <a href="https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758#a10" target="_blank" rel="noopener">LSSI, artículo 10</a>: titular, domicilio o establecimiento, contacto e identificación fiscal; registro, autorización o profesión regulada si procede. Confirma la aplicabilidad antes de publicar datos; el teléfono privado no se solicita.</p>
  <form data-form="adsense-legal-review">
  <label style="display:block">Tipo de titular <select name="entity_type" required><option value="">Seleccionar</option><option value="PERSON" ${legal.entity_type==='PERSON'?'selected':''}>Persona física</option><option value="COMPANY" ${legal.entity_type==='COMPANY'?'selected':''}>Sociedad</option></select></label>
  <label style="display:block">Actividad económica <select name="economic" required><option value="">Seleccionar</option><option value="YES" ${legal.economic==='YES'?'selected':''}>Sí</option><option value="NO" ${legal.economic==='NO'?'selected':''}>No</option></select></label>
  ${Object.entries(r.public_fields||{}).map(([key,label])=>`<label style="display:block;margin:10px 0">${esc(label)} <input style="width:100%" maxlength="500" name="public_${esc(key)}" value="${esc(legal.PUBLIC_REQUIRED?.[key]||'')}" ${['controller','email','activity'].includes(key)?'required':''}></label>`).join('')}
  <label style="display:block"><input type="checkbox" name="applicability_reviewed" required> He revisado qué exige la ley para mi actividad, incluidos registro y obligaciones profesionales si corresponden.</label>
  <label style="display:block"><input type="checkbox" name="confirmed" required> Autorizo publicar exactamente los campos anteriores en el aviso legal. No se copiarán valores de mi perfil privado.</label>
  <button class="zoBtn">Confirmar y publicar identificación legal</button></form></details>
  <button class="zoBtn" type="button" data-adsense-reverify>REVERIFICAR ADSENSE / CMP</button><p data-adsense-probe-status role="status"></p>
  <p>Comprueba solo sitio público, ads.txt, verificación, CMP, presencia del aviso legal y confirmaciones internas. No consulta datos fiscales privados de Google.</p>
  <p>Auditoría pública: ${r.audit_current?'vigente':'pendiente o desactualizada'}. ${esc(checked)}</p>
  <p>READY_FOR_RESUBMISSION: <strong>${r.ready_for_resubmission?'YES':'NO'}</strong>. Pendiente: ${esc((r.blockers||[]).join(' · '))}</p>
  ${r.ready_for_resubmission?'<p>ReposNews está preparado para volver a enviarse a revisión.</p>':''}</section>`;
 }
 let running=false;
 document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-adsense-reverify]');if(!b||running)return;
  const panel=b.closest('#zarAdsenseReadiness'),status=panel.querySelector('[data-adsense-probe-status]');
  // Open during the user gesture; retain opener only for a nonce-bound origin check.
  const popup=window.open('about:blank','zar-adsense-cmp-probe');
  if(!popup){status.textContent='Permite abrir la ventana del sitio para comprobar la CMP.';return;}
  running=true;b.disabled=true;let receiver,timer;
  try{
   status.textContent='Comprobando el sitio público y su CMP…';
   const wf=await fetch('/api/holdings/workflows').then(x=>x.json());
   const post=async(action,payload)=>{const response=await fetch('/api/holdings/workflows/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':wf.csrf},body:JSON.stringify(payload)});const body=await response.json();if(!response.ok||!body.ok)throw Error(body.error||'No se pudo completar la verificación.');return body.result;};
   const start=await post('adsense_probe_start',{});
   const result=new Promise((resolve,reject)=>{
    receiver=event=>{if(event.origin==='https://www.reposnews.com'&&event.source===popup&&event.data?.type==='zar-cmp-probe'&&event.data.nonce===start.nonce)resolve(event.data.probe);};
    window.addEventListener('message',receiver);timer=setTimeout(()=>reject(Error('La CMP no respondió. Comprueba si el navegador bloquea la ventana o la conexión.')),35000);
   });
   popup.location.href=start.url;
   const probe=await result;clearTimeout(timer);window.removeEventListener('message',receiver);
   const r=await post('adsense_probe_finish',{nonce:start.nonce,probe});
   const message='Verificación terminada. CMP: '+r.cmp_status+'. READY_FOR_RESUBMISSION: '+(r.ready_for_resubmission?'YES':'NO');
   status.textContent=message;window.dispatchEvent(new Event('zar-adsense-reverified'));if(window.zarWorkflowRefresh)await window.zarWorkflowRefresh();
   const current=document.querySelector('#zarAdsenseReadiness [data-adsense-probe-status]');if(current)current.textContent=message;
  }catch(error){status.textContent=error.message;}
  finally{clearTimeout(timer);if(receiver)window.removeEventListener('message',receiver);running=false;b.disabled=false;/* Keep the public window available for reading its result. */}
 });
 window.ZarAdSenseReadiness={render};
})();
