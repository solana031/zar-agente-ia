/* Keep the graph and its handlers intact; move secondary controls out of its viewport on mobile. */
(()=>{
 const mobile=matchMedia('(max-width:720px)');
 function arrange(){
  const root=document.getElementById('orchestrationWorkspace'),wrap=root?.querySelector('.zoSceneWrap'),tools=root?.querySelector('.zoToolbar');
  if(!wrap||!tools)return;
  let details=root.querySelector('[data-zo-mobile-controls]');
  if(mobile.matches){
   if(!details){details=document.createElement('details');details.dataset.zoMobileControls='';details.className='zoMobileControls';const summary=document.createElement('summary');summary.textContent='Filtros, zoom y clusters';details.append(summary);wrap.after(details);}
   if(tools.parentElement!==details)details.append(tools);
   const stats=root.querySelector('#zoStats');if(stats&&wrap.nextElementSibling!==stats)wrap.after(stats);
   if(!wrap.querySelector('.zoMobileMapActions')){const actions=document.createElement('div');actions.className='zoMobileMapActions';for(const [label,fn] of [['Ajustar mapa','zoFitAll'],['−','zoZoomOut'],['＋','zoZoomIn']]){const button=document.createElement('button');button.type='button';button.className='zoBtn';button.textContent=label;button.setAttribute('aria-label',label==='−'?'Alejar mapa':label==='＋'?'Acercar mapa':label);button.onclick=()=>window[fn]?.();actions.append(button);}wrap.prepend(actions);}
  }else if(details){wrap.prepend(tools);const stats=root.querySelector('#zoStats');if(stats)wrap.before(stats);details.remove();wrap.querySelector('.zoMobileMapActions')?.remove();}
 }
 new MutationObserver(arrange).observe(document.body,{childList:true,subtree:true});mobile.addEventListener('change',arrange);arrange();
})();
