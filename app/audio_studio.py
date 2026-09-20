import os, json, math, wave, uuid, random, subprocess
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR=Path(os.environ.get('ZAR_DATA_DIR','/data'))
ROOT=DATA_DIR/'audio_studio'
PROJECTS=ROOT/'projects'; TRACKS=ROOT/'tracks'; OUTPUTS=ROOT/'outputs'
for p in (PROJECTS,TRACKS,OUTPUTS): p.mkdir(parents=True,exist_ok=True)

GENRE_FAMILIES={
 # Electronic / club
 'house','techno','hardcore','hardstyle','gabber','frenchcore','trance','psytrance','dubstep','drumandbass','breakbeat','garage','ukgarage','grime','electro','edm','downtempo','ambient',
 # Urban / Latin
 'trap','drill','hiphop','rnb','reggaeton','dancehall','afrobeats','afrohouse','funk','samba','bossa','cumbia','salsa','bachata','merengue','dembow','latinpop',
 # Band / pop / rock
 'pop','rock','punk','metal','indierock','indiepop','alternative','shoegaze','grunge','emo','ska','reggae','reggaeroots','ska','blues','soul','disco','funkrock','country','folk','americana','flamenco',
 # Acoustic / orchestral / cinematic
 'classical','cinematic','jazz','fusion','world','lofi','chillout','soundtrack','neoclassical','minimalism'
}

def _preset(bpm, root, scale, family):
    return {'bpm':bpm,'root':root,'scale':scale,'family':family}

