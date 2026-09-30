/* Presentation only: visible viewport and accessible menu state. No service calls. */
(() => {
  const root = document.documentElement;
  function syncViewport() {
    const v = window.visualViewport;
    const height = v?.height || innerHeight;
    root.style.setProperty('--zar-visible-height', `${height}px`);
    root.style.setProperty('--zar-visible-top', `${v?.offsetTop || 0}px`);
    root.style.setProperty('--zar-keyboard-offset', `${Math.max(0, innerHeight - height - (v?.offsetTop || 0))}px`);
    document.body.classList.toggle('zar-keyboard-open', height < innerHeight * .8);
  }
  syncViewport();
  window.addEventListener('resize', syncViewport, {passive:true});
  window.visualViewport?.addEventListener('resize', syncViewport, {passive:true});
  window.visualViewport?.addEventListener('scroll', syncViewport, {passive:true});
  const drawer = document.getElementById('mobileDrawer');
  const menu = document.querySelector('.mobileMenu');
  const syncMenu = () => {
    menu?.setAttribute('aria-expanded', String(!drawer.hidden));
    menu?.setAttribute('aria-controls', 'mobileDrawer');
  };
  if(drawer){new MutationObserver(syncMenu).observe(drawer,{attributes:true,attributeFilter:['hidden']});syncMenu();}
  document.getElementById('input')?.setAttribute('aria-label','Mensaje para ZAR');
  const close = document.querySelector('#panel > button');
  close?.setAttribute('aria-label','Cerrar panel');
  const studioPopup = document.getElementById('studioContextPopup');
  if(studioPopup){
    new MutationObserver(() => {
      if(studioPopup.hidden || studioPopup.querySelector('[data-close-context]'))return;
      const button=document.createElement('button');
      button.type='button';button.className='btnSmall';button.dataset.closeContext='1';
      button.textContent='Cerrar';button.setAttribute('aria-label','Cerrar panel de Studio');
      button.onclick=()=>{studioPopup.hidden=true;};
      studioPopup.prepend(button);
    }).observe(studioPopup,{childList:true,attributes:true,attributeFilter:['hidden']});
  }
  document.addEventListener('keydown', e => {
    if(e.key==='Escape' && drawer && !drawer.hidden){closeMobileDrawer();menu?.focus();}
  });
})();
