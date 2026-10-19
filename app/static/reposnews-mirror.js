/* Independent mirror status; production and editorial confirmation are unchanged. */
(()=>{
 let csrf='',timer=null,busy=false;
 const esc=s=>String(s??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function visible(){const host=document.getElementById('zwSites');return host&&host.getClientRects().length&&!document.hidden;}
 async function refresh(){
  if(!visible()||busy)return;
  busy=true;
  try{
   const r=await fetch('/api/reposnews/mirror'),j=await r.json();if(!r.ok||!j.ok)return;
   csrf=j.csrf;const m=j.mirror,host=document.getElementById('zwSites');let card=document.getElementById('zarReposNewsMirror');
   if(!card){card=document.createElement('section');card.id='zarReposNewsMirror';card.className='zwtPreview';host.prepend(card);}
   card.innerHTML='<h3>ReposNews · producción y mirror</h3><p><strong>PRODUCCIÓN</strong> · Railway · '+(m.primary_online?'ONLINE':'VERIFICANDO')+' · www.reposnews.com</p><p><strong>MIRROR</strong> · GitHub Pages · '+esc(m.status||'OUTDATED')+' · '+esc(m.published_articles_count)+' artículos</p><p>EVENT: '+esc(m.event_driven?'CONFIGURADO':m.dispatch_status||'AUTH_REQUIRED')+'</p><p>LAST SYNC: '+esc(m.verified_at||m.last_static_deploy)+' · '+esc(m.parity||'MIRROR_OUTDATED')+'</p><a href="https://www.reposnews.com" target="_blank" rel="noopener">ABRIR PRODUCCIÓN</a> · <a href="https://solana031.github.io/" target="_blank" rel="noopener">ABRIR MIRROR</a> · <button type="button" data-mirror-sync>SINCRONIZAR MIRROR</button><small data-mirror-result style="display:block">Sincronización por cambios; comprobación diaria sin build si no cambia. Mirror noindex; producción conserva su canonical.</small>';
   card.querySelector('[data-mirror-sync]').onclick=async e=>{
    e.target.disabled=true;
    try{const r=await fetch('/api/reposnews/mirror/sync',{method:'POST',headers:{'X-ZAR-Business-CSRF':csrf}}),j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||'No se pudo solicitar');card.querySelector('[data-mirror-result]').textContent='Mirror en cola. Se sincronizará en la próxima ejecución de GitHub Actions; producción permanece publicada.';}
    catch(ex){card.querySelector('[data-mirror-result]').textContent=ex.message;}
    finally{e.target.disabled=false;}
   };
  }catch(ex){const box=document.querySelector('#zarReposNewsMirror [data-mirror-result]');if(box)box.textContent='No se pudo actualizar el estado del mirror.';}finally{busy=false;}
 }
 function schedule(){if(visible()){refresh();if(!timer)timer=setInterval(()=>{if(visible())refresh();else{clearInterval(timer);timer=null;}},30000);}else if(timer){clearInterval(timer);timer=null;}}
 window.addEventListener('zar-workflow-state',()=>requestAnimationFrame(schedule));
 document.addEventListener('visibilitychange',schedule);
 new MutationObserver(()=>{if(timer&&!visible()){clearInterval(timer);timer=null;}else if(!timer&&visible())schedule();}).observe(document.body,{subtree:true,attributes:true,attributeFilter:['class','style','hidden']});
 schedule();
})();
