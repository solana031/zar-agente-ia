const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
global.window={};vm.runInThisContext(fs.readFileSync('app/static/music-engine.js','utf8'));vm.runInThisContext(fs.readFileSync('app/static/music-midi.js','utf8'));
(async()=>{const M=window.ZarMusic,p=M.validate(M.planner({bpm:140,bars:8,key:'A',scale:'minor',seed:7})),dummy=(p.tracks.forEach((t,i)=>t.notes=Array.from({length:4},(_,j)=>({id:M.id(),pitch:48+i,start:j*8,duration:2.5,velocity:.4+j*.1})))),bytes=await M.midi(p).arrayBuffer(),r=window.ZarMidiImport.read(bytes,'trap.mid');
assert.equal(r.tracks.length,6);assert(Math.abs(r.tempo-140)<.001);assert.equal(r.bars,7);
for(let i=0;i<6;i++){assert.equal(r.tracks[i].notes.length,p.tracks[i].notes.length);for(let j=0;j<p.tracks[i].notes.length;j++){const a=p.tracks[i].notes[j],b=r.tracks[i].notes[j];assert.equal(a.pitch,b.pitch);assert(Math.abs(a.start-b.start)<.003);assert(Math.abs(a.duration-b.duration)<.003);assert(Math.abs(a.velocity-b.velocity)<.01);}}
for(const cut of [0,4,10,bytes.byteLength-4])assert.throws(()=>window.ZarMidiImport.read(bytes.slice(0,cut)));
const invalid=bytes.slice(0);new DataView(invalid).setUint16(12,0x8001);assert.throws(()=>window.ZarMidiImport.read(invalid),/PPQN/);
assert.throws(()=>window.ZarMidiImport.read(new ArrayBuffer(2*1024*1024+1)),/2 MB/);console.log('PASS MIDI roundtrip: tracks, tempo, beats, duration, velocity; truncation and SMPTE rejected');})();
