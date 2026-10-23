/* One external authorization launcher. Completion messages are hints, never proofs. */
(()=>{
 if(window.launchExternalOAuth)return;
 const providers=new Set(['google','youtube','instagram','adsense','tiktok','shopify']);
 const oauth=new Set(['google','youtube','instagram','adsense']);
 const webview=/Android/i.test(navigator.userAgent)&&(/; wv[);]/i.test(navigator.userAgent)||/Version\/4\.0.*Chrome/i.test(navigator.userAgent));
 let active=null;
 const label=p=>({google:'Google',youtube:'YouTube',instagram:'Instagram',adsense:'Google',tiktok:'TikTok',shopify:'Shopify'}[p]||'la cuenta');
 function identify(raw){try{
  const u=new URL(raw,location.origin),h=u.hostname.toLowerCase();
  if(u.origin===location.origin){if(u.pathname==='/connect/google')return u.searchParams.get('service')==='youtube'?'youtube':u.searchParams.get('service')==='adsense'?'adsense':'google';if(u.pathname==='/connect/youtube')return 'youtube';if(u.pathname==='/api/reposnews/instagram/connect')return 'instagram';return null;}
  if(u.protocol!=='https:')return null;
  if(h==='accounts.google.com')return 'google';
  if(['instagram.com','www.instagram.com','facebook.com','www.facebook.com','auth.meta.com'].includes(h)&&/\/(?:oauth|dialog|accounts\/login|login)/.test(u.pathname))return 'instagram';
  if(['www.tiktok.com','open.tiktokapis.com'].includes(h)&&/\/oauth/.test(u.pathname))return 'tiktok';
  if((h==='accounts.shopify.com'||h.endsWith('.myshopify.com'))&&/\/(?:oauth|auth)/.test(u.pathname))return 'shopify';
 }catch{}return null;}
 function safeURL(provider,raw){const u=new URL(raw,location.origin);if(u.username||u.password||!['https:','http:'].includes(u.protocol))throw Error('Dirección de autorización no válida.');
  if(u.origin===location.origin&&(/^\/oauth\/accounts\/start\/[A-Za-z0-9_-]+$/.test(u.pathname)||identify(u.href)))return u;
  if(u.protocol==='https:'&&identify(u.href)===provider)return u;
  throw Error('La autorización requiere revisar el proveedor.');
 }
 function state(attempt,phase,message){window.dispatchEvent(new CustomEvent('zar-oauth-state',{detail:{provider:attempt.provider,phase,message}}));if(attempt.notice)attempt.notice.textContent=message;}
 function panel(attempt){
  document.getElementById('zarOAuthNotice')?.remove();
  const box=document.createElement('section');box.id='zarOAuthNotice';box.setAttribute('role','status');
  Object.assign(box.style,{position:'fixed',bottom:'18px',left:'16px',right:'16px',maxWidth:'620px',margin:'auto',zIndex:'2147483000',padding:'18px',border:'1px solid #9d8048',borderRadius:'12px',background:'#17150f',color:'#ead9b5',boxShadow:'0 10px 40px #0009'});
  const text=document.createElement('p');attempt.notice=text;
  const link=document.createElement('a');link.textContent='ABRIR AUTORIZACIÓN';link.target='_blank';link.rel='noopener noreferrer';link.dataset.oauthFallback='1';link.hidden=true;
  link.onclick=()=>{attempt.started=true;state(attempt,'AUTHORIZING','Esperando autorización… Vuelve a ZAR al terminar.');};
  const cancel=document.createElement('button');attempt.cancel=cancel;cancel.type='button';cancel.textContent='CANCELAR';cancel.style.marginLeft='16px';cancel.onclick=()=>{try{attempt.popup?.close();}catch{}finish(attempt,'cancel');};
  box.append(text,link,cancel);document.body.append(box);attempt.box=box;attempt.fallback=link;
 }
 function notify(provider){
  window.dispatchEvent(new CustomEvent('zar-accounts-changed',{detail:{provider}}));
  if(parent!==window)parent.postMessage({type:'zar-accounts-changed',provider},location.origin);
  else for(const f of document.querySelectorAll('iframe'))f.contentWindow?.postMessage({type:'zar-accounts-changed',provider},location.origin);
 }
 async function reverify(provider){
  const r=await fetch('/api/accounts/connections',{cache:'no-store'});if(!r.ok)throw Error('No se pudo comprobar la cuenta.');const j=await r.json();
  if(oauth.has(provider)){
   const check=await fetch('/api/accounts/connections/'+provider+'/reverify',{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':j.csrf},body:'{}'});
   if(!check.ok)throw Error('No se pudo reverificar la cuenta.');
  }
  await fetch('/api/accounts/connections',{cache:'no-store'});notify(provider);
 }
 async function finish(attempt,reason){
  if(active!==attempt||attempt.finishing)return;attempt.finishing=true;clearTimeout(attempt.timer);
  if(attempt.handoff)sessionStorage.removeItem('zar-accounts-oauth');
  try{await reverify(attempt.provider);state(attempt,'DONE',reason==='CONNECTED'?'Cuenta conectada correctamente.':'Estado de la cuenta actualizado.');}
  catch{state(attempt,'ERROR','No se pudo comprobar la conexión. Pulsa REVERIFICAR.');attempt.failed=true;}
  active=null;if(attempt.failed){attempt.fallback.hidden=true;attempt.cancel.textContent='CERRAR';attempt.cancel.onclick=()=>attempt.box.remove();}else attempt.box?.remove();
 }
 async function watch(attempt){
  if(active!==attempt||attempt.finishing)return;
  if(Date.now()>attempt.expires){finish(attempt,'expired');return;}
  if(attempt.handoff&&!document.hidden){try{const r=await fetch('/api/accounts/oauth/status/'+encodeURIComponent(attempt.handoff),{cache:'no-store'}),j=await r.json();if(j.status!=='PENDING'){finish(attempt,j.status);return;}}catch{}}
  else if(attempt.started&&attempt.popup?.closed){finish(attempt,'closed');return;}
  clearTimeout(attempt.timer);attempt.timer=setTimeout(()=>watch(attempt),attempt.handoff?3000:650);
 }
 window.launchExternalOAuth=async function(provider,url,options={}){
  provider=String(provider||'').toLowerCase();if(!providers.has(provider))throw Error('Proveedor no válido.');
  if(active){try{active.popup?.focus();}catch{}return;}
  const attempt={provider,popup:null,started:false,expires:Date.now()+600000};active=attempt;panel(attempt);
  // Reserve a real browsing context during the click, before any asynchronous fetch.
  if(!webview){try{attempt.popup=window.open('about:blank','zar-oauth-'+provider+'-'+Date.now(),'popup,width=600,height=760');if(attempt.popup)attempt.popup.document.body.textContent='Esperando autorización…';}catch{attempt.popup=null;}}
  state(attempt,'AUTHORIZING','Esperando autorización…');
  try{
   let result={url};const local=url&&new URL(url,location.origin);
   if(!url||(local.origin===location.origin&&identify(local.href))){
    let csrf=options.csrf;if(!csrf){const r=await fetch('/api/accounts/connections',{cache:'no-store'});if(!r.ok)throw Error();csrf=(await r.json()).csrf;}
    const payload={external:true};if(local)payload.authorization_path=local.pathname+local.search;
    const r=await fetch('/api/accounts/connections/'+provider+'/'+(options.operation==='connect'?'connect':'reconnect'),{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify(payload)});result=await r.json();if(!r.ok||!result.url||result.assistant)throw Error();
   }
   const target=safeURL(provider,result.url);
   if(!result.external&&target.origin===location.origin)target.searchParams.set('oauth_popup','1');
   attempt.url=target.href;attempt.fallback.href=target.href;attempt.fallback.hidden=false;
   if(result.external){
    if(target.origin!==location.origin||!result.poll_id)throw Error();
    attempt.handoff=result.poll_id;sessionStorage.setItem('zar-accounts-oauth',JSON.stringify({id:attempt.handoff,provider,expires:attempt.expires}));
   }
   if(result.external&&webview){
    const intent='intent://'+target.host+target.pathname+'#Intent;scheme=https;action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;package=com.android.chrome;S.browser_fallback_url='+encodeURIComponent(target.href)+';end';
    const chrome=document.createElement('a');chrome.textContent='ABRIR NAVEGADOR SEGURO';chrome.href=intent;chrome.dataset.oauthFallback='1';attempt.box.append(' ',chrome);
    state(attempt,'AUTHORIZING','Conectando… Esperando autorización en Chrome. Vuelve a ZAR al terminar.');location.assign(intent);
   }else if(attempt.popup){attempt.popup.location.replace(target.href);attempt.started=true;}
   else state(attempt,'AUTHORIZING','Tu navegador ha bloqueado la ventana de autorización.');
   watch(attempt);
  }catch{try{attempt.popup?.close();}catch{}active=null;attempt.fallback.hidden=true;attempt.cancel.textContent='CERRAR';attempt.cancel.onclick=()=>attempt.box.remove();state(attempt,'ERROR','No se pudo abrir la autorización. Vuelve a intentarlo desde CUENTAS.');}
 };
 window.addEventListener('message',e=>{
  if(e.origin!==location.origin)return;
  if(e.data?.type==='zar-oauth-result'&&active&&e.source===active.popup&&e.data.provider===active.provider)finish(active,e.data.status);
  if(e.data?.type!=='zar-accounts-changed'||!providers.has(e.data.provider))return;
  if(parent!==window&&e.source===parent){window.dispatchEvent(new CustomEvent('zar-accounts-changed',{detail:{provider:e.data.provider}}));return;}
  if(![...document.querySelectorAll('iframe')].some(f=>f.contentWindow===e.source))return;
  window.dispatchEvent(new CustomEvent('zar-accounts-changed',{detail:{provider:e.data.provider}}));
  for(const f of document.querySelectorAll('iframe'))if(f.contentWindow!==e.source)f.contentWindow?.postMessage(e.data,location.origin);
 });
 window.addEventListener('focus',()=>{if(active?.started&&!active.popup&&!active.handoff)finish(active,'return');});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden&&active){if(active.handoff)watch(active);else if(active.started&&!active.popup)finish(active,'return');}});
 window.addEventListener('pagehide',()=>clearTimeout(active?.timer));
 document.addEventListener('click',e=>{
  const a=e.target.closest('a[href]');if(!a||a.dataset.oauthFallback)return;
  const u=new URL(a.href,location.origin);let provider=identify(u.href);
  if(!provider&&u.origin===location.origin&&u.pathname==='/accounts'&&/^(?:RE)?CONECTAR\b/i.test(a.textContent.trim())){const p=u.hash.slice(1);if(oauth.has(p))provider=p;}
  if(!provider)return;e.preventDefault();e.stopImmediatePropagation();window.launchExternalOAuth(provider,u.pathname==='/accounts'?null:u.href);
 },true);
 try{const saved=JSON.parse(sessionStorage.getItem('zar-accounts-oauth')||'null');if(saved&&providers.has(saved.provider||'google')&&saved.expires>Date.now()){
  active={provider:saved.provider||'google',handoff:saved.id,expires:saved.expires,started:true};panel(active);state(active,'AUTHORIZING','Esperando autorización…');watch(active);
 }}catch{sessionStorage.removeItem('zar-accounts-oauth');}
})();
