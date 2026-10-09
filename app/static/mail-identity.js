/* Sender choices come from Gmail verification, never from an invented account. */
(()=>{
 async function choose(){
  const r=await fetch('/api/mail/identities',{cache:'no-store'}),j=await r.json();
  if(!r.ok||!j.ok)throw Error(j.error||'No se pudo verificar Gmail.');
  if(!j.accounts?.length){await ZarUI.alert('ACTION_REQUIRED · conecta una cuenta Gmail autorizada.');return null;}
  return ZarUI.select('¿DESDE QUÉ CUENTA QUIERES ENVIARLO?\nSolo se muestran buzones verificados. El envío se revisa después.',[
   {value:'',label:'Selecciona el remitente'},...j.accounts.map(a=>({value:a.email,label:a.label+' · '+a.email}))
  ]);
 }
 window.ZarMailIdentity={choose};
 document.addEventListener('click',async e=>{const b=e.target.closest('[data-mail-sender]');if(!b)return;b.disabled=true;try{const sender=await choose();if(sender){document.getElementById('input').value='remitente '+sender;await window.send();}}catch(error){await ZarUI.alert(error.message);}finally{b.disabled=false;}});
})();
