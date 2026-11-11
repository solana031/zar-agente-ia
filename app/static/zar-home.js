/* "Inicio" button on every ZAR section: back to the main menu from tabs, panes and standalone pages. */
(()=>{
 if(document.getElementById('zarHomeButton'))return;
 const params=new URLSearchParams(location.search);
 let framed=false;try{framed=window.parent!==window&&parent.location.origin===location.origin;}catch{framed=false;}
 const standalone=params.has('zar_workspace')||location.pathname.startsWith('/accounts')||location.pathname.startsWith('/instagram-browser');
 if(!framed&&!standalone)return;
 const b=document.createElement('a');b.id='zarHomeButton';b.href='/';b.className='zarHomeButton';
 b.setAttribute('aria-label','Volver al menú principal de ZAR');b.title='Volver al menú principal';
 b.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v10h5v-6h4v6h5V10"/></svg><span>Inicio</span>';
 b.addEventListener('click',e=>{if(framed){e.preventDefault();parent.postMessage({zarWorkspace:true,action:'home'},location.origin);}});
 const css=document.createElement('style');css.textContent='.zarHomeButton{position:fixed;left:12px;top:10px;z-index:100000;display:inline-flex;align-items:center;gap:7px;height:40px;padding:0 14px 0 11px;border-radius:999px;background:rgba(28,23,17,.86);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border:1px solid rgba(226,189,115,.35);color:#f0dcb5;font:600 13px/1 system-ui,-apple-system,Segoe UI,sans-serif;text-decoration:none;box-shadow:0 8px 24px rgba(0,0,0,.35);transition:background .15s,border-color .15s,transform .15s}.zarHomeButton:hover{background:rgba(48,38,26,.95);border-color:rgba(226,189,115,.7);transform:translateY(-1px)}.zarHomeButton:focus-visible{outline:2px solid #e2bd73;outline-offset:3px}.zarHomeButton svg{width:18px;height:18px}body.zarHasHome .zwtSubappHeader,body.zarHasHome main.accounts>header{padding-top:44px}.zarHomeButton.zarHomeFloat{top:auto;bottom:16px;left:16px}.zarHomeButton.zarHomeRaised{bottom:118px}@media(max-width:600px){.zarHomeButton span{display:none}.zarHomeButton{width:40px;padding:0;justify-content:center}}';
 document.head.append(css);document.body.classList.add('zarHasHome');document.body.append(b);
 // Sections without a reserved header slot get a floating button at the bottom-left.
 const place=()=>{const top=document.body.classList.contains('zarBusinessPane')||!!document.querySelector('main.accounts');b.classList.toggle('zarHomeFloat',!top);b.classList.toggle('zarHomeRaised',!top&&['stonks','studio','clipper'].includes(document.body.dataset.workspaceType||''));};
 place();setTimeout(place,1500);
})();
