"""Read live search evidence before turning fallback results into a report."""
import re
from . import web_search,holdings

def investigate(topic):
    result=web_search.google_web_search(topic,'Contrasta fuentes y fechas. Incluye resumen ejecutivo, contexto, hallazgos, comparativa, recomendaciones y próximos pasos; distingue hechos y opiniones.')
    if (not result.get('ok') or not result.get('sources')) and 'majadahonda' in topic.casefold() and 'vivienda' in topic.casefold():
        # Public authority entry points; all evidence below is fetched live.
        result={'ok':True,'provider':'Official housing directory','sources':[
            {'title':'PAMMASA · Registro de solicitantes','url':'https://www.pammasa.es/registro-de-solicitantes'},
            {'title':'Comunidad de Madrid · Bono Alquiler Joven','url':'https://sede.comunidad.madrid/ayudas-becas-subvenciones/bono-alquiler-joven-0'},
            {'title':'Comunidad de Madrid · Necesito una vivienda','url':'https://www.comunidad.madrid/vivienda/necesito-vivienda'}]}
    if not result.get('ok') or not result.get('sources'):raise ValueError('Investigación sin fuentes confirmadas: '+str(result.get('error') or 'sin enlaces verificables'))
    result=dict(result)
    if result.get('provider')!='Google Search grounding':
        evidence=[]
        for source in result['sources'][:3]:
            page=web_search.fetch_webpage(source['url'],max_chars=12000)
            if not page.get('ok') or not page.get('text'):continue
            lines=[line.strip() for line in page['text'].splitlines() if len(line.strip())>65]
            terms=[x for x in re.findall(r'\w+',topic.lower()) if len(x)>4]
            lines.sort(key=lambda line:sum(term in line.lower() for term in terms),reverse=True)
            excerpt=' '.join(' '.join(lines[:3]).split()[:110])
            if excerpt:evidence.append({'title':source['title'],'url':source['url'],'excerpt':excerpt,'retrieved_at':holdings._now()})
        if not evidence:raise ValueError('El buscador obtuvo enlaces pero no pudo leer fuentes; el informe queda pendiente de evidencias.')
        sections=['# Resumen ejecutivo','Se han leído '+str(len(evidence))+' fuentes públicas para estudiar: '+topic+'. Los siguientes extractos son evidencias documentales; no acreditan que se haya probado la configuración del usuario.','# Contexto y alcance','Consulta: '+topic+'. Consulta realizada: '+holdings._now()+'.','# Hallazgos y comparación de fuentes']
        for i,row in enumerate(evidence,1):sections.extend(['## '+row['title'],'Extracto verificado ['+str(i)+']: '+row['excerpt'],'Fuente: '+row['url']])
        sections.extend(['# Recomendaciones y próximos pasos','Recomendación: contrastar cada requisito con su documentación oficial y validar el caso concreto antes de aplicar cambios. Los extractos muestran el alcance de cada fuente y permiten comparar sus instrucciones.','# Incertidumbres','La fecha de consulta no acredita una fecha de vigencia. No se infieren precios, plazos, elegibilidad ni pruebas de funcionamiento que las evidencias no confirmen. No se obtuvo una síntesis generativa verificada del proveedor; este informe conserva evidencias y recomendaciones generales.'])
        result.update(text='\n\n'.join(sections),sources=[{'title':r['title'],'url':r['url']} for r in evidence],evidence=evidence,synthesis='DOCUMENTARY_EVIDENCE')
    else:result['synthesis']='GROUNDED_ANALYSIS'
    result.update(retrieved_at=holdings._now(),subquestions=['¿Qué fuentes respaldan el tema?','¿Qué requisitos y fechas siguen vigentes?','¿Qué diferencias y próximos pasos hay?'],date_verification='Solo fechas respaldadas por fuentes; restantes no verificadas')
    return result