GENRES={
 # Core styles
 'pop':_preset(112,60,[0,2,4,5,7,9,11],'pop'), 'rock':_preset(118,52,[0,2,4,5,7,9,10],'rock'),
 'indiepop':_preset(108,57,[0,2,3,5,7,9,10],'indiepop'), 'indierock':_preset(116,52,[0,2,3,5,7,9,10],'indierock'),
 'alternative':_preset(110,55,[0,2,3,5,7,8,10],'alternative'), 'punk':_preset(168,52,[0,2,3,5,7,9,10],'punk'),
 'hardrock':_preset(132,49,[0,2,3,5,7,8,10],'rock'), 'metal':_preset(150,46,[0,1,3,5,7,8,10],'metal'),
 'heavymetal':_preset(145,46,[0,1,3,5,7,8,10],'metal'), 'metalcore':_preset(150,46,[0,1,3,5,7,8,10],'metal'),
 'deathmetal':_preset(175,43,[0,1,3,5,7,8,10],'metal'), 'nu-metal':_preset(105,46,[0,1,3,5,7,8,10],'metal'),
 'grunge':_preset(100,52,[0,2,3,5,7,8,10],'grunge'), 'emo':_preset(150,52,[0,2,3,5,7,9,10],'emo'),
 'shoegaze':_preset(105,55,[0,2,3,5,7,8,10],'shoegaze'), 'garage-rock':_preset(145,52,[0,2,3,5,7,10],'rock'),
 'folk':_preset(92,55,[0,2,4,5,7,9,11],'folk'), 'country':_preset(104,55,[0,2,4,5,7,9,10],'country'),
 'americana':_preset(96,52,[0,2,4,5,7,9,10],'country'), 'singer-songwriter':_preset(88,57,[0,2,4,5,7,9,11],'folk'),
 # Urban
 'trap':_preset(140,49,[0,3,5,7,10],'trap'), 'drill':_preset(142,49,[0,1,3,5,7,10],'drill'),
 'hiphop':_preset(92,49,[0,3,5,7,10],'hiphop'), 'boom-bap':_preset(90,49,[0,2,3,5,7,10],'hiphop'),
 'cloudrap':_preset(130,49,[0,3,5,7,10],'trap'), 'rage':_preset(150,49,[0,1,3,5,7,10],'trap'),
 'rnb':_preset(86,52,[0,2,3,5,7,9,10],'rnb'), 'soul':_preset(92,52,[0,2,3,5,7,9,10],'soul'),
 'neo-soul':_preset(78,52,[0,1,3,5,7,8,10],'rnb'), 'funk':_preset(108,52,[0,2,4,5,7,9,10],'funk'),
 'funkrock':_preset(112,52,[0,2,3,5,7,9,10],'funk'),
 # Latin
 'reggaeton':_preset(96,55,[0,2,4,7,9],'reggaeton'), 'dembow':_preset(100,55,[0,2,4,7,9],'dembow'),
 'dancehall':_preset(102,55,[0,2,3,5,7,9,10],'dancehall'), 'reggae':_preset(78,55,[0,2,4,5,7,9,10],'reggae'),
 'reggaeroots':_preset(74,52,[0,2,4,5,7,9,10],'reggae'), 'bachata':_preset(125,55,[0,2,4,7,9],'bachata'),
 'salsa':_preset(96,55,[0,2,4,5,7,9,10],'salsa'), 'cumbia':_preset(94,55,[0,2,4,5,7,9,10],'cumbia'),
 'merengue':_preset(125,55,[0,2,4,5,7,9,10],'merengue'), 'flamenco':_preset(110,52,[0,1,3,5,7,8,10],'flamenco'),
 'latinpop':_preset(105,57,[0,2,4,5,7,9,11],'latinpop'), 'samba':_preset(100,55,[0,2,4,5,7,9,11],'samba'),
 'bossa':_preset(130,55,[0,2,3,5,7,9,10],'bossa'), 'afrobeats':_preset(105,55,[0,2,4,5,7,9,10],'afrobeats'),
 'afrohouse':_preset(122,55,[0,2,4,5,7,9,10],'afrohouse'),
 # Electronic
 'house':_preset(124,55,[0,2,4,7,9],'house'), 'deep-house':_preset(122,52,[0,2,3,5,7,9,10],'house'),
 'tech-house':_preset(126,55,[0,2,4,7,9],'house'), 'techno':_preset(132,49,[0,3,5,7,10],'techno'),
 'minimal-techno':_preset(128,49,[0,1,3,5,7,8,10],'techno'), 'acid-techno':_preset(138,49,[0,1,3,5,7,8,10],'techno'),
 'trance':_preset(138,57,[0,2,4,5,7,9,11],'trance'), 'uplifting-trance':_preset(140,57,[0,2,4,5,7,9,11],'trance'),
 'psytrance':_preset(145,49,[0,1,3,5,7,8,10],'psytrance'), 'goa-trance':_preset(142,49,[0,1,3,5,7,8,10],'psytrance'),
 'edm':_preset(128,55,[0,2,4,5,7,9,11],'edm'), 'electro':_preset(124,49,[0,2,3,5,7,8,10],'electro'),
 'dubstep':_preset(140,49,[0,1,3,5,7,8,10],'dubstep'), 'future-bass':_preset(150,55,[0,2,3,5,7,9,10],'edm'),
 'drumandbass':_preset(174,49,[0,2,3,5,7,10],'drumandbass'), 'liquid-dnb':_preset(174,55,[0,2,4,5,7,9,11],'drumandbass'),
 'breakbeat':_preset(132,52,[0,2,3,5,7,9,10],'breakbeat'), 'ukgarage':_preset(132,55,[0,2,4,5,7,9,10],'ukgarage'),
 'garage':_preset(132,55,[0,2,4,5,7,9,10],'ukgarage'), 'grime':_preset(140,49,[0,1,3,5,7,10],'grime'),
 'hardcore':_preset(170,46,[0,1,3,5,7,8,10],'hardcore'), 'hardstyle':_preset(150,46,[0,1,3,5,7,8,10],'hardstyle'),
 'gabber':_preset(190,46,[0,1,3,5,7,8,10],'gabber'), 'frenchcore':_preset(195,46,[0,1,3,5,7,8,10],'frenchcore'),
 'speedcore':_preset(220,46,[0,1,3,5,7,8,10],'speedcore'), 'breakcore':_preset(190,49,[0,1,3,5,7,8,10],'breakcore'),
 'jungle':_preset(170,49,[0,2,3,5,7,10],'drumandbass'), 'downtempo':_preset(75,52,[0,2,3,5,7,9,10],'downtempo'),
 'ambient':_preset(68,52,[0,2,4,7,9,11],'ambient'), 'chillout':_preset(90,55,[0,2,3,5,7,9,10],'chillout'),
 'synthwave':_preset(105,49,[0,2,3,5,7,8,10],'electro'), 'retrowave':_preset(100,49,[0,2,3,5,7,8,10],'electro'),
 # Jazz / blues / fusion
 'jazz':_preset(108,52,[0,2,3,5,7,9,10],'jazz'), 'smooth-jazz':_preset(88,52,[0,2,3,5,7,9,11],'jazz'),
 'bebop':_preset(180,52,[0,2,3,5,7,9,10],'jazz'), 'blues':_preset(90,52,[0,3,5,6,7,10],'blues'),
 'jazz-fusion':_preset(112,52,[0,2,3,5,7,9,10],'fusion'), 'funk-jazz':_preset(108,52,[0,2,4,5,7,9,10],'fusion'),
 'world':_preset(100,55,[0,2,3,5,7,8,10],'world'), 'balkan':_preset(125,52,[0,1,3,5,7,8,10],'world'),
 # Classical / cinematic
 'clasica':_preset(76,60,[0,2,4,5,7,9,11],'classical'), 'classical':_preset(76,60,[0,2,4,5,7,9,11],'classical'),
 'neoclassical':_preset(82,57,[0,2,3,5,7,9,10],'neoclassical'), 'baroque':_preset(100,60,[0,2,4,5,7,9,11],'classical'),
 'romantic':_preset(72,57,[0,2,4,5,7,9,11],'classical'), 'minimalism':_preset(120,60,[0,2,4,7,9],'minimalism'),
 'cinematic':_preset(88,49,[0,2,4,7,9],'cinematic'), 'soundtrack':_preset(84,49,[0,2,4,5,7,9,10],'cinematic'),
 # Lo-fi / chill
 'lofi':_preset(82,48,[0,2,3,7,9],'lofi'), 'lofi-hiphop':_preset(78,48,[0,2,3,7,9],'lofi'),
 'chillhop':_preset(82,50,[0,2,3,5,7,9,10],'lofi'), 'study-beats':_preset(76,50,[0,2,3,7,9],'lofi'),
}
INSTRUMENTS=['piano','synth','pluck','pad','bass','808','guitar','bell','strings','brass','organ','marimba','lead']
EFFECTS=['clean','telephone','radio','echo','robot','deep','bright','wide']


