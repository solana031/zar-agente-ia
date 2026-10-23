/* Same-origin completion hint only; the opener must reverify server-side. */
(()=>{
 const provider=document.body.dataset.oauthProvider,status=document.body.dataset.oauthStatus;
 try{history.replaceState(null,'',location.pathname);}catch{}
 if(!provider||!status)return;
 try{if(window.opener&&!window.opener.closed){window.opener.postMessage({type:'zar-oauth-result',provider,status},location.origin);window.opener.focus();setTimeout(()=>window.close(),900);}}catch{}
})();
