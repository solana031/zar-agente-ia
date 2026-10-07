/* Details in the existing Orchestration workspace; no simulated production. */
(() => {
  let csrf='', state, selectedMedia='', filter='', editing=false, lastRendered='';
  const esc=x=>String(x??'Desconocido').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pre=x=>`<pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(x,null,2))}</pre>`;
  const safeAsset=value=>{try{const u=new URL(value,location.origin);return u.origin===location.origin||u.protocol==='https:'?u.href:'';}catch{return '';}};
  const button=(name,id,label)=>`<button type="button" class="zoBtn" data-op="${name}" data-id="${esc(id)}">${label}</button>`;
  const notify=message=>{const el=document.getElementById('zwNotice');if(el)el.textContent=message;};
  async function post(op,data){
    const multipart=data instanceof FormData;
    const r=await fetch('/api/holdings/workflows/'+op,{method:'POST',headers:{'X-ZAR-Business-CSRF':csrf,...(multipart?{}:{'Content-Type':'application/json'})},body:multipart?data:JSON.stringify(data)});
    const j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||'No disponible');
    editing=false;lastRendered='';await refresh();if(window.zarBusinessRefresh)await window.zarBusinessRefresh();return j.result;
  }
  function mediaDetail(project){
    if(!project)return '';
    const r=project.result||{},id=project.id;
    return `<article class="zhCard"><h3>${esc(r.project?.title||'Historia')} · ${esc(r.project_state)}</h3><p>${esc(r.stage_label)} · ${esc(r.progress)}% · ${esc(project.error||'Sin error registrado')}</p>
      <p>Coste estimado ${esc(r.costs?.estimated)} · coste real ${esc(r.costs?.actual)} · proveedor ${esc(r.costs?.provider||'DramaClaw DIRECT')}</p>
      ${button('media_produce',id,'Producir / continuar')}${button('inspect',id,'Sincronizar storyboard/personajes')}${button('assign_voices',id,'Asignar voces disponibles; conservar elecciones')}${button('ready',id,'Aprobar revisión')}
      ${r.preview_url?`<video controls preload="metadata" style="max-width:100%;max-height:400px" src="${esc(r.preview_url)}"></video><a href="${esc(r.download_url)}">Exportar MP4</a>`:''}
      ${r.editor_url?`<p><a href="${esc(r.editor_url)}" target="_blank" rel="noopener">Abrir editor DramaClaw</a></p>`:''}
      <details><summary>Guion / revisión</summary><form data-form="script" data-id="${esc(id)}"><textarea name="script" rows="6" style="width:100%" required>${esc(project.payload?.master_brief||'')}</textarea><button class="zoBtn">Preparar nueva revisión de guion</button></form><p>Conserva la revisión anterior; nueva producción exige confirmación.</p>${pre(r.script)}</details>
      <details><summary>Storyboard / escenas</summary>${(r.scenes||[]).map(s=>`<p>Escena ${esc(s.beat_number)}: ${esc(s.visual_description)} · ${esc(s.narration_segment)}</p>${safeAsset(s.sketch_url||s.frame_url)?`<img loading="lazy" style="max-width:100%;max-height:240px" alt="Storyboard escena ${esc(s.beat_number)}" src="${esc(safeAsset(s.sketch_url||s.frame_url))}">`:""}${button('regenerate_scene',id+'|'+s.beat_number,'Regenerar escena')}`).join('')||'Sincronizar tras la planificación de DramaClaw.'}</details>
      <details><summary>Personajes / voces</summary><p>ElevenLabs produce assets audibles; el montaje por personaje requiere importación y revisión en el editor de DramaClaw. No se afirma que cambie automáticamente el MP4.</p>${button('voices','ElevenLabs','Verificar / listar voces')}<div id="zwVoiceSamples"></div>
      ${(r.characters||[]).map(c=>`<form data-form="voice" data-id="${esc(id)}"><b>${esc(c.name)}</b><p>${esc(c.description)}</p><input type="hidden" name="character" value="${esc(c.name)}"><input name="voice" value="${esc(c.voice||'')}" placeholder="ID ElevenLabs" required><button class="zoBtn">Seleccionar voz</button></form><form data-form="audio" data-id="${esc(id)}"><input type="hidden" name="character" value="${esc(c.name)}"><textarea name="text" placeholder="Texto de este personaje" required></textarea><button class="zoBtn">Generar audio del personaje</button></form>${c.voice_preview?`<audio controls src="${esc(c.voice_preview)}"></audio>`:''}`).join('')}
      ${button('voice_import_review',id,'Confirmar importación/revisión de voces en editor')}</details>
      <details><summary>Subtítulos sincronizados</summary>${button('load_subtitles',id,'Recuperar SRT de DramaClaw')}
      <form data-form="subtitles" data-id="${esc(id)}"><textarea name="text" rows="6" style="width:100%" placeholder="SRT con tiempos reales">${esc(r.subtitles?.text||'')}</textarea><label><input type="checkbox" name="enabled" ${r.subtitles?.enabled===false?'':'checked'}>Activados</label><input name="language" value="${esc(r.subtitles?.language||'es')}"><select name="style">${["default","boxed","high_contrast"].map(p=>`<option ${p===(r.subtitles?.style||"default")?"selected":""}>${p}</option>`).join("")}</select><select name="position">${["bottom","middle","top"].map(p=>`<option ${p===(r.subtitles?.position||"bottom")?"selected":""}>${p}</option>`).join("")}</select><input name="size" type="number" min="10" max="72" value="${esc(r.subtitles?.size||24)}"><button class="zoBtn">Guardar SRT/preferencias</button></form><a href="/api/holdings/workflows/media/${encodeURIComponent(id)}/subtitles">Exportar SRT</a>${button("clean_source",id,"Preparar fuente sin subtítulos")}${button("render_final",id,"Renderizar final con preferencias")}<p>Render local con FFmpeg/libass. Se conserva una fuente anterior. Cambiar el idioma del campo no traduce el texto del SRT.</p></details>
      <details><summary>Publicación revisada</summary>${['youtube','tiktok','instagram'].map(p=>button('publish',id+'|'+p,'Publicar '+p)).join('')}<p>YouTube usa el OAuth existente y sube como privado. Toda publicación exige confirmación.</p>${pre(r.publications||r.publish)}</details><details><summary>Agentes / trazabilidad</summary>${pre(r.agent_trace)}</details></article>`;
  }
  async function refresh(){
    const workspace=document.getElementById('orchestrationWorkspaceInner');if(!workspace||document.getElementById('orchestrationWorkspace')?.hidden)return;
    let host=document.getElementById('zarBusinessWorkflows');if(!host){host=document.createElement('section');host.id='zarBusinessWorkflows';host.className='workspaceCard';workspace.append(host);}
    try{
      const r=await fetch('/api/holdings/workflows',{cache:'no-store'}),j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||'No disponible');csrf=j.csrf;state=j;window.dispatchEvent(new CustomEvent('zar-workflow-state',{detail:j}));if(editing)return;const signature=JSON.stringify([j,selectedMedia,filter]);if(signature===lastRendered)return;lastRendered=signature;
      const rows=(j.jev||[]).filter(x=>!filter||x.decision===filter);
      host.innerHTML=`<h2>JEV · DramaClaw · Sites</h2><nav><a href="#zwJev">JEV</a> · <a href="#zwMedia">Media</a> · <a href="#zwSites">Sites / AdSense</a> ${button('refresh','','Actualizar')}</nav><p id="zwNotice" role="status"></p>
      <details id="zwJev" open><summary>JEV · decisiones persistentes</summary><p>Política local siempre disponible. TypeSafe solo se marca LISTO tras respuesta válida. Costes desconocidos: null; ninguna decisión autoriza pagos.</p>
      <form data-form="jev"><input name="source_agent" value="ZAR Supervisor" required><input name="task" placeholder="Tarea" required><textarea name="action" placeholder="Acción propuesta" required></textarea><input name="expected_cost" type="number" min="0" step="0.01" placeholder="Coste conocido"><input name="expected_revenue" type="number" min="0" step="0.01" placeholder="Ingreso esperado conocido"><input name="currency" value="EUR"><input name="risk" type="number" min="0" max="1" step="0.1" placeholder="Riesgo 0–1"><input name="urgency" type="number" min="0" max="1" step="0.1" placeholder="Urgencia 0–1"><input name="resources" placeholder="Capacidades, separadas por coma"><input name="suggested_provider" placeholder="Proveedor sugerido"><label><input name="remote" type="checkbox">Consultar TypeSafe (puede consumir cuota)</label><button class="zoBtn">Probar decisión</button></form>
      <label>Filtrar <select id="zwDecisionFilter"><option value="">Todas</option>${['APPROVE','REJECT','DEFER','ESCALATE'].map(x=>`<option ${filter===x?'selected':''}>${x}</option>`).join('')}</select></label>
      ${rows.map(x=>`<details><summary>${esc(x.decision)} · ${esc(x.requesting_agent)} · riesgo ${esc(x.output.risk_score)} · coste ${esc(x.output.expected_cost)} · beneficio ${esc(x.output.expected_profit)}</summary>${pre(x)}</details>`).join('')||'<p>Sin decisiones.</p>'}</details>
      <details id="zwMedia" open><summary>ZAR Media · DramaClaw</summary>${button('probe','DramaClaw DIRECT','Probar conexión DIRECT')}
      <form data-form="media"><input name="title" placeholder="Título opcional"><textarea name="story" rows="6" style="width:100%" placeholder="Historia completa inventada" required></textarea><input name="language" value="es"><select name="visual_style"><option>realistic</option><option>anime</option><option>chinese_period_drama</option><option>post_apocalyptic</option></select><select name="format"><option>9:16</option><option>16:9</option><option>1:1</option></select><input name="duration" type="number" min="5" max="600" value="60"><label><input name="subtitles" type="checkbox" checked>Subtítulos</label><input name="subtitle_language" value="es"><label><input name="music" type="checkbox">Música</label><button class="zoBtn">Guardar proyecto DRAFT</button></form>
      ${(j.media||[]).map(p=>button('detail',p.id,esc(p.result?.project?.title||p.id)+' · '+esc(p.result?.project_state))).join('')}${mediaDetail((j.media||[]).find(x=>x.id===selectedMedia))}</details>
      <details id="zwSites" open><summary>ZAR Sites · SiteProject / AdSense</summary><form data-form="site" enctype="multipart/form-data"><input name="name" placeholder="Nombre proyecto" required><input name="topic" placeholder="Temática/idea"><input name="language" value="es"><input name="country" value="ES"><input name="domain" placeholder="dominio.com existente"><textarea name="code" placeholder="HTML opcional" rows="4" style="width:100%"></textarea><input name="files" type="file" multiple accept=".zip,.html,.css,.js,.png,.jpg,.jpeg,.webp,.svg,.gif,.ico,.txt,.xml,.woff,.woff2"><button class="zoBtn">Guardar / importar web</button></form>
      ${(j.sites||[]).map(p=>`<details><summary>${esc(p.name)} · ${esc(p.state||'Estado histórico')} · ${esc(p.domain||'Sin dominio')}</summary>${pre(p)}${p.source_kind==='IDEA'?button('site_build',p.id,'Asignar construcción a BusinessOrchestrator'):''}${button('site_analyze',p.id,'Analizar HTML / SEO')}${p.relative_url?`<iframe title="Preview ${esc(p.name)}" loading="lazy" sandbox="allow-scripts" style="width:100%;height:320px;border:1px solid #334" src="${esc(p.relative_url)}"></iframe>`:''}</details>`).join('')}
      <h3>AdSense · ${esc(j.adsense?.state||'POR CONFIGURAR')}</h3><p>FUENTE: Google AdSense API · DATOS ACTUALIZADOS (consulta ZAR): ${esc(j.adsense?.updated_at)} · Última actualización interna de Google: desconocida. Informes con posible retraso.</p>
      <details><summary>Configurar AdSense</summary><p>Google Cloud OAuth, scope adsense.readonly. Configurar GOOGLE_ADSENSE_ACCESS_TOKEN y GOOGLE_ADSENSE_ACCOUNT en secretos del servidor; publisher para insertar anuncios. Sin introducir tokens en esta UI.</p><a href="https://adsense.google.com" target="_blank" rel="noopener">Abrir AdSense</a></details>
      <form data-form="adsense"><input name="account" placeholder="accounts/pub-… (opcional si solo hay una)"><input name="domain" placeholder="Filtrar sitio (opcional)"><button class="zoBtn">Conectar / sincronizar métricas reales</button></form>${pre(j.adsense)}
      ${(j.adsense?.payments||[]).filter(p=>p.classification==='FINALIZED'&&p.provider_status==='CREDITED_BY_GOOGLE').map(p=>button('received',p.reference,'Confirmar RECEIVED '+esc(p.amount)+' '+esc(p.currency))).join('')}<p>ESTIMATED/FINALIZED no suman saldo disponible. RECEIVED requiere referencia bancaria y confirmación.</p></details>`;
    }catch(e){notify(e.message);}
  }
  document.addEventListener('input',e=>{if(e.target.closest('#zarBusinessWorkflows form'))editing=true;});
  document.addEventListener('change',async e=>{if(e.target.id==='zwDecisionFilter'){filter=e.target.value;await refresh();}});
  document.addEventListener('submit',async e=>{
    const f=e.target;if(!f.matches('#zarBusinessWorkflows form'))return;e.preventDefault();const data=Object.fromEntries(new FormData(f));
    try{
      const kind=f.dataset.form;
      if(kind==='site'){const fd=new FormData(f);for(const [key,value] of [...fd.entries()])if(value instanceof File&&!value.name)fd.delete(key);await post('site_upload',fd);}
      else if(kind==='media'){data.duration=Number(data.duration);data.subtitles=f.elements.subtitles.checked;data.music=f.elements.music.checked;await post('media_create',data);}
      else if(kind==='jev'){for(const k of ['risk','urgency','expected_cost','expected_revenue'])data[k]=data[k]===''?null:Number(data[k]);data.resources=data.resources.split(',').map(x=>x.trim()).filter(Boolean);const remote=f.elements.remote.checked;delete data.remote;if(!data.suggested_provider)data.suggested_provider=null;if(remote&&!confirm('Consultar TypeSafe con esta propuesta puede consumir cuota del proveedor. ¿Continuar?'))return;await post('jev',{proposal:data,use_provider:remote,confirmed:remote});}
      else if(kind==='adsense')await post('adsense_sync',data);
      else if(kind==='script')await post('media_edit',{id:f.dataset.id,script:data.script});
      else if(kind==='voice')await post('media_control',{id:f.dataset.id,control:'voice',...data});
      else if(kind==='audio'){if(!confirm('Generar este audio usa créditos/cuota del proveedor. Coste monetario no disponible. No se realiza compra de saldo. ¿Continuar?'))return;await post('media_control',{id:f.dataset.id,control:'character_audio',confirmed:true,...data});}
      else if(kind==='subtitles'){data.enabled=f.elements.enabled.checked;data.size=Number(data.size);await post('media_control',{id:f.dataset.id,control:'subtitles',...data});}
    }catch(error){notify(error.message);}
  });
  document.addEventListener('click',async e=>{
    const b=e.target.closest('#zarBusinessWorkflows button[data-op]');if(!b)return;const op=b.dataset.op,id=b.dataset.id;
    try{
      if(op==='refresh'){editing=false;await refresh();}
      else if(op==='detail'){selectedMedia=id;editing=false;await refresh();}
      else if(op==='probe')await post('probe',{name:id});
      else if(op==='voices'){const result=await post('probe',{name:'ElevenLabs'});const host=document.getElementById('zwVoiceSamples');if(host)host.innerHTML=(result.voices||[]).map(v=>`<p>${esc(v.name)} · ID ${esc(v.id)}</p>${safeAsset(v.preview_url)?`<audio controls preload="none" src="${esc(safeAsset(v.preview_url))}"></audio>`:''}`).join('');notify(result.state);}
      else if(op==='media_produce'){if(confirm('Producir/continuar esta historia con DramaClaw y sus proveedores puede consumir cuota/créditos. No se comprará saldo ni se publicará automáticamente. ¿Continuar?'))await post(op,{id,confirmed:true});}
      else if(['inspect','assign_voices','load_subtitles','render_final'].includes(op))await post('media_control',{id,control:op});
      else if(op==='ready'||op==='voice_import_review'){if(confirm(op==='ready'?'¿Has revisado el MP4 y apruebas su contenido?':'¿Has importado y verificado las voces seleccionadas en el editor?'))await post('media_control',{id,control:op,confirmed:true});}
      else if(op==='clean_source'){if(confirm('Recomponer fuente sin subtítulos en DramaClaw puede consumir cuota. Se conserva vídeo anterior. ¿Continuar?'))await post('media_control',{id,control:op,confirmed:true});}
      else if(op==='regenerate_scene'){const [project,scene]=id.split('|');if(confirm('Regenerar esta escena puede consumir cuota/créditos del proveedor. ¿Continuar?'))await post('media_control',{id:project,scene:Number(scene),control:op,confirmed:true});}
      else if(op==='publish'){const [project,platform]=id.split('|');if(confirm(`Publicar vídeo revisado en ${platform}. YouTube se subirá privado. ¿Confirmas esta publicación?`))await post('media_publish',{id:project,platform,confirmed:true});}
      else if(op==='received'){const reference=prompt('Referencia bancaria del cobro realmente recibido:');if(reference&&confirm('Registrar como RECEIVED; confirmas que ya recibiste este pago. No se ejecuta transferencia.'))await post('adsense_received',{reference:id,bank_reference:reference,confirmed:true});}
      else if(op==='site_build')await post(op,{id});
      else if(op==='site_analyze'){const result=await post(op,{id});notify(JSON.stringify(result));}
    }catch(error){notify(error.message);}
  });
  window.zarWorkflowRefresh=refresh;
})();
