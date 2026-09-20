"""Public music-reference analysis for Zar Studio.

Zar may inspect public metadata/articles about an artist or a specific song and
turn that into a high-level production profile. It does not download, copy or
reproduce copyrighted recordings, melodies, lyrics, stems or samples.
"""
import json, os, re, requests
from .web_search import google_web_search


def _key(): return os.environ.get('GEMINI_API_KEY','').strip()
def _model(): return os.environ.get('ZAR_API_MODEL','gemini-3.6-flash').strip()


def _extract_json(text):
    text=(text or '').strip(); text=re.sub(r'^```(?:json)?\s*','',text,flags=re.I); text=re.sub(r'\s*```$','',text)
    try:return json.loads(text)
    except Exception:pass
    m=re.search(r'\{.*\}',text,re.S)
    if m:
        try:return json.loads(m.group(0))
        except Exception:pass
    return None


def _parse_reference_request(text):
    t=(text or '').strip()
    patterns=[
        r'(?:canci[oó]n|tema)\s+["“]?(.+?)["”]?\s+(?:de|del)\s+(.+?)(?:\s+(?:y|pero|con|para|que)\b|$)',
        r'(?:canciones|temas|estilo|sonido|música|musica)\s+(?:de|del)\s+(.+?)(?:\s+(?:y|pero|con|para|que)\b|$)',
        r'(?:como|parecida?\s+a|parecido\s+a|similar\s+a)\s+["“]?(.+?)["”]?(?:\s+(?:y|pero|con|para|que)\b|$)',
    ]
    for idx,pattern in enumerate(patterns):
        m=re.search(pattern,t,re.I)
        if not m: continue
        if idx==0:
            title=re.sub(r'["“”\']','',m.group(1)).strip(' .,:;!?¿¡')
            artist=re.sub(r'["“”\']','',m.group(2)).strip(' .,:;!?¿¡')
            return artist[:120], title[:160]
        ref=re.sub(r'["“”\']','',m.group(1)).strip(' .,:;!?¿¡')
        return ref[:120], ''
    # canción/tema sin artista: conserva el título y deja que Internet lo resuelva.
    m=re.search(r'(?:canci[oó]n|tema)\s+["“]?(.+?)["”]?(?:\s+(?:y|pero|con|para|que)\b|$)', t, re.I)
    if m:
        title=re.sub(r'["“”\']','',m.group(1)).strip(' .,:;!?¿¡')
        return '', title[:160]
    return '', ''


def analyze_reference(instruction, artist=None, song=None):
    parsed_artist, parsed_song=_parse_reference_request(instruction)
    artist=(artist or parsed_artist).strip(); song=(song or parsed_song).strip()
    if not artist:
        return {'ok':False,'error':'No pude identificar la referencia. Di «analiza el estilo de Quevedo», «analiza la canción Columbia de Quevedo» o pega el nombre/enlace de una canción.'}
    # If no artist was explicit, search the whole phrase so the web/Gemini can resolve a song or URL.
    focus=f' canción "{song}"' if song else ' estilo general'
    q=f'{instruction} {artist}{focus} BPM tempo género ritmo groove instrumentación producción estructura'

    web=google_web_search(q, 'Busca información pública y fiable. Si la petición contiene una URL, identifica esa página o canción. Prioriza metadatos, BPM/tempo, género, ritmo, instrumentación y descripciones de producción. No descargues audio, letras, samples ni grabaciones.')
    if not web.get('ok'):
        return {'ok':False,'error':web.get('error','No se pudo consultar Internet.')}
    evidence=(web.get('text') or '')[:26000]
    key=_key()
    if not key:
        return {'ok':False,'error':'No hay GEMINI_API_KEY configurada para analizar la referencia.'}
    prompt=f'''Analiza una referencia musical a partir de información pública de Internet.
Artista: {artist}
Canción concreta (si aplica): {song or 'ninguna; analiza el estilo general'}
Petición original: {instruction}
Datos encontrados:
{evidence}

Devuelve SOLO JSON válido:
{{
  "artist":"...",
  "song":"...",
  "songs":[{{"title":"...","bpm":0,"genre":"...","notes":"..."}}],
  "bpm_min":0,
  "bpm_max":0,
  "bpm_target":0,
  "genres":["..."],
  "rhythm":"...",
  "groove":"...",
  "arrangement":"...",
  "instruments":["kick","snare","hat","bass","808","piano","guitar","pluck","pad","strings","bell","lead","organ","brass","marimba","synth"],
  "energy":0.0,
  "production_notes":["..."],
  "source_urls":["..."]
}}

Reglas estrictas:
- Si hay canción concreta, prioriza sus datos; si no hay BPM fiable, usa 0 y no inventes.
- bpm_target debe ser razonable y estar entre bpm_min y bpm_max cuando haya rango.
- Describe SOLO rasgos de alto nivel: tempo, groove, instrumentación, estructura, energía, textura y tratamiento.
- No describas ni reproduzcas melodías, letras, samples, stems ni patrones exactos de una obra.
- La salida se usará para crear una composición NUEVA y original. Nunca pidas ni propongas copiar la canción.
- Para un artista, sintetiza rasgos comunes de varias canciones, no una copia de una sola.
- Si faltan datos, usa una estimación explícita o deja el campo vacío; no inventes fuentes.
'''
    try:
        r=requests.post(
            'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
            headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'},
            json={'model':_model(),'messages':[{'role':'system','content':'Devuelve únicamente JSON válido.'},{'role':'user','content':prompt}], 'temperature':0.15},
            timeout=90,
        )
        r.raise_for_status(); data=r.json(); text=((data.get('choices') or [{}])[0].get('message') or {}).get('content',''); obj=_extract_json(text)
        if not obj:return {'ok':False,'error':'No pude convertir el análisis musical en un perfil estructurado.'}
        obj['ok']=True; obj['artist']=obj.get('artist') or artist; obj['song']=obj.get('song') or song; obj['search_query']=q; obj['web_sources']=web.get('sources') or []
        return obj
    except Exception as exc:
        return {'ok':False,'error':f'No pude analizar la referencia musical: {exc}'}
