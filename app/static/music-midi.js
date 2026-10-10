/* Bounded Standard MIDI File reader. Rejects SMPTE/type 2; preserves beat times. */
(()=>{'use strict';
 function read(buffer,name='MIDI importado'){
  const M=window.ZarMusic,b=new Uint8Array(buffer),v=new DataView(buffer);let pos=0;
  if(b.length>2*1024*1024)throw Error('MIDI supera 2 MB.');
  const need=n=>{if(pos+n>b.length)throw Error('MIDI truncado.');};
  const u8=()=>{need(1);return b[pos++];},u16=()=>{need(2);const n=v.getUint16(pos);pos+=2;return n;},u32=()=>{need(4);const n=v.getUint32(pos);pos+=4;return n;},tag=()=>String.fromCharCode(u8(),u8(),u8(),u8());
  const variable=end=>{let n=0;for(let i=0;i<4;i++){if(pos>=end)throw Error('Delta MIDI inválido.');const x=u8();n=n*128+(x&127);if(!(x&128))return n;}throw Error('Delta MIDI demasiado largo.');};
  if(tag()!=='MThd')throw Error('No es un archivo MIDI estándar.');const header=u32();if(header<6||header>64)throw Error('Cabecera MIDI inválida.');const format=u16(),count=u16(),division=u16();if(format>1||!count||count>25||(division&32768)||!division)throw Error('Solo MIDI tipo 0/1 con PPQN, máximo 25 tracks.');pos+=header-6;need(0);
  const p=M.empty();p.name=name.replace(/\.midi?$/i,'');let tempo=null,endBeat=0,tempoChanges=0;
  for(let ti=0;ti<count;ti++){
   if(tag()!=='MTrk')throw Error('Track MIDI inválido.');const length=u32(),end=pos+length;need(length);let tick=0,running=0,events=0;const tracks=new Map(),held=new Map();
   const tFor=channel=>{if(!tracks.has(channel)){const t=M.track(channel===9?'Kick':'Piano');t.name='MIDI '+(ti+1)+' · canal '+(channel+1);tracks.set(channel,t);}return tracks.get(channel);};
   const off=(ch,key)=>{const q=held.get(ch+':'+key),n=q?.pop();if(n){n.duration=Math.max(.0625,tick/division-n.start);endBeat=Math.max(endBeat,n.start+n.duration);}};
   while(pos<end){if(++events>100000)throw Error('Demasiados eventos MIDI.');tick+=variable(end);if(tick/division>256)throw Error('MIDI supera 64 compases de 4/4.');let status=u8();if(status<128){if(!running)throw Error('Running status MIDI inválido.');pos--;status=running;}else if(status<240)running=status;
    if(status===255){running=0;const type=u8(),n=variable(end);if(pos+n>end)throw Error('Metaevento truncado.');if(type===81&&n===3){const usec=b[pos]*65536+b[pos+1]*256+b[pos+2];if(!usec)throw Error('Tempo MIDI inválido.');if(tempo===null)tempo=60000000/usec;else tempoChanges++;}pos+=n;if(type===47)break;continue;}
    if(status===240||status===247){running=0;const n=variable(end);if(pos+n>end)throw Error('SysEx truncado.');pos+=n;continue;}
    const op=status>>4,ch=status&15;if(op<8||op>14)throw Error('Evento MIDI no admitido.');const a=u8(),c=op===12||op===13?0:u8();if(a>127||c>127)throw Error('Datos MIDI inválidos.');
    if(op===9&&c){const t=tFor(ch);if(t.notes.length>=8192)throw Error('Demasiadas notas.');const note={id:M.id(),pitch:a,start:tick/division,duration:.25,velocity:c/127};t.notes.push(note);const key=ch+':'+a;if(!held.has(key))held.set(key,[]);held.get(key).push(note);}else if(op===8||op===9)off(ch,a);
   }
   for(const notes of held.values())for(const n of notes){n.duration=Math.max(.0625,tick/division-n.start);endBeat=Math.max(endBeat,n.start+n.duration);}pos=end;p.tracks.push(...tracks.values());if(p.tracks.length>24)throw Error('Más de 24 pistas con notas.');
  }
  if(!p.tracks.length)throw Error('MIDI sin notas.');const bpm=tempo??120;if(bpm<40||bpm>240)throw Error('Tempo fuera de rango 40–240.');p.tempo=bpm;p.bars=Math.max(1,Math.ceil(endBeat/4));p.midi_import={tempo_changes_ignored:tempoChanges,source_format:format,program_mapping:'Piano; canal 10 Kick. Programas, sustain y cambios de tempo no aplicados.'};return M.validate(p);
 }
 window.ZarMidiImport={read};
})();