def _now(): return datetime.now(timezone.utc).isoformat()
def _path(pid): return PROJECTS/f'{pid}.json'
def _load(pid):
 p=_path(pid)
 if not p.exists(): raise ValueError('Proyecto de audio no encontrado.')
 return json.loads(p.read_text(encoding='utf-8'))
def _save(p):
 _path(p['id']).write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8')


def create_project(name='', genre='pop', bpm=None, duration=30, root=60, key='C'):
 genre=genre if genre in GENRES else 'pop'; g=GENRES[genre]; bpm=int(bpm or g['bpm']); bpm=max(40,min(220,bpm)); duration=max(5,min(int(duration or 30),600))
 defaults={
  'trap':['kick','snare','hat','808','pad','lead'],
  'reggaeton':['kick','snare','hat','bass','guitar','pluck'],
  'house':['kick','hat','bass','synth','pad'],
  'techno':['kick','hat','bass','synth','pad'],
  'lofi':['kick','snare','hat','bass','piano','guitar'],
  'pop':['kick','snare','hat','bass','piano','pad','lead'],
  'drill':['kick','snare','hat','808','pad','lead'],
  'cinematic':['piano','strings','pad','brass'],
  'clasica':['piano','strings','organ'],
  'classical':['piano','strings','organ'],
 }
 pid=uuid.uuid4().hex
 p={'id':pid,'name':name or 'Nueva base','genre':genre,'bpm':bpm,'duration':duration,'root':float(root or g['root']),'key':key,'swing':0,'master':.9,'tracks':[], 'instruments':defaults.get(genre,defaults['pop']), 'energy':.65,'voice_effect':'clean','created_at':_now(),'updated_at':_now()}
 _save(p); return p


def list_projects():
 out=[]
 for f in sorted(PROJECTS.glob('*.json'), key=lambda x:x.stat().st_mtime, reverse=True):
  try: out.append(json.loads(f.read_text(encoding='utf-8')))
  except Exception: pass
 return out


def _osc(kind, freq, t):
 if freq<=0:return 0.0
 ph=(freq*t)%1.0
 if kind=='saw': return 2*ph-1
 if kind=='square': return 1.0 if ph<.5 else -1.0
 if kind=='tri': return 4*abs(ph-.5)-1
 return math.sin(2*math.pi*freq*t)


def _env(t,d,a=.01,r=.08):
 if t<0:return 0.0
 if t<a:return t/max(a,1e-6)
 if t>d-r:return max(0,(d-t)/max(r,1e-6))
 return 1.0


def _profile(genre, ref):
 txt=' '.join(str(ref.get(k) or '') for k in ('genres','rhythm','groove','arrangement','production_notes')).lower()
 g=(genre or 'pop').lower()
 if g in GENRES: return GENRES[g].get('family',g)
 if any(x in txt for x in ('frenchcore','hardcore','gabber','speedcore')): return 'hardcore'
 if any(x in txt for x in ('dembow','reggaeton','reguetón')): return 'reggaeton'
 for family in sorted(GENRE_FAMILIES, key=len, reverse=True):
  if family in txt or family.replace('-',' ') in txt: return family
 return 'pop'


