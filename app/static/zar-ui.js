/* One accessible ZAR dialog surface. Never replaces synchronous browser globals. */
(()=>{
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let tail=Promise.resolve(),active=null;
 function show(options){return new Promise(resolve=>{
  const prior=document.activeElement,root=document.createElement('div');root.className='zarDialogOverlay';root.innerHTML=`<section class="zarDialog" role="dialog" aria-modal="true" aria-labelledby="zarDialogTitle" tabindex="-1"><header><h2 id="zarDialogTitle">${esc(options.title||'ZAR')}</h2></header><p style="white-space:pre-wrap">${esc(options.message)}</p>${options.input?`<label>${esc(options.label||'Tu respuesta')}<textarea data-zar-answer rows="4">${esc(options.value||'')}</textarea></label>`:''}${options.choices?`<label>Selecciona<select data-zar-answer>${options.choices.map(c=>`<option value="${esc(c.value)}">${esc(c.label)}</option>`).join('')}</select></label>`:''}<footer>${options.cancel!==false?'<button class="zarBtn secondary" data-zar-cancel>Cancelar</button>':''}<button class="zarBtn" ${options.primaryId?`id="${esc(options.primaryId)}"`:""} data-zar-ok>${esc(options.ok||'Continuar')}</button></footer></section>`;document.body.append(root);active=root;
  const finish=value=>{root.remove();active=null;document.removeEventListener('keydown',keys,true);prior?.focus?.();resolve(value);};
  function keys(e){if(e.key==='Escape'){e.preventDefault();finish(options.input||options.choices?null:false);}if(e.key==='Tab'){const items=root.querySelectorAll('button,textarea,select');if(e.shiftKey&&document.activeElement===items[0]){e.preventDefault();items[items.length-1].focus();}else if(!e.shiftKey&&document.activeElement===items[items.length-1]){e.preventDefault();items[0].focus();}}}
  document.addEventListener('keydown',keys,true);root.querySelector('[data-zar-cancel]')?.addEventListener('click',()=>finish(options.input||options.choices?null:false));root.querySelector('[data-zar-ok]').addEventListener('click',()=>finish(options.input||options.choices?root.querySelector('[data-zar-answer]').value:true));(root.querySelector('[data-zar-answer]')||root.querySelector('[data-zar-ok]')).focus();
 });}
 function queued(options){const promise=tail.then(()=>show(options));tail=promise.catch(()=>{});return promise;}
 const pending=new Map();
 async function confirm(message,options={}){
  const key=options.action_id||String(message);if(pending.has(key))return pending.get(key);
  const promise=(async()=>{const risk=options.risk||(/publicar|comprar|irrevers|definitiv|enviar dinero|cerrar cuenta|live trading|email sensible/i.test(message)?'HIGH':'MEDIUM');const id=crypto.randomUUID(),row={confirmation_id:id,action_id:options.action_id||id,state:'PENDING',risk,description:String(message),created_at:new Date().toISOString()};
   if(!await queued({title:options.title||'Confirmar acción',message,ok:options.ok||'Confirmar',primaryId:options.primaryId})){row.state='CANCELLED';window.dispatchEvent(new CustomEvent('zar-confirmation-event',{detail:row}));return false;}
   row.confirmed_at=new Date().toISOString();
   if(['HIGH','CRITICAL'].includes(risk)){if(!await queued({title:'Revisión final',message:'¿Estás seguro de que quieres confirmar esta acción?\n\n'+message,ok:'Sí, estoy seguro'})){row.state='CANCELLED';window.dispatchEvent(new CustomEvent('zar-confirmation-event',{detail:row}));return false;}row.second_confirm_at=new Date().toISOString();}
   row.state='ACTION_CONFIRMED';window.dispatchEvent(new CustomEvent('zar-confirmation-event',{detail:row}));return true;
  })();pending.set(key,promise);try{return await promise;}finally{pending.delete(key);}
 }
 window.ZarUI={confirm,prompt:(message,value='',options={})=>queued({title:options.title||'Editar en ZAR',message,input:true,value,label:options.label,ok:options.ok||'Aplicar'}),alert:message=>queued({title:'ZAR',message,cancel:false,ok:'Entendido'}),select:(message,choices)=>queued({title:'Seleccionar',message,choices}),form:options=>queued(options)};
 window.ZarModal=window.ZarUI;window.ZarPrompt=window.ZarUI.prompt;window.ZarConfirm=confirm;window.ZarSelect=window.ZarUI.select;window.ZarFormDialog=window.ZarUI.form;
})();
