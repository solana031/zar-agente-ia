/* General Workspace UI over the existing durable native Google artifact engine. */
(()=>{
 'use strict';
 const kinds={DOC:'Documento',SLIDES:'Presentación',SHEET:'Hoja de cálculo',FORM:'Formulario'};
 const stages={QUEUED:'En cola',PLAN:'Planificando contenido',DESIGN:'Preparando diseño',ASSETS:'Preparando recursos',BUILD:'Creando archivo Google',VALIDATE:'Comprobando contenido',PREVIEW:'Listo',COMPLETED:'Listo',FAILED:'No se pudo completar',WAITING_GOOGLE_AUTH:'Requiere conexión Google'};
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const googleLink=v=>{try{const u=new URL(v);return u.protocol==='https:'&&['docs.google.com','drive.google.com','forms.gle'].includes(u.hostname)?u.href:''}catch{return ''}};
 let stopPrevious=()=>{};
 window.openZarWorkspace=async host=>{
  stopPrevious();let stopped=false,timer=null,csrf='',rows=[],page=0,pendingId='',submitting=false;
  stopPrevious=()=>{stopped=true;clearTimeout(timer);};
  host.innerHTML='<section class="gwCreator"><header><span class="gwEyebrow">CREAR · ORGANIZAR · EDITAR</span><h2>ZAR Workspace</h2><p>Documentos, presentaciones, hojas y formularios editables con tu cuenta Google.</p></header><form data-gw-create><div class="gwGrid"><label>Tipo de archivo<select name="type" aria-label="Tipo de archivo">'+Object.entries(kinds).map(([k,v])=>'<option value="'+k+'">'+v+'</option>').join('')+'</select></label><label>Diseño<select name="theme" aria-label="Diseño">'+[['ZAR','ZAR'],['CORPORATE','Corporativo'],['EDITORIAL','Editorial'],['MINIMAL','Minimalista'],['LIGHT','Claro'],['DARK','Oscuro'],['REPOSNEWS','ReposNews']].map(([k,v])=>'<option value="'+k+'">'+v+'</option>').join('')+'</select></label></div><label>Título<input name="title" required maxlength="180" placeholder="Qué quieres crear"></label><label>Contenido y objetivo<textarea name="request" required maxlength="6000" rows="5" placeholder="Público, propósito, idioma y contenido que necesitas. Puedes pedir tablas, gráficos, imágenes disponibles o secciones."></textarea></label><details><summary>Usar un artículo de ReposNews</summary><label>Artículo de origen<select name="source_article_id" aria-label="Artículo de origen"><option value="">Sin artículo · creación general</option></select></label><p>Reutiliza sus fuentes e imágenes conservadas.</p></details><button type="submit">Crear archivo Google</button></form><p class="gwFeedback" role="status" data-gw-feedback></p><section aria-label="Archivos creados"><div class="gwHeading"><h3>Tus archivos y trabajos</h3><button type="button" data-gw-refresh>Actualizar</button></div><div class="gwJobs"></div><nav class="gwPages" aria-label="Páginas de archivos"><button data-gw-prev>Anterior</button><span data-gw-count></span><button data-gw-next>Siguiente</button></nav></section><details class="gwCompany"><summary>Empresa y documentos fuente</summary><div data-gw-company></div></details></section>';
  const root=host.querySelector('.gwCreator'),form=root.querySelector('form'),feedback=root.querySelector('[data-gw-feedback]');
  function renderJobs(){
   page=Math.min(page,Math.max(0,Math.ceil(rows.length/6)-1));
   root.querySelector('.gwJobs').innerHTML=rows.slice(page*6,(page+1)*6).map(j=>{
    const url=googleLink(j.result?.url),done=j.state==='COMPLETED',label=stages[j.state]||stages[j.stage]||'En proceso';
    return '<article class="gwJob"><span class="gwEyebrow">'+esc(kinds[j.request.type]||j.request.type)+'</span><h4>'+esc(j.request.title)+'</h4><p>'+esc(label)+' · '+esc(new Date(j.updated_at||j.created_at).toLocaleString('es-ES'))+'</p><div class="gwActions">'+(done?'<a href="/workspace-artifact/'+encodeURIComponent(j.id)+'" target="_blank" rel="noopener">Ver</a>':'')+(url?'<a href="'+esc(url)+'" target="_blank" rel="noopener">Abrir en Google</a>':'')+(j.file_id?'<a href="/workspace-artifact/'+encodeURIComponent(j.id)+'" target="_blank" rel="noopener">Editar el mismo archivo</a>':'')+'</div><details><summary>Ver detalles</summary><p>'+esc(j.error||j.result?.validation?.check||'El trabajo se conserva aunque cierres Workspace.')+'</p><p>'+esc(j.result?.validation?.status||'Pendiente de validación')+'</p>'+(j.result?.validation?.limitations||[]).map(x=>'<p>'+esc(x)+'</p>').join('')+'</details></article>';
   }).join('')||'<p class="gwEmpty">Los archivos aparecerán aquí cuando los solicites.</p>';
   root.querySelector('[data-gw-prev]').disabled=page===0;root.querySelector('[data-gw-next]').disabled=(page+1)*6>=rows.length;
   root.querySelector('[data-gw-count]').textContent=rows.length?(page*6+1)+'–'+Math.min((page+1)*6,rows.length)+' de '+rows.length:'Sin trabajos';
  }
  async function refresh(){
   clearTimeout(timer);if(stopped||!root.isConnected)return;
   try{const r=await fetch('/api/workspace/artifacts'),j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||'No se pudieron cargar los trabajos');rows=(j.jobs||[]).slice().reverse();renderJobs();}catch(e){feedback.textContent=e.message;}
   if(!stopped&&root.isConnected)timer=setTimeout(refresh,20000);
  }
  root.querySelector('[data-gw-refresh]').onclick=refresh;
  root.querySelector('[data-gw-prev]').onclick=()=>{page--;renderJobs();};root.querySelector('[data-gw-next]').onclick=()=>{page++;renderJobs();};
  root.querySelector('.gwCompany').ontoggle=e=>{if(e.target.open&&!root.querySelector('.companyWorkspace'))window.openCompanyWorkspace(root.querySelector('[data-gw-company]'));};
  form.oninput=()=>{if(!submitting)pendingId='';};form.onchange=()=>{if(!submitting)pendingId='';};
  form.onsubmit=async e=>{
   e.preventDefault();if(submitting)return;submitting=true;const button=form.querySelector('button[type=submit]');button.disabled=true;feedback.textContent='Guardando tu solicitud…';pendingId=pendingId||crypto.randomUUID();
   try{
    if(!csrf)throw Error('Espera a que termine de cargar Workspace.');
    const r=await fetch('/api/workspace/artifacts',{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify({...Object.fromEntries(new FormData(form)),request_id:pendingId})}),j=await r.json();
    if(!r.ok||!j.ok)throw Error(j.error||'No se pudo guardar la solicitud');pendingId='';page=0;feedback.textContent='Solicitud guardada. ZAR creará el archivo y te avisará en la campana.';await refresh();
   }catch(e){feedback.textContent=e.message;}finally{submitting=false;button.disabled=false;}
  };
  try{
   const r=await fetch('/api/notifications'),j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||'No se pudo cargar la sesión');csrf=j.csrf;
   const options=new Map();for(const n of j.items||[])if(n.article)options.set(n.article.id,n.article.title_es||n.article.id);
   const select=form.elements.source_article_id;select.innerHTML='<option value="">Sin artículo · creación general</option>'+[...options].map(([id,title])=>'<option value="'+esc(id)+'">'+esc(title)+'</option>').join('');
   const selected=new URLSearchParams(location.search).get('source_article');if(options.has(selected))select.value=selected;
  }catch(e){feedback.textContent=e.message;}
  await refresh();
 };
})();
