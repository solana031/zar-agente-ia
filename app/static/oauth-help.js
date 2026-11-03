/* Only copies the existing HTTPS handoff. Never consumes it in an embedded browser. */
(()=>{
 const button=document.getElementById('copyOAuthLink'),field=document.getElementById('oauthSafeLink'),notice=document.getElementById('notice');
 button?.addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText(field.value);notice.textContent='Enlace copiado. Ábrelo en Chrome para continuar; no necesitas repetir la conexión.';}
  catch{field.closest('details').open=true;field.focus();field.select();notice.textContent='Mantén pulsado el enlace y elige Copiar. Ábrelo en Chrome.';}
 });
})();
