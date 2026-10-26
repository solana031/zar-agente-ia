/* Offline TCF/Google FC contract: loaded, delayed, rejected, granular and failure. */
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('app/static/reposnews/consent.js','utf8');
function fixture({stub=false,noApi=false,throws=false,cmpId=300}={}){
 const updates=[],events={},queue=[],scheduled=[],callbacks={};let listener,removed=false;
 const root={dataset:{}},document={currentScript:{dataset:{}},documentElement:root,addEventListener:(name,fn)=>events[name]=fn};
 const window={gtag:(...args)=>updates.push(args),googlefc:{callbackQueue:{push:value=>{queue.push(value);if(typeof value==='function')value();}},getGoogleConsentModeValues:()=>callbacks.values||{},showRevocationMessage:()=>callbacks.revoked=true},addEventListener:(name,fn)=>events[name]=fn};
 if(!noApi)window.__tcfapi=(command,version,fn,id)=>{assert.equal(version,2);if(throws)throw Error('CMP unavailable');if(command==='ping')fn({cmpLoaded:!stub,cmpStatus:stub?'stub':'loaded'});if(command==='addEventListener'){listener=fn;fn({listenerId:7,cmpId,cmpStatus:stub?'stub':'loaded',eventStatus:stub?'':'tcloaded',tcString:stub?'':'TRANSIENT-ONLY'},true);}if(command==='removeEventListener'){assert.equal(id,7);removed=true;}};
 vm.runInNewContext(source,{window,document,location:{hash:'',href:''},URLSearchParams,setInterval:fn=>(scheduled.push(fn),1),clearInterval:()=>{},setTimeout:()=>1});
 return {root,updates,queue,events,window,callbacks,get removed(){return removed;},emit:(event,data={})=>listener({listenerId:7,cmpId,cmpStatus:'loaded',eventStatus:event,tcString:'TRANSIENT-ONLY',...data},true)};
}
let f=fixture({noApi:true});assert.equal(f.root.dataset.cmpStatus,'MISSING');
f=fixture({stub:true});assert.equal(f.root.dataset.cmpStatus,'REVIEW_REQUIRED');
f=fixture({throws:true});assert.equal(f.root.dataset.cmpStatus,'REVIEW_REQUIRED');
f=fixture({cmpId:42});assert.equal(f.root.dataset.cmpStatus,'REVIEW_REQUIRED');
f=fixture();assert.equal(f.root.dataset.cmpStatus,'READY');
assert.equal(f.updates.at(-1)[2].ad_storage,'denied');
f.callbacks.values={adStoragePurposeConsentStatus:1,adUserDataPurposeConsentStatus:2,adPersonalizationPurposeConsentStatus:1,analyticsStoragePurposeConsentStatus:0};
f.emit('useractioncomplete');let v=f.updates.at(-1)[2];assert.equal(v.ad_storage,'granted');assert.equal(v.ad_user_data,'denied');assert.equal(v.ad_personalization,'granted');assert.equal(v.analytics_storage,'denied');
f.callbacks.values={adStoragePurposeConsentStatus:2,adUserDataPurposeConsentStatus:2,adPersonalizationPurposeConsentStatus:2,analyticsStoragePurposeConsentStatus:2};
f.emit('useractioncomplete');assert.ok(Object.values(f.updates.at(-1)[2]).every(x=>x==='denied'));
f.emit('cmpuishown');assert.ok(Object.values(f.updates.at(-1)[2]).every(x=>x==='denied'));
f.emit('tcloaded',{tcString:''});assert.equal(f.root.dataset.cmpStatus,'REVIEW_REQUIRED');
assert.equal(JSON.stringify(f.root.dataset).includes('TRANSIENT-ONLY'),false);
f.events.pagehide();assert.equal(f.removed,true);
assert.equal(source.includes('localStorage'),false);assert.equal(source.includes('adsbygoogle'),false);
console.log('PASS: missing/stub/error/unverified CMP, TCF readiness, granular grant, rejection, empty string, removal; no ads or TC persistence');
