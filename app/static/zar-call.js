/* ZAR calls: free incoming "calls" through Web Push + browser voice (no phone carrier). */
(()=>{
 if(window.zarCallReady)return;window.zarCallReady=true;
 if(window.parent!==window){try{if(parent.location.origin===location.origin)return;}catch{}}
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let ring=null,current=null,csrf='';
 const css=document.createElement('style');css.textContent=`
 #zarCall{position:fixed;inset:0;z-index:2147483000;display:grid;place-items:center;background:radial-gradient(circle at 50% 30%,#3a2a14 0%,#120e09 60%,#070605 100%);color:#f3e6cc;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;padding:24px}
 #zarCall .zc{width:min(420px,100%);text-align:center;display:grid;gap:18px;justify-items:center}
 #zarCall .zcAvatar{width:132px;height:132px;border-radius:50%;background:#1b150e url(/static/zar-logo.png) center/78% no-repeat;border:2px solid #e2bd73;box-shadow:0 0 0 0 #e2bd7366;animation:zcPulse 1.6s infinite}
 #zarCall.talking .zcAvatar{animation:zcTalk .9s infinite alternate}
 @keyframes zcPulse{0%{box-shadow:0 0 0 0 #e2bd7380}100%{box-shadow:0 0 0 34px #e2bd7300}}
 @keyframes zcTalk{from{transform:scale(1)}to{transform:scale(1.05)}}
 #zarCall h2{margin:0;font-size:26px;font-weight:700}#zarCall .zcSub{margin:0;color:#c9b38c;font-size:14px;letter-spacing:.08em;text-transform:uppercase}
 #zarCall .zcText{margin:0;color:#e9dcc2;font-size:16px;max-height:34vh;overflow:auto;white-space:pre-wrap}
 #zarCall .zcRow{display:flex;gap:22px;justify-content:center;flex-wrap:wrap;margin-top:8px}
 #zarCall button{appearance:none;border:0;cursor:pointer;font:inherit;font-weight:700;color:#fff;border-radius:999px;min-height:56px;padding:0 24px;display:inline-flex;align-items:center;gap:8px}
 #zarCall .zcRound{width:68px;height:68px;padding:0;justify-content:center;font-size:28px}
 #zarCall .zcAccept{background:#2f9e5b}#zarCall .zcDecline{background:#c94a3c}#zarCall .zcOpt{background:#e2bd73;color:#1b140b}#zarCall .zcGhost{background:#ffffff1a}
 #zarCall button:focus-visible{outline:3px solid #fff;outline-offset:3px}
 #zarCall .zcHint{color:#a8957c;font-size:12.5px;margin:0}`;
 document.head.append(css);
 function startRing(){try{const ctx=new (window.AudioContext||window.webkitAudioContext)();let on=true;const beep=()=>{if(!on)return;[0,0.45].forEach(offset=>{const o=ctx.createOscillator(),g=ctx.createGain();o.type='sine';o.frequency.value=offset?480:440;g.gain.setValueAtTime(0.0001,ctx.currentTime+offset);g.gain.exponentialRampToValueAtTime(0.25,ctx.currentTime+offset+0.05);g.gain.exponentialRampToValueAtTime(0.0001,ctx.currentTime+offset+0.4);o.connect(g).connect(ctx.destination);o.start(ctx.currentTime+offset);o.stop(ctx.currentTime+offset+0.42);});};beep();const timer=setInterval(beep,2400);ring={stop(){on=false;clearInterval(timer);ctx.close().catch(()=>{});}};}catch{ring=null}if(navigator.vibrate)navigator.vibrate([600,300,600,300,600]);}
 function stopRing(){ring?.stop();ring=null;if(navigator.vibrate)navigator.vibrate(0);}
 function speak(text){return new Promise(resolve=>{if(!('speechSynthesis' in window)){resolve();return;}speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);u.lang='es-ES';u.rate=1;const voice=speechSynthesis.getVoices().find(v=>/^es(-|_)/i.test(v.lang));if(voice)u.voice=voice;u.onend=resolve;u.onerror=resolve;speechSynthesis.speak(u);setTimeout(resolve,Math.min(60000,1500+text.length*90));});}
 function listen(){return new Promise(resolve=>{const R=window.SpeechRecognition||window.webkitSpeechRecognition;if(!R){resolve(null);return;}const r=new R();r.lang='es-ES';r.maxAlternatives=3;let done=false;r.onresult=e=>{done=true;resolve([...e.results[0]].map(a=>a.transcript.toLowerCase()).join(' '));};r.onerror=()=>{if(!done)resolve(null)};r.onend=()=>{if(!done)resolve(null)};try{r.start();setTimeout(()=>{try{r.stop()}catch{}},7000);}catch{resolve(null)}});}
 async function answer(id,value){try{const r=await fetch('/api/calls/'+encodeURIComponent(id)+'/answer',{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify({answer:value})});const j=await r.json();return j.reply||'';}catch{return '';}}
 function close(){stopRing();try{speechSynthesis.cancel()}catch{}document.getElementById('zarCall')?.remove();current=null;const u=new URL(location.href);if(u.searchParams.has('zar_call')){u.searchParams.delete('zar_call');u.searchParams.delete('decline');history.replaceState(null,'',u.pathname+u.search+u.hash);}}
 async function show(id,decline){
  if(!id||current===id)return;current=id;
  let call;try{const r=await fetch('/api/calls/'+encodeURIComponent(id),{cache:'no-store'});const j=await r.json();if(!r.ok||!j.ok)throw 0;call=j.call;csrf=j.csrf||csrf;}catch{current=null;return;}
  if(decline){await answer(id,'declined');close();return;}
  const box=document.createElement('div');box.id='zarCall';box.setAttribute('role','dialog');box.setAttribute('aria-modal','true');box.setAttribute('aria-label','Llamada de ZAR');
  box.innerHTML='<div class="zc"><div class="zcAvatar" aria-hidden="true"></div><p class="zcSub">ZAR te llama</p><h2>'+esc(call.title)+'</h2><div class="zcRow"><button class="zcRound zcDecline" data-decline aria-label="Rechazar">✕</button><button class="zcRound zcAccept" data-accept aria-label="Contestar">📞</button></div><p class="zcHint">Contesta para que ZAR te lo cuente en voz alta.</p></div>';
  document.body.append(box);startRing();box.querySelector('[data-accept]').focus();
  box.querySelector('[data-decline]').onclick=async()=>{await answer(id,'declined');close();};
  box.querySelector('[data-accept]').onclick=async()=>{
   stopRing();box.classList.add('talking');
   const zc=box.querySelector('.zc');zc.innerHTML='<div class="zcAvatar" aria-hidden="true"></div><p class="zcSub">En llamada con ZAR</p><h2>'+esc(call.title)+'</h2><p class="zcText">'+esc(call.text)+'</p><div class="zcRow" data-options></div><p class="zcHint" data-hint></p><div class="zcRow"><button class="zcGhost" data-hang>Colgar</button></div>';
   zc.querySelector('[data-hang]').onclick=async()=>{if(!call.options.length)await answer(id,'heard');close();};
   await speak(call.title+'. '+call.text);
   box.classList.remove('talking');
   const opts=zc.querySelector('[data-options]'),hint=zc.querySelector('[data-hint]');
   if(!call.options.length){await answer(id,'heard');hint.textContent='Mensaje entregado.';return;}
   opts.innerHTML=call.options.map(o=>'<button class="'+(o.id==='yes'?'zcOpt':'zcGhost')+'" data-answer="'+esc(o.id)+'">'+esc(o.label)+'</button>').join('');
   const decide=async value=>{opts.innerHTML='';hint.textContent='Un momento…';const reply=await answer(id,value);hint.textContent=reply;box.classList.add('talking');await speak(reply||'De acuerdo.');box.classList.remove('talking');setTimeout(close,2500);};
   opts.querySelectorAll('[data-answer]').forEach(b=>b.onclick=()=>decide(b.dataset.answer));
   hint.textContent='Responde «sí» o «no», o pulsa un botón.';
   const heard=await listen();if(heard&&document.getElementById('zarCall')&&opts.children.length){if(/\b(s[ií]|vale|claro|publ[ií]ca|adelante|ok)\b/.test(heard))decide('yes');else if(/\b(no|luego|despu[eé]s|m[aá]s tarde|espera)\b/.test(heard))decide('no');}
  };
 }
 async function registerWorker(){if(!('serviceWorker' in navigator))return null;try{return await navigator.serviceWorker.register('/zar-sw.js',{scope:'/'});}catch{return null;}}
 const toKey=b64=>{const s=(b64+'='.repeat((4-b64.length%4)%4)).replace(/-/g,'+').replace(/_/g,'/');return Uint8Array.from(atob(s),c=>c.charCodeAt(0));};
 window.zarEnableCalls=async(vapidKey,token)=>{
  if(!('serviceWorker' in navigator)||!('PushManager' in window))throw Error('Este navegador no admite llamadas push. En iPhone, añade ZAR a la pantalla de inicio y ábrelo desde allí.');
  const permission=await Notification.requestPermission();if(permission!=='granted')throw Error('Permite las notificaciones de ZAR para recibir llamadas.');
  const reg=await registerWorker();if(!reg)throw Error('No se pudo activar el servicio de llamadas.');await navigator.serviceWorker.ready;
  let sub=await reg.pushManager.getSubscription();if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:toKey(vapidKey)});
  const label=/android/i.test(navigator.userAgent)?'Android':/iphone|ipad/i.test(navigator.userAgent)?'iPhone/iPad':/windows/i.test(navigator.userAgent)?'PC Windows':/mac/i.test(navigator.userAgent)?'Mac':'Navegador';
  const r=await fetch('/api/notify/push/subscribe',{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':token},body:JSON.stringify({subscription:sub.toJSON(),label})});const j=await r.json();if(!r.ok||!j.ok)throw Error('No se pudo registrar este dispositivo.');return j.settings;
 };
 if('serviceWorker' in navigator){navigator.serviceWorker.addEventListener('message',e=>{const d=e.data||{};if(d.type==='zar-push'&&d.data?.type==='call')show(d.data.id);if(d.type==='zar-open-call'){const u=new URL(d.url,location.origin);show(u.searchParams.get('zar_call'),u.searchParams.has('decline'));}});if(Notification?.permission==='granted')registerWorker();}
 const params=new URLSearchParams(location.search);if(params.get('zar_call'))show(params.get('zar_call'),params.has('decline'));
 window.zarShowCall=show;
})();
