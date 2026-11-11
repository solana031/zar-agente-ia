/* Help bubbles for the sidebar (i) icons, drawn in a fixed top layer so no panel can cover or clip them. */
(()=>{
 if(window.zarTipsReady)return;window.zarTipsReady=true;
 let tip=null,current=null;
 const ensure=()=>{if(!tip){tip=document.createElement('div');tip.id='zarTip';tip.setAttribute('role','tooltip');document.body.append(tip);}return tip;};
 function show(el){const text=el.getAttribute('data-tip');if(!text)return;current=el;const t=ensure();t.textContent=text;const r=el.getBoundingClientRect();t.style.left='0px';t.style.top='0px';t.classList.add('on');
  const w=t.offsetWidth,h=t.offsetHeight;let left=r.right+10,top=r.top+r.height/2-h/2;if(left+w>innerWidth-8)left=Math.max(8,r.left-w-10);top=Math.max(8,Math.min(innerHeight-h-8,top));t.style.left=left+'px';t.style.top=top+'px';el.setAttribute('aria-describedby','zarTip');}
 function hide(){if(tip)tip.classList.remove('on');current?.removeAttribute('aria-describedby');current=null;}
 document.addEventListener('mouseover',e=>{const el=e.target.closest?.('.info[data-tip]');if(el&&el!==current)show(el);else if(!el&&current)hide();});
 document.addEventListener('focusin',e=>{const el=e.target.closest?.('.info[data-tip]');if(el)show(el);});
 document.addEventListener('focusout',hide);
 document.addEventListener('scroll',hide,true);
 document.addEventListener('keydown',e=>{if(e.key==='Escape')hide();});
})();