def render_base(pid, genre=None,bpm=None,duration=None,root=None,instruments=None,energy=.65,seed=None):
 p=_load(pid); genre=genre or p['genre']; g=GENRES.get(genre,GENRES['pop']); bpm=int(bpm or p['bpm']); dur=int(duration or p['duration']); root=float(root or p['root']); instruments=instruments or p.get('instruments') or ['kick','snare','hat','bass','pad','lead']; instruments=list(dict.fromkeys(instruments)); energy=max(.1,min(float(energy),1.0)); seed = int(seed) if seed is not None else int(uuid.uuid4().hex[:8],16); rng=random.Random(seed)
 sr=44100; n=int(dur*sr); beat=60/bpm; bar=beat*4; profile=_profile(genre,p.get('reference_profile') or {})
 buf=[0.0]*n; scale=g['scale']
 # Every render gets a new musical identity: chord choices, motifs, syncopation and note register
 # all derive from a fresh seed. A reference only changes high-level musical constraints.
 chord_templates=[[0,2,4],[5,3,0],[4,6,1],[0,3,5],[2,4,6],[6,4,1]]
 chord_seed=rng.randrange(len(chord_templates)); chords=chord_templates[chord_seed:]+chord_templates[:chord_seed]
 motif=[rng.choice([0,1,2,3,4,5,6]) for _ in range(8)]
 motif2=[rng.choice([-1,0,1,2,3]) for _ in range(8)]
 sync=rng.choice([0,1,2,3])
 swing=(rng.uniform(.0,.08) if profile in ('trap','drill','lofi','reggaeton') else rng.uniform(0,.035))
 
 # Genre-specific arrangement decisions.
 classical = profile=='classical'
 cinematic = profile=='cinematic'
 if classical:
  default_insts=['piano','strings','organ']
 elif profile in ('rock','indierock','alternative','grunge','punk','emo','metal','country','folk'):
  default_insts=['kick','snare','hat','bass','guitar','piano']
 elif profile in ('hardcore','hardstyle','gabber','frenchcore','speedcore','breakcore'):
  default_insts=['kick','snare','hat','bass','synth','lead']
 elif profile in ('drumandbass','breakbeat','ukgarage','garage','jungle','grime'):
  default_insts=['kick','snare','hat','bass','synth','pad']
 elif profile in ('jazz','blues','fusion','soul','rnb'):
  default_insts=['kick','snare','hat','bass','piano','guitar','brass']
 elif profile in ('reggae','dancehall','bachata','salsa','cumbia','merengue','samba','bossa','flamenco','latinpop','afrobeats','afrohouse'):
  default_insts=['kick','snare','hat','bass','guitar','pluck']

 elif cinematic:
  default_insts=['piano','strings','pad','brass']
 elif profile=='reggaeton': default_insts=['kick','snare','hat','bass','guitar','pluck']
 elif profile=='trap': default_insts=['kick','snare','hat','808','pad','lead']
 elif profile=='drill': default_insts=['kick','snare','hat','808','pad','lead']
 elif profile=='house': default_insts=['kick','hat','bass','synth','pad']
 elif profile=='techno': default_insts=['kick','hat','bass','synth','pad']
 else: default_insts=['kick','snare','hat','bass','piano','pad','lead']
 if not instruments: instruments=default_insts
 
 def note_freq(degree, octave=0):
  sem=scale[degree%len(scale)] + 12*octave
  return root*(2**(sem/12))
 
 for i in range(n):
  t=i/sr; bi=int(t/beat); phase=t%beat; bar_i=int(t/bar); step=bi%4; six=int((phase/(beat/4))%4); x=0.0
  section=(bar_i//4)%4
  chord=chords[(bar_i+section)%len(chords)]
  deg=chord[(step + sync + bar_i)%len(chord)]
  chord_root=note_freq(deg,-1)
  swing_shift=(beat/4)*swing if six%2 else 0
  local_phase=max(0,phase-swing_shift)
  
  if not classical and not cinematic:
   # Drums: materially different grooves by style.
   kick_steps={
    'reggaeton':((0,2,3) if bar_i%2 else (0,2)), 'dembow':(0,2,3),
    'trap':((0,2,3) if bar_i%2 else (0,2)), 'drill':((0,3) if (bar_i+sync)%2 else (0,2,3)),
    'house':(0,1,2,3), 'techno':(0,1,2,3), 'hardcore':(0,1,2,3), 'hardstyle':(0,1,2,3),
    'gabber':(0,1,2,3), 'frenchcore':(0,1,2,3), 'speedcore':(0,1,2,3),
    'drumandbass':(0,2), 'breakbeat':(0,2), 'ukgarage':(0,2), 'grime':(0,2),
    'rock':(0,2), 'indierock':(0,2), 'punk':(0,1,2,3), 'metal':(0,2),
    'jazz':(0,2), 'blues':(0,2), 'funk':(0,2), 'soul':(0,2), 'rnb':(0,2),
    'reggae':(0,2), 'dancehall':(0,2), 'bachata':(0,2), 'salsa':(0,2), 'cumbia':(0,2),
    'merengue':(0,2), 'samba':(0,2), 'bossa':(0,2), 'afrobeats':(0,2), 'afrohouse':(0,2),
    'lofi':(0,2), 'downtempo':(0,2), 'ambient':(0,), 'pop':(0,2),
   }.get(profile,(0,2))
   if 'kick' in instruments and step in kick_steps and local_phase<.22:
    if profile in ('house','techno'): f=90-45*(local_phase/.22); amp=.28
    else: f=110-75*(local_phase/.22); amp=.36 if profile in ('trap','drill') else .30
    x += amp*math.exp(-18*local_phase)*math.sin(2*math.pi*f*local_phase)
   snare_steps={'reggaeton':(1,3),'dembow':(1,3),'trap':(1,3),'drill':(3,),
                 'house':(1,3),'techno':(1,3),'hardcore':(1,3),'hardstyle':(1,3),'gabber':(1,3),'frenchcore':(1,3),
                 'drumandbass':(1,3),'breakbeat':(1,3),'ukgarage':(1,3),'rock':(1,3),'punk':(1,3),'metal':(1,3),
                 'lofi':(1,3),'pop':(1,3)}.get(profile,(1,3))
   if 'snare' in instruments and step in snare_steps and local_phase<.16:
    amp=.10 if profile not in ('trap','drill') else .14
    x += amp*math.exp(-24*local_phase)*(rng.random()*2-1)
   if 'hat' in instruments:
    if profile in ('trap','drill'): hat_on=(bi%2==0 or bi%4 in (1,3) or (bar_i+sync)%3==0)
    elif profile in ('house','techno'): hat_on=(six in (1,3) or (profile=='techno' and bi%2==1))
    elif profile in ('reggaeton','dembow','dancehall','bachata','salsa','cumbia','merengue','samba','bossa','afrobeats','afrohouse','reggae'):
     hat_on=(bi%2==0 or six==3)
    elif profile in ('hardcore','hardstyle','gabber','frenchcore','speedcore'):
     hat_on=(bi%2==0 or six in (1,3))
    elif profile in ('drumandbass','breakbeat','ukgarage','garage','grime'):
     hat_on=(bi%2==0 or six in (1,3) or (bar_i+bi)%3==0)
    else: hat_on=(bi%2==0 or energy>.72)
    if hat_on and local_phase<.045: x += (.028 if profile in ('house','techno') else .035)*math.exp(-70*local_phase)*(rng.random()*2-1)
  
  # Bass / 808. Trap and drill get stronger sub movement; dance styles get shorter notes.
  if ('bass' in instruments or '808' in instruments) and not classical:
   f=chord_root
   if '808' in instruments: f*=.5
   length=beat*(.65 if profile in ('house','techno') else .9)
   wave_kind='sine' if profile in ('reggaeton','house','deep-house','afrohouse','bossa') else ('square' if profile in ('hardcore','hardstyle','gabber','frenchcore','speedcore','electro') else 'saw')
   amp=.105 if '808' in instruments else (.078 if profile in ('hardcore','hardstyle','gabber','frenchcore','speedcore','techno') else .065)
   if step==3 and profile in ('trap','drill'): f*=rng.choice([.75,1,1.25])
   x += amp*_osc(wave_kind,f,t)*_env(local_phase,length,.02,.12)
  
  # Harmony / instruments.
  if 'pad' in instruments or 'strings' in instruments:
   if classical:
    # Long sustained triad with gentle movement.
    for off in (0,4,7): x += .025*_osc('tri',note_freq(chord[(off//4)%len(chord)],0),t)
   else:
    for off in (0,4,7): x += .018*_osc('tri',chord_root*2**(off/12),t)
  if 'piano' in instruments or 'guitar' in instruments:
   # Random arpeggio/motif means two renders are not identical.
   hit=(step in (0,2)) if profile!='classical' else ((bi+bar_i)%2==0 or six==2)
   if hit and local_phase<(.55 if classical else .18):
    md=motif[(bi+bar_i)%len(motif)]
    freq=note_freq(md%len(scale), 1 if classical else 0)
    amp=.055 if classical else .045
    x += amp*math.sin(2*math.pi*freq*t)*math.exp((-3 if classical else -18)*local_phase)
  if 'pluck' in instruments or 'bell' in instruments or 'marimba' in instruments:
   if local_phase<.28 and ((step in (0,1,2,3)) if energy>.55 else step in (0,2)):
    md=(motif[(bi+sync)%8]+motif2[(bar_i+bi)%8])%len(scale)
    freq=note_freq(md,1)
    x += .032*_osc('sine',freq,t)*math.exp(-11*local_phase)
  if 'synth' in instruments or 'lead' in instruments:
   if not classical and ((step in (0,2) and local_phase<beat*.9) or (profile=='techno' and six in (0,2))):
    md=(motif[(bi+bar_i)%8]+(bar_i%3))%len(scale)
    lf=note_freq(md,1 if profile not in ('trap','drill') else 0)
    x += .026*_osc('saw',lf,t)*math.exp(-2.3*local_phase)
  if 'organ' in instruments:
   if classical:
    x += .012*(math.sin(2*math.pi*chord_root*t)+.5*math.sin(4*math.pi*chord_root*t))
   else:
    x += .014*(math.sin(2*math.pi*chord_root*t)+.5*math.sin(4*math.pi*chord_root*t))
  if 'brass' in instruments and local_phase<.15 and step==3:
   x += .026*(math.sin(2*math.pi*chord_root*t)+.25*math.sin(4*math.pi*chord_root*t))*math.exp(-16*local_phase)
  # Cinematic strings/brass swell and occasional motif notes.
  if cinematic:
   swell=.45+.55*(math.sin(2*math.pi*(bar_i%8)/8)**2)
   if 'strings' in instruments: x += .028*swell*_osc('tri',note_freq(motif[bar_i%8]%len(scale),0),t)
   if 'brass' in instruments and step==0: x += .018*swell*math.sin(2*math.pi*note_freq(deg,0)*t)
  if classical and 'strings' in instruments:
   md=(motif[bi%8]+motif2[(bar_i+2)%8])%len(scale)
   x += .018*_osc('tri',note_freq(md,1),t)*_env(local_phase,beat*1.7,.05,.25)
  
  # Family-specific timbral accent so adjacent genres do not collapse into the same sound.
  if profile in ('hardcore','hardstyle','gabber','frenchcore','speedcore') and 'synth' in instruments:
   if six in (0,2) and local_phase < beat*.45:
    x += .018*_osc('square', chord_root*4, t)*math.exp(-2.0*local_phase)
  elif profile in ('rock','indierock','punk','metal','grunge','emo') and 'guitar' in instruments:
   if step in (0,2) and local_phase < .25:
    x += .022*_osc('saw', chord_root*2, t)*math.exp(-10*local_phase)
  elif profile in ('jazz','blues','fusion','soul','rnb') and ('piano' in instruments or 'brass' in instruments):
   if six==2 and local_phase < .35:
    x += .018*math.sin(2*math.pi*note_freq((motif2[bar_i%8]+2)%len(scale),1)*t)*math.exp(-5*local_phase)
  elif profile in ('reggae','dancehall','bachata','salsa','cumbia','merengue','samba','bossa','afrobeats','afrohouse'):
   if six==1 and local_phase < .25:
    x += .014*math.sin(2*math.pi*note_freq((motif[bi%8]+3)%len(scale),0)*t)*math.exp(-8*local_phase)
  # Small humanization and section dynamics.
  if section==1: x*=.88
  elif section==2: x*=1.05
  elif section==3: x*=1.12
  x=max(-.9,min(.9,x*energy))
  fade=min(1,t/.15,(dur-t)/.4 if t>dur-.4 else 1)
  buf[i]=x*max(0,fade)*float(p.get('master',.9))
 
 path=OUTPUTS/f'{pid}_{seed}.wav'
 pcm=bytearray()
 for x in buf:
  s=int(max(-1,min(1,x))*32767); pcm += s.to_bytes(2,'little',signed=True)*2
 with wave.open(str(path),'wb') as w:
  w.setnchannels(2);w.setsampwidth(2);w.setframerate(sr);w.writeframes(pcm)
 p['genre']=genre;p['bpm']=bpm;p['duration']=dur;p['root']=root;p['seed']=seed;p['instruments']=instruments;p['energy']=energy;p['rendered_url']=f'/api/studio/audio/projects/{pid}/preview?file={path.name}';p['rendered_file']=path.name;p['rendered_at']=_now();p['updated_at']=_now();_save(p)
 return {'path':str(path),'url':p['rendered_url'],'file':path.name,'bpm':bpm,'duration':dur,'genre':genre,'instruments':instruments,'sample_rate':sr,'channels':2,'format':'wav','seed':seed,'profile':profile,'rights_note':'Base generada proceduralmente por Zar sin canciones ni samples de terceros.'}


def save_settings(pid, patch):
 p=_load(pid)
 for k in ('genre','bpm','duration','root','key','swing','master','voice_effect','energy'):
  if k in patch: p[k]=patch[k]
 p['genre']=p['genre'] if p['genre'] in GENRES else 'pop';p['bpm']=max(40,min(220,int(p['bpm'])));p['duration']=max(5,min(600,int(p['duration'])))
 p['updated_at']=_now();_save(p);return p


def apply_voice_effect(pid, file_storage, effect='clean'):
 p=_load(pid); effect=effect if effect in EFFECTS else 'clean'; ext=Path(file_storage.filename or 'voice.webm').suffix or '.webm'; src=TRACKS/f'{uuid.uuid4().hex}{ext}'; file_storage.save(src)
 out=OUTPUTS/f'{pid}_voice_{effect}_{uuid.uuid4().hex[:8]}.wav'
 filters={'clean':'anull','telephone':'highpass=f=350,lowpass=f=3200,acompressor','radio':'highpass=f=700,lowpass=f=2800,acrusher=bits=8:mix=0.18','echo':'aecho=0.8:0.88:120:0.28','robot':'aecho=0.8:0.7:80:0.22,chorus=0.5:0.9:45:0.25:0.45:2','deep':'asetrate=44100*0.86,aresample=44100,atempo=1.1628','bright':'highpass=f=120,treble=g=5','wide':'stereotools=mlev=0.8:mlev2=0.8'}
 cmd=['ffmpeg','-y','-i',str(src),'-af',filters[effect],str(out)]
 try: subprocess.run(cmd,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
 except Exception as exc: raise ValueError(f'No pude aplicar el efecto de voz: {exc}')
 p['voice_effect']=effect;p['voice_preview_url']=f'/api/studio/audio/projects/{pid}/preview?file={out.name}';p['updated_at']=_now();_save(p);return {'effect':effect,'url':p['voice_preview_url'],'path':str(out)}


def _parse_reference_request(text):
 t=(text or '').strip()
 import re
 patterns=[
  r'(?:canci[oó]n|tema)\s+["“]?(.+?)["”]?\s+(?:de|del)\s+(.+?)(?:\s+(?:y|pero|con|para)\b|$)',
  r'(?:canciones|temas|bases|estilo|ritmo|sonido)\s+(?:de|del)\s+(.+?)(?:\s+(?:y|pero|con|para)\b|$)',
  r'(?:como|parecida?\s+a|parecido\s+a|similar\s+a)\s+(.+?)(?:\s+(?:y|pero|con|para)\b|$)',
 ]
 for idx,p in enumerate(patterns):
  m=re.search(p,t,re.I)
  if m:
   if idx==0:
    title=re.sub(r'["“”\']','',m.group(1)).strip(' .,:;!?¿¡'); artist=re.sub(r'["“”\']','',m.group(2)).strip(' .,:;!?¿¡')
    return artist[:120], title[:160]
   artist=re.sub(r'["“”\']','',m.group(1)).strip(' .,:;!?¿¡')
   return artist[:120], ''
 m=re.search(r'(?:canci[oó]n|tema)\s+["“]?(.+?)["”]?(?:\s+(?:y|pero|con|para|que)\b|$)', t, re.I)
 if m:
  title=re.sub(r'["“”\']','',m.group(1)).strip(' .,:;!?¿¡')
  return '', title[:160]
 return '', ''


def audio_command(pid, instruction):
 p=_load(pid); original=(instruction or '').strip(); t=original.lower(); changes=[]; import re
 reference=None
 ref_artist, ref_song=_parse_reference_request(original)
 is_reference=bool(ref_artist) or ('http://' in t or 'https://' in t) or any(x in t for x in ('canciones de ', 'temas de ', 'bases de ', 'estilo de ', 'parecida a ', 'parecido a ', 'similar a ', 'inspirada en ', 'inspirado en ', 'canción ', 'cancion ', 'tema '))
 if is_reference:
  try:
   from .music_reference import analyze_reference
   reference=analyze_reference(original, ref_artist, ref_song)
   if reference.get('ok'):
    bpm_target=int(reference.get('bpm_target') or 0)
    if 40 <= bpm_target <= 220:
     p['bpm']=bpm_target; changes.append(f"BPM de referencia {bpm_target}")
    genres_ref=' '.join(str(x).lower() for x in (reference.get('genres') or []))
    if any(x in genres_ref for x in ('classical','clásica','classica','orchestral','orquestal')): p['genre']='clasica'
    elif 'reggaeton' in genres_ref or 'reguetón' in genres_ref: p['genre']='reggaeton'
    elif 'trap' in genres_ref: p['genre']='trap'
    elif 'drill' in genres_ref: p['genre']='drill'
    elif 'house' in genres_ref: p['genre']='house'
    elif 'techno' in genres_ref: p['genre']='techno'
    elif 'lofi' in genres_ref or 'lo-fi' in genres_ref: p['genre']='lofi'
    elif 'cinematic' in genres_ref or 'orchestral' in genres_ref: p['genre']='cinematic'
    elif 'pop' in genres_ref: p['genre']='pop'
    inst=set(p.get('instruments') or ['kick','snare','hat','bass','pad','lead'])
    valid={'kick','snare','hat','bass','808','piano','guitar','pluck','pad','strings','bell','lead','organ','brass','marimba','synth'}
    # Reference instruments are suggestions, not a copied arrangement.
    for inst_name in reference.get('instruments') or []:
     if inst_name in valid: inst.add(inst_name)
    if p['genre']=='clasica': inst.update(['piano','strings']); inst.difference_update(['kick','snare','hat','808'])
    elif p['genre']=='reggaeton': inst.update(['kick','snare','hat','bass','guitar','pluck'])
    elif p['genre'] in ('trap','drill'): inst.update(['kick','snare','hat','808','pad','lead'])
    p['instruments']=sorted(inst)
    if reference.get('energy') is not None:
     try:p['energy']=max(.1,min(1,float(reference.get('energy'))))
     except Exception:pass
    p['reference_profile']={k:reference.get(k) for k in ('artist','song','songs','bpm_min','bpm_max','bpm_target','genres','rhythm','groove','arrangement','instruments','energy','production_notes','source_urls')}
    p['reference_note']=f"Inspiración general basada en rasgos públicos de {reference.get('artist')}; base nueva y original."
    changes.append(f"referencia analizada: {reference.get('artist')}{' · '+reference.get('song') if reference.get('song') else ''}")
   else:
    return {'ok':False,'error':reference.get('error','No se pudo analizar la referencia.'),'project':p}
  except Exception as exc:
   return {'ok':False,'error':f'No pude analizar la referencia: {exc}','project':p}
 genres={'liquid drum and bass':'liquid-dnb','singer songwriter':'singer-songwriter','singer-songwriter':'singer-songwriter','uplifting trance':'uplifting-trance','hardcore techno':'hardcore','minimal techno':'minimal-techno','música clásica':'clasica','musica clasica':'clasica','drum and bass':'drumandbass','roots reggae':'reggaeroots','neoclassical':'neoclassical','banda sonora':'soundtrack','lofi hip hop':'lofi-hiphop','lofi hip-hop':'lofi-hiphop','alternative':'alternative','heavy metal':'heavymetal','heavy-metal':'heavymetal','death metal':'deathmetal','garage rock':'garage-rock','acid techno':'acid-techno','future bass':'future-bass','future-bass':'future-bass','french core':'frenchcore','smooth jazz':'smooth-jazz','jazz fusion':'jazz-fusion','world music':'world','minimalismo':'minimalism','study beats':'study-beats','indie rock':'indierock','deathmetal':'deathmetal','bossa nova':'bossa','afro house':'afrohouse','deep house':'deep-house','deep-house':'deep-house','tech house':'tech-house','tech-house':'tech-house','psy trance':'psytrance','goa trance':'goa-trance','liquid dnb':'liquid-dnb','frenchcore':'frenchcore','neoclásica':'neoclassical','neoclasica':'neoclassical','minimalism':'minimalism','cinemática':'cinematic','cinematica':'cinematic','soundtrack':'soundtrack','reggaeton':'reggaeton','reggaetón':'reggaeton','cloud rap':'cloudrap','funk rock':'funkrock','indie pop':'indiepop','indierock':'indierock','hard rock':'hardrock','metalcore':'metalcore','americana':'americana','dancehall':'dancehall','latin pop':'latinpop','afrobeats':'afrobeats','afrohouse':'afrohouse','psytrance':'psytrance','drum&bass':'drumandbass','breakbeat':'breakbeat','uk garage':'ukgarage','hardstyle':'hardstyle','speedcore':'speedcore','breakcore':'breakcore','synthwave':'synthwave','retrowave':'retrowave','downtempo':'downtempo','jazz-funk':'funk-jazz','jazz funk':'funk-jazz','classical':'classical','romántica':'romantic','cinematic':'cinematic','reguetón':'reggaeton','boom bap':'boom-bap','boom-bap':'boom-bap','cloudrap':'cloudrap','neo soul':'neo-soul','neo-soul':'neo-soul','funkrock':'funkrock','indiepop':'indiepop','hardrock':'hardrock','nu metal':'nu-metal','nu-metal':'nu-metal','shoegaze':'shoegaze','merengue':'merengue','flamenco':'flamenco','latinpop':'latinpop','ukgarage':'ukgarage','hardcore':'hardcore','chillout':'chillout','romantic':'romantic','chillhop':'chillhop','hip hop':'hiphop','hip-hop':'hiphop','country':'country','bachata':'bachata','electro':'electro','dubstep':'dubstep','ambient':'ambient','clásica':'clasica','clasica':'clasica','baroque':'baroque','barroco':'baroque','dembow':'dembow','hiphop':'hiphop','grunge':'grunge','reggae':'reggae','cumbia':'cumbia','techno':'techno','trance':'trance','garage':'garage','gabber':'gabber','jungle':'jungle','balkan':'balkan','drill':'drill','metal':'metal','salsa':'salsa','samba':'samba','bossa':'bossa','house':'house','grime':'grime','bebop':'bebop','blues':'blues','world':'world','lo-fi':'lofi','trap':'trap','rage':'rage','soul':'soul','funk':'funk','rock':'rock','punk':'punk','folk':'folk','jazz':'jazz','lofi':'lofi','r&b':'rnb','rnb':'rnb','pop':'pop','emo':'emo','edm':'edm','dnb':'drumandbass'}
 # Lenguaje natural: cambiar de género aunque el usuario no nombre uno concreto.
 # Se elige uno diferente al actual para que "otro género" produzca una transformación real.
 if any(x in t for x in ('otro género','otro genero','cambia de género','cambia de genero','cambiar de género','cambiar de genero','diferente género','diferente genero')):
  pool=[g for g in GENRES.keys() if g not in ('classical',p.get('genre'))]
  if pool:
   target=random.SystemRandom().choice(pool)
   p['genre']=target; changes.append(f'cambio de género a {target}')
 else:
  for token,val in genres.items():
   if token in t: p['genre']=val; changes.append(f'género {val}'); break
 # "haz/genera/crea una base" es una orden válida incluso si no hay otro ajuste:
 # el render usa una semilla nueva, por lo que genera una composición diferente.
 generation_words=('genera una base','genera base','haz una base','hazme una base','crea una base','creame una base','crea un beat','haz un beat','genera un beat','haz música','haz musica','genera música','genera musica','otra base','nueva base','nueva variación','nueva variacion')
 if any(x in t for x in generation_words):
  changes.append('nueva composición original')
 m=re.search(r'(?:bpm|beats per minute|pulsos)[^0-9]*(\d{2,3})',t) or re.search(r'(\d{2,3})\s*bpm',t)
 if m: p['bpm']=max(40,min(220,int(m.group(1)))); changes.append(f"BPM a {p['bpm']}")
 m=re.search(r'(?:duraci[oó]n|que dure|durante)\s*(\d+)\s*(segundos?|s|minutos?|min|m)',t)
 if m:
  val=int(m.group(1))*(60 if m.group(2).startswith(('m','min')) else 1);p['duration']=max(5,min(600,val));changes.append(f'duración {p["duration"]} s')
 if 'más rápida' in t or 'mas rapida' in t or 'más rapido' in t: p['bpm']=min(220,p['bpm']+12);changes.append(f'BPM a {p["bpm"]}')
 if 'más lenta' in t or 'mas lenta' in t: p['bpm']=max(40,p['bpm']-12);changes.append(f'BPM a {p["bpm"]}')
 inst_alias={'808':'808','bajo':'bass','bass':'bass','piano':'piano','guitarra':'guitar','guitar':'guitar','pad':'pad','cuerdas':'strings','strings':'strings','campanas':'bell','bell':'bell','lead':'lead','sintetizador':'synth','synth':'synth','pluck':'pluck','órgano':'organ','organo':'organ','metales':'brass','brass':'brass','bombo':'kick','kick':'kick','caja':'snare','snare':'snare','charles':'hat','hat':'hat','marimba':'marimba'}
 cur=set(p.get('instruments') or ['kick','snare','hat','bass','pad','lead'])
 for phrase,inst in inst_alias.items():
  if phrase in t:
   if any(w in t for w in ('quita','elimina','sin ','fuera')) and ('quita '+phrase in t or 'sin '+phrase in t or 'elimina '+phrase in t): cur.discard(inst);changes.append(f'sin {inst}')
   else: cur.add(inst);changes.append(f'añadido {inst}')
 p['instruments']=sorted(cur)
 if any(w in t for w in ('más fuerte','mas fuerte','más intensa','mas intensa','energía','energia')): p['energy']=min(1,float(p.get('energy',.65))+.15);changes.append('más energía')
 if any(w in t for w in ('más suave','mas suave','menos intensa','menos intensa')): p['energy']=max(.1,float(p.get('energy',.65))-.15);changes.append('menos energía')
 if any(w in t for w in ('autotune','auto tune','afinación','afinacion','pitch')): p['voice_effect']='bright';changes.append('Auto-Pitch creativo seleccionado')
 if any(w in t for w in ('eco','echo')): p['voice_effect']='echo';changes.append('eco seleccionado')
 if any(w in t for w in ('robot','robótica','robotica')): p['voice_effect']='robot';changes.append('efecto robot seleccionado')
 if not changes: return {'ok':False,'error':'No identifiqué una acción de audio. Puedes decir «haz una base de trap», «cambia a otro género», «analiza el estilo de Quevedo», «analiza la canción Columbia de Quevedo», «haz música clásica», «añade guitarra» o «hazla más rápida».', 'project':p}
 p['updated_at']=_now();_save(p);return {'ok':True,'project':p,'changes':changes,'reference':reference}
