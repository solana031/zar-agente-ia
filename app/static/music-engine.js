/* ZAR Music: original Web Audio synthesis, beat-domain model and offline renderer. */
(()=>{'use strict';
 const clamp=(v,a,b)=>Math.max(a,Math.min(b,Number(v))),id=()=>crypto.randomUUID(),copy=x=>JSON.parse(JSON.stringify(x));
 const instruments=['Kick','Snare','HiHat','Clap','Bass','Synth','PolySynth','Piano','Pad','Lead','Pluck','Audio'];
 const track=(name)=>({id:id(),name,instrument:name,volume:.55,pan:0,mute:false,solo:false,notes:[],clips:[],effects:[]});
 function empty(){return {schema:'ZarMusicProject',version:1,id:id(),name:'Nueva composición',tempo:140,key:'A',scale:'minor',signature:4,bars:8,seed:1,tracks:[],assets:{},sections:[],master:{volume:.7,preset:'Clean'},updated_at:new Date().toISOString()};}
 function validate(p){
  if(!p||p.schema!=='ZarMusicProject'||p.version!==1||!Array.isArray(p.tracks)||p.tracks.length>24)throw Error('Formato de proyecto no compatible.');
  p=copy(p);p.tempo=clamp(p.tempo,40,240);p.bars=clamp(p.bars,1,64);p.signature=[3,4,6].includes(p.signature)?p.signature:4;p.assets=p.assets||{};p.master=p.master||{volume:.7,preset:'Clean'};
  if(!Number.isFinite(p.tempo)||!Number.isFinite(p.bars))throw Error('Tempo o duración inválidos.');
  for(const t of p.tracks){if(!instruments.includes(t.instrument)||!Array.isArray(t.notes)||t.notes.length>8192||!Array.isArray(t.clips)||t.clips.length>128)throw Error('Pista inválida.');t.volume=clamp(t.volume,0,1);t.pan=clamp(t.pan,-1,1);t.effects=(t.effects||[]).slice(0,9);for(const n of t.notes){for(const k of ['pitch','start','duration','velocity'])if(!Number.isFinite(n[k]))throw Error('Nota inválida.');n.pitch=clamp(n.pitch,0,127);n.start=clamp(n.start,0,384);n.duration=clamp(n.duration,.0625,384);n.velocity=clamp(n.velocity,.01,1);}for(const c of t.clips){if(!p.assets[c.asset]||![c.start,c.offset,c.duration].every(Number.isFinite)||c.start<0||c.offset<0||c.duration<=0)throw Error('Clip inválido.');}}
  return p;
 }
 function planner(options={}){
  const p=empty();p.name=options.name||'Base original · '+(options.genre||'Trap');p.tempo=clamp(options.bpm||140,40,240);p.bars=clamp(options.bars||8,4,32);p.key=options.key||'A';p.scale=options.scale||'minor';p.seed=Number(options.seed)||Math.floor(Math.random()*100000);
  let seed=p.seed>>>0;const rand=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296;};
  const root=({C:48,'C#':49,D:50,'D#':51,E:52,F:53,'F#':54,G:55,'G#':56,A:57,'A#':58,B:59})[p.key]??57;
  const scale=p.scale==='major'?[0,2,4,5,7,9,11]:[0,2,3,5,7,8,10],chords=[0,5,3,6],genre=String(options.genre||'trap').toLowerCase();
  p.tracks=['Kick','Snare','HiHat','Bass','Piano','Pad'].map(track);
  const note=(t,pitch,start,duration,velocity)=>t.notes.push({id:id(),pitch,start,duration,velocity});
  for(let bar=0;bar<p.bars;bar++){
   const b=bar*4,degree=chords[bar%4],r=root+scale[degree],energy=options.energy??.7;
   const kicks=['house','techno'].includes(genre)?[0,1,2,3]:genre==='reggaeton'?[0,1.5,2.5]:[0,1.75,3];
   kicks.forEach(x=>note(p.tracks[0],36,b+x,.25,.85));[1,3].forEach(x=>note(p.tracks[1],38,b+x,.2,.65));
   for(let s=0;s<16;s++)if(s%2===0||rand()<energy*.55)note(p.tracks[2],42,b+s*.25+(s%2?(options.swing||0)*.1:0),.08,.25+rand()*.3);
   [0,1.75,3].forEach((x,i)=>note(p.tracks[3],r-24,b+x,i===2?.85:1.4,.7));
   [0,2,4].forEach(d=>{let pitch=root+scale[(degree+d)%7]+12*(Math.floor((degree+d)/7));note(p.tracks[4],pitch+12,b,3.7,.4);note(p.tracks[5],pitch,b,3.9,.22);});
   if(bar%2===1)[.5,1.5,2.75].forEach(x=>note(p.tracks[4],root+12+scale[Math.floor(rand()*7)],b+x,.4,.35));
  }
  p.sections=[{name:'Intro',start:0,bars:2},{name:'Verse',start:8,bars:Math.max(2,p.bars-4)},{name:'Outro',start:(p.bars-2)*4,bars:2}];return p;
 }
 const fxNames=['EQ','Compressor','Limiter','Reverb','Delay','Chorus','Distortion','Filter','Gate'];
 function chain(ctx,t,destination,modulators=[]){
  const input=ctx.createGain();let end=input;
  for(const f of (t.effects||[]).filter(f=>f.on!==false)){
   let node;const amount=clamp(f.amount??.4,0,1);
   if(f.type==='EQ'||f.type==='Filter'){node=ctx.createBiquadFilter();node.type=f.type==='EQ'?'peaking':'lowpass';node.frequency.value=f.type==='EQ'?1000:200+amount*16000;node.Q.value=.7;node.gain.value=(amount-.5)*16;}
   else if(f.type==='Compressor'||f.type==='Limiter'){node=ctx.createDynamicsCompressor();node.threshold.value=f.type==='Limiter'?-2:-12-amount*20;node.ratio.value=f.type==='Limiter'?20:2+amount*8;node.attack.value=.003;node.release.value=.15;}
   else if(f.type==='Distortion'){node=ctx.createWaveShaper();const curve=new Float32Array(1024),drive=1+amount*25;for(let i=0;i<curve.length;i++){const x=i*2/1023-1;curve[i]=Math.tanh(drive*x)/Math.tanh(drive);}node.curve=curve;node.oversample='2x';}
   else if(['Delay','Chorus','Reverb'].includes(f.type)){
    const mix=ctx.createGain(),wet=ctx.createGain();wet.gain.value=amount*.5;end.connect(mix);
    if(f.type==='Reverb'){node=ctx.createConvolver();const impulse=ctx.createBuffer(2,ctx.sampleRate*.7,ctx.sampleRate);for(let c=0;c<2;c++){const a=impulse.getChannelData(c);let s=17;for(let i=0;i<a.length;i++){s=(s*16807)%2147483647;a[i]=(s/2147483647*2-1)*Math.pow(1-i/a.length,3);}}node.buffer=impulse;}
    else{node=ctx.createDelay(1);node.delayTime.value=f.type==='Chorus'?.018:.27;if(f.type==='Chorus'){const lfo=ctx.createOscillator(),depth=ctx.createGain();lfo.frequency.value=.8;depth.gain.value=.006;lfo.connect(depth).connect(node.delayTime);lfo.start();modulators.push(lfo);}}
    end.connect(node).connect(wet).connect(mix);end=mix;continue;
   }else if(f.type==='Gate'){node=ctx.createWaveShaper();const a=new Float32Array(1024),threshold=.005+amount*.05;for(let i=0;i<a.length;i++){const x=i*2/1023-1;a[i]=Math.abs(x)<threshold?0:x;}node.curve=a;}
   if(node){end.connect(node);end=node;}
  }
  const gain=ctx.createGain(),pan=ctx.createStereoPanner(),meter=ctx.createAnalyser();gain.gain.value=t.volume;pan.pan.value=t.pan;meter.fftSize=256;end.connect(gain).connect(pan).connect(meter).connect(destination);return {input,gain,pan,meter};
 }
 function voice(ctx,t,n,when,length,out,nodes){
  const env=ctx.createGain();env.connect(out);const velocity=n.velocity*.27,drum=['Kick','Snare','HiHat','Clap'].includes(t.instrument);let source;
  if(['Snare','HiHat','Clap'].includes(t.instrument)){source=ctx.createBufferSource();const size=Math.ceil(ctx.sampleRate*(t.instrument==='HiHat'?.12:.22)),b=ctx.createBuffer(1,size,ctx.sampleRate);const a=b.getChannelData(0);let s=123;for(let i=0;i<size;i++){s=(s*16807)%2147483647;a[i]=s/2147483647*2-1;}source.buffer=b;const filter=ctx.createBiquadFilter();filter.type='highpass';filter.frequency.value=t.instrument==='HiHat'?6500:1300;source.connect(filter).connect(env);length=t.instrument==='HiHat'?.1:.2;}
  else{source=ctx.createOscillator();source.type=t.instrument==='Bass'||t.instrument==='Kick'?'sine':t.instrument==='Pad'?'triangle':t.instrument==='Piano'?'triangle':t.instrument==='Pluck'?'sine':'sawtooth';const freq=440*Math.pow(2,(n.pitch-69)/12);source.frequency.setValueAtTime(t.instrument==='Kick'?150:freq,when);if(t.instrument==='Kick'){source.frequency.exponentialRampToValueAtTime(42,when+.16);length=.22;}source.connect(env);}
  const attack=t.instrument==='Pad'?.1:.004;env.gain.setValueAtTime(0,when);env.gain.linearRampToValueAtTime(velocity,when+attack);env.gain.exponentialRampToValueAtTime(.0001,when+Math.max(attack+.01,length));source.start(when);source.stop(when+length+.03);if(nodes)nodes.push(source);
 }
 function graph(ctx,p){const master=ctx.createGain(),limiter=ctx.createDynamicsCompressor(),modulators=[];master.gain.value=clamp(p.master.volume??.7,0,1);limiter.threshold.value=p.master.preset==='Loud'?-12:-3;limiter.ratio.value=12;limiter.attack.value=p.master.preset==='Punchy'?.02:.003;if(p.master.preset==='Warm'){const eq=ctx.createBiquadFilter();eq.type='lowshelf';eq.frequency.value=180;eq.gain.value=2;master.connect(eq).connect(limiter);}else master.connect(limiter);limiter.connect(ctx.destination);const solo=p.tracks.some(t=>t.solo);const tracks=new Map();for(const t of p.tracks)if(!t.mute&&(!solo||t.solo))tracks.set(t.id,chain(ctx,t,master,modulators));return {tracks,master,modulators};}
 function assetBuffer(ctx,a){if(a?.pcm){const raw=atob(a.pcm);if(![1,2].includes(a.channels)||!Number.isInteger(a.length)||a.length<1||a.length>5760000||raw.length!==a.length*a.channels*2||!Number.isFinite(a.sampleRate)||a.sampleRate<8000||a.sampleRate>96000)throw Error('PCM inválido.');const bytes=Uint8Array.from(raw,c=>c.charCodeAt(0)),v=new DataView(bytes.buffer),b=ctx.createBuffer(a.channels,a.length,a.sampleRate);for(let c=0;c<a.channels;c++){const out=b.getChannelData(c);for(let i=0;i<a.length;i++)out[i]=v.getInt16((i*a.channels+c)*2,true)/32768;}return b;}if(!a||!Array.isArray(a.channels)||a.channels.length>2||!a.channels.length||!Number.isFinite(a.sampleRate)||a.sampleRate<8000||a.sampleRate>96000)throw Error('Asset de audio inválido.');const length=a.channels[0].length;if(length>ctx.sampleRate*60)throw Error('Audio importado supera 60 segundos.');const b=ctx.createBuffer(a.channels.length,length,a.sampleRate);a.channels.forEach((c,i)=>{if(c.length!==length||!c.every(Number.isFinite))throw Error('Audio inválido.');b.copyToChannel(Float32Array.from(c),i);});return b;}
 function schedule(ctx,p,g,from,to,origin,nodes){const beat=60/p.tempo;for(const t of p.tracks){const ch=g.tracks.get(t.id);if(!ch)continue;for(const n of t.notes)if(n.start+n.duration>from&&n.start<to)voice(ctx,t,n,origin+(Math.max(n.start,from)-from)*beat,(n.duration-Math.max(0,from-n.start))*beat,ch.input,nodes);for(const c of t.clips){const end=c.start+c.duration;if(c.start>=to||end<=from)continue;const start=Math.max(c.start,from),duration=Math.min(end,to)-start,b=assetBuffer(ctx,p.assets[c.asset]),s=ctx.createBufferSource(),gain=ctx.createGain();s.buffer=b;const when=origin+(start-from)*beat,seconds=duration*beat;gain.gain.setValueAtTime(c.gain??1,when);if(c.fadeIn) {gain.gain.setValueAtTime(.0001,when);gain.gain.linearRampToValueAtTime(c.gain??1,when+Math.min(c.fadeIn,seconds/2));}if(c.fadeOut){gain.gain.setValueAtTime(c.gain??1,when+Math.max(0,seconds-c.fadeOut));gain.gain.linearRampToValueAtTime(0,when+seconds);}s.connect(gain).connect(ch.input);s.start(when,c.offset+(start-c.start)*beat,seconds);nodes?.push(s);}}}
 class Engine{
  constructor(){this.ctx=null;this.nodes=[];this.playing=false;this.position=0;this.loop=false;this.metro=false;this.timer=null;this.graph=null;}
  async context(){if(!this.ctx)this.ctx=new AudioContext();await this.ctx.resume();return this.ctx;}
  stop(reset=true){clearInterval(this.timer);if(this.playing&&this.ctx)this.position=this.current();this.playing=false;this.nodes.forEach(n=>{try{n.stop();}catch{}});this.nodes=[];this.graph?.modulators.forEach(n=>{try{n.stop();}catch{}});this.graph?.master.disconnect();this.graph=null;if(reset)this.position=0;}
  current(){return this.playing?this.offset+(this.ctx.currentTime-this.origin)*this.project.tempo/60:this.position;}
  async play(p){this.stop(false);this.project=p;const ctx=await this.context(),end=p.bars*p.signature;if(this.position>=end)this.position=0;this.offset=this.position;this.origin=ctx.currentTime+.04;this.graph=graph(ctx,p);schedule(ctx,p,this.graph,this.offset,end,this.origin,this.nodes);if(this.metro)for(let b=Math.ceil(this.offset);b<end;b++)voice(ctx,{instrument:'Pluck'},{pitch:b%p.signature?84:91,velocity:.25},this.origin+(b-this.offset)*60/p.tempo,.025,this.graph.master,this.nodes);this.playing=true;this.timer=setInterval(()=>{if(this.current()>=end){this.stop();if(this.loop)this.play(p);}},60);}
  async audition(t,pitch){const c=await this.context();voice(c,t,{pitch,velocity:.7},c.currentTime,.4,c.destination,this.nodes);}
  async offline(p,only=null){p=validate(p);if(only)p.tracks=p.tracks.filter(t=>t.id===only).map(t=>({...t,mute:false,solo:false}));const seconds=p.bars*p.signature*60/p.tempo+.8;if(seconds>120)throw Error('Exportación limitada a 120 s para proteger memoria.');const ctx=new OfflineAudioContext(2,Math.ceil(seconds*44100),44100),g=graph(ctx,p);schedule(ctx,p,g,0,p.bars*p.signature,0,null);return ctx.startRendering();}
 }
 function wav(b){const length=b.length*b.numberOfChannels*2,data=new ArrayBuffer(44+length),v=new DataView(data);const str=(o,s)=>{for(let i=0;i<s.length;i++)v.setUint8(o+i,s.charCodeAt(i));};str(0,'RIFF');v.setUint32(4,36+length,true);str(8,'WAVE');str(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,b.numberOfChannels,true);v.setUint32(24,b.sampleRate,true);v.setUint32(28,b.sampleRate*b.numberOfChannels*2,true);v.setUint16(32,b.numberOfChannels*2,true);v.setUint16(34,16,true);str(36,'data');v.setUint32(40,length,true);let o=44;for(let i=0;i<b.length;i++)for(let c=0;c<b.numberOfChannels;c++){const s=clamp(b.getChannelData(c)[i],-1,1);v.setInt16(o,s<0?s*32768:s*32767,true);o+=2;}return new Blob([data],{type:'audio/wav'});}
 function midi(p){const bytes=[],word=(a,n)=>a.push(n>>>8&255,n&255),u32=(a,n)=>a.push(n>>>24&255,n>>>16&255,n>>>8&255,n&255),vlq=n=>{const a=[n&127];while(n>>=7)a.unshift((n&127)|128);return a;};bytes.push(...[...'MThd'].map(c=>c.charCodeAt()));u32(bytes,6);word(bytes,1);word(bytes,p.tracks.length+1);word(bytes,480);const chunk=a=>{bytes.push(...[...'MTrk'].map(c=>c.charCodeAt()));u32(bytes,a.length);bytes.push(...a);};const tempo=Math.round(60000000/p.tempo);chunk([0,255,81,3,tempo>>>16&255,tempo>>>8&255,tempo&255,0,255,47,0]);p.tracks.forEach((t,index)=>{const events=[];for(const n of t.notes){events.push({at:Math.round(n.start*480),data:[144+(index%9),n.pitch,Math.round(n.velocity*127)]},{at:Math.round((n.start+n.duration)*480),data:[128+(index%9),n.pitch,0]});}events.sort((a,b)=>a.at-b.at||a.data[0]-b.data[0]);let last=0,a=[];for(const e of events){a.push(...vlq(e.at-last),...e.data);last=e.at;}a.push(0,255,47,0);chunk(a);});return new Blob([Uint8Array.from(bytes)],{type:'audio/midi'});}
 window.ZarMusic={empty,track,planner,validate,copy,clamp,id,Engine,wav,midi,instruments,fxNames,assetBuffer};
})();
