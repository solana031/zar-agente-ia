/* Existing AdSense pane: evidence, account review and explicit outstanding gates. */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function render(r={}) {
    const checks=r.checklist||{},fields=r.account_fields||{};
    const checked=r.checked_at?new Date(r.checked_at).toLocaleString('es-ES',{timeZone:'Europe/Madrid'}):'';
    return `<section id="zarAdsenseReadiness" aria-label="Preparación de ReposNews para AdSense" style="border:1px solid #665130;border-radius:14px;padding:16px;margin:18px 0;max-width:100%;overflow-wrap:anywhere">
      <h3>ReposNews · preparación de AdSense</h3><p>${esc(r.status||'UNKNOWN')}</p>
      <dl style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 16px">${Object.entries(checks).map(([label,status])=>`<dt>${esc(label)}</dt><dd style="margin:0">${esc(status)}</dd>`).join('')}</dl>
      <p>Publicidad desactivada. La verificación del sitio no activa anuncios ni envía una solicitud a Google.</p>
      <p>${esc(r.cmp_note||'Verificar CMP certificada antes de activar anuncios.')}</p>
      <p>Último aviso observado de la cuenta: ${esc(r.account_message||'Revisión pendiente en la cuenta existente.')}</p>
      <a href="https://adsense.google.com/" target="_blank" rel="noopener">Abrir la cuenta AdSense existente</a>
      ${Object.keys(fields).length?`<details ${r.account_reviewed?'':'open'}><summary>Revisar información de cuenta AdSense · ${r.account_reviewed?'revisión registrada':'acción de Pablo'}</summary>
        <p>Revisa los valores directamente en Google. Aquí solo se guarda si has comprobado cada punto y su aplicabilidad; no escribas nombre, dirección, teléfono, NIF, datos fiscales ni bancarios.</p>
        <form data-form="adsense-account-review">${Object.entries(fields).map(([key,label])=>`<label style="display:block;margin:10px 0"><input type="checkbox" name="${esc(key)}" ${r.account_checks?.[key]?'checked':''} required> ${esc(label)}</label>`).join('')}
        <label style="display:block;margin:12px 0"><input type="checkbox" name="confirmed" required> He revisado estos datos en la cuenta existente y su aplicabilidad.</label>
        <button class="zoBtn" type="submit">Guardar revisión de datos</button>
        <p>Esta confirmación no cambia los datos de Google, no acredita aprobación y no pulsa «Volver a enviar».</p></form></details>`:''}
      <p>Auditoría pública: ${r.audit_current?'vigente':'pendiente o desactualizada'}. ${esc(checked)}</p>
      <p>Listo para volver a enviar: <strong>${r.ready_for_resubmission?'YES':'NO'}</strong>. Pendiente: ${esc((r.blockers||[]).join(' · '))}</p>
    </section>`;
  }
  window.ZarAdSenseReadiness={render};
})();
