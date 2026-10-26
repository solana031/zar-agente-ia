/* Read TCF metadata only; no TC string, cookie or consent choice is persisted here. */
(() => {
  'use strict';
  const own=document.currentScript,root=document.documentElement;
  const empty=()=>({api:false,loaded:false,readable:false,cmp_id:0,event_status:'',has_tc_string:false,cmp_status:''});
  let state=empty(),listener=null,attached=false,stopped=false,api=null;
  const deny=()=>({ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied',analytics_storage:'denied'});
  const update=value=>{if(typeof window.gtag==='function')window.gtag('consent','update',value);};
  function show(){root.dataset.cmpStatus=state.api?(state.loaded&&state.readable&&state.has_tc_string&&state.cmp_id===300&&['tcloaded','useractioncomplete'].includes(state.event_status)?'READY':'REVIEW_REQUIRED'):'MISSING';root.dataset.cmpId=String(state.cmp_id);}
  function consent(data,success){
    update(deny());
    if(root.dataset.cmpStatus!=='READY'||!success||!data||!['tcloaded','useractioncomplete'].includes(data.eventStatus)||data.cmpId!==300)return;
    window.googlefc.callbackQueue.push(()=>{
      if(stopped||!['tcloaded','useractioncomplete'].includes(state.event_status))return;
      try{
        const values=window.googlefc.getGoogleConsentModeValues(),mapped=deny();
        const fields={ad_storage:'adStoragePurposeConsentStatus',ad_user_data:'adUserDataPurposeConsentStatus',ad_personalization:'adPersonalizationPurposeConsentStatus',analytics_storage:'analyticsStoragePurposeConsentStatus'};
        for(const [key,field] of Object.entries(fields))if(values[field]===1)mapped[key]='granted';
        update(mapped);
      }catch(_){update(deny());}
    });
  }
  function attach(){
    if(stopped||attached||typeof window.__tcfapi!=='function')return;
    attached=true;api=window.__tcfapi;state.api=true;show();
    try{
      api('ping',2,p=>{if(stopped)return;state.loaded=p?.cmpLoaded===true;state.cmp_status=['stub','loading','loaded','error'].includes(p?.cmpStatus)?p.cmpStatus:'';show();});
      api('addEventListener',2,(data,success)=>{
        if(stopped)return;
        listener=data?.listenerId??listener;
        state.readable=success===true&&!!data;
        state.cmp_id=Number.isInteger(data?.cmpId)?data.cmpId:0;
        state.event_status=['tcloaded','cmpuishown','useractioncomplete'].includes(data?.eventStatus)?data.eventStatus:'';
        state.has_tc_string=success===true&&typeof data?.tcString==='string'&&data.tcString.length>0;
        if(['stub','loading','loaded','error'].includes(data?.cmpStatus))state.cmp_status=data.cmpStatus;
        state.loaded=state.cmp_status==='loaded';show();consent(data,success);
      });
    }catch(_){state=Object.assign(empty(),{api:true,cmp_status:'error'});show();update(deny());}
  }
  window.googlefc=window.googlefc||{};window.googlefc.callbackQueue=window.googlefc.callbackQueue||[];
  window.googlefc.callbackQueue.push({CONSENT_API_READY:attach});
  // Consent Mode changes are also delivered through TCF useractioncomplete above.
  window.googlefc.callbackQueue.push({CONSENT_MODE_DATA_READY:()=>{if(state.cmp_id===300)consent({cmpId:300,eventStatus:state.event_status},true);}});
  show();attach();
  const poll=setInterval(attach,250);setTimeout(()=>clearInterval(poll),20000);
  window.addEventListener('pagehide',()=>{stopped=true;clearInterval(poll);if(api&&listener!==null)try{api('removeEventListener',2,()=>{},listener);}catch(_){}},{once:true});
  document.addEventListener('click',event=>{
    const link=event.target.closest('a[href$="cookies/#options"]');
    if(link&&root.dataset.cmpStatus==='READY'&&state.cmp_id===300){event.preventDefault();update(deny());window.googlefc.callbackQueue.push(()=>{try{window.googlefc.showRevocationMessage();}catch(_){location.href=link.href;}});}
  });
  const nonce=new URLSearchParams(location.hash.slice(1)).get('zar-cmp-probe');
  const target=own?.dataset.probeOrigin;
  if(nonce&&/^[A-Za-z0-9_-]{40,60}$/.test(nonce)&&window.opener&&target==='https://web-production-a9565.up.railway.app'){
    setTimeout(()=>window.opener.postMessage({type:'zar-cmp-probe',nonce,probe:{...state}},target),8500);
  }
})();
