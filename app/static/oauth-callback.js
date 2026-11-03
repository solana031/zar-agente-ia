/* Same-origin completion hint only; the opener must reverify server-side. */
(()=>{
 const provider=document.body.dataset.oauthProvider,status=document.body.dataset.oauthStatus;
 try{history.replaceState(null,'',location.pathname);}catch{}
 if(!provider||!status)return;
 try{if(window.opener&&!window.opener.closed){window.opener.postMessage({type:'zar-oauth-result',provider,status},location.origin);window.opener.focus();setTimeout(()=>window.close(),900);return;}}catch{}
 // A same-tab browser flow retains its ZAR cookie and server-side receipt.
 // A fresh external browser has no ZAR login; it must never be granted one here.
 if(document.body.dataset.oauthReturn==='1')location.replace('/accounts');
})();
