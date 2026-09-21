(() => {
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const api = async (url, options={}) => {
    const r = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options});
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) throw new Error(data.error || 'No se pudo completar la operación.');
    return data;
  };
  let skills=[];
  let editing=null;
  let runningId=null;
  const resumePending=new Set();

  function ensureUI(){
    if(document.getElementById('zarSkillsPanel')) return;
    const panel=document.createElement('div');
    panel.id='zarSkillsPanel'; panel.className='zarSkillsPanel';
    panel.innerHTML=`<div class="zarSkillsShell">
      <div class="zarSkillsHead"><div><div class="zarSkillsEyebrow">ZAR · SISTEMA DE HABILIDADES</div><h2>🧩 Habilidades</h2><p>Procedimientos reutilizables que quedan guardados en el almacenamiento persistente de ZAR.</p></div><button class="zarSkillsClose" type="button" aria-label="Cerrar">×</button></div>
      <div class="zarSkillHint">Puedes crear una habilidad como «Informe semanal», indicar sus pasos y las herramientas que debería usar. Después puedes decir en el chat: <b>«ZAR, ejecuta mi habilidad Informe semanal sobre esta semana»</b>.</div>
      <div class="zarSkillsToolbar"><button id="zarSkillNew" class="zarSkillPrimary">＋ Nueva habilidad</button><button id="zarLearnNew" class="zarSkillLearn">🧠 Enseñar a ZAR</button><button id="zarSkillRefresh">↻ Actualizar</button><span id="zarSkillsCount"></span></div>
      <div id="zarSkillsEditor" class="zarSkillsEditor" hidden></div><div id="zarLearningBox" class="zarLearningBox" hidden></div><div id="zarLearningJobs" class="zarLearningJobs"></div>
      <div id="zarSkillsList" class="zarSkillsList"></div>
    </div>
    <div id="zarConfirmModal" class="zarConfirmModal" hidden aria-hidden="true">
      <div class="zarConfirmCard" role="dialog" aria-modal="true" aria-labelledby="zarConfirmTitle">
        <div class="zarConfirmIcon">!</div><div class="zarConfirmBody"><h3 id="zarConfirmTitle">Confirmar acción</h3><p id="zarConfirmText"></p></div>
        <div class="zarConfirmActions"><button type="button" id="zarConfirmNo">No, conservar</button><button type="button" id="zarConfirmYes" class="danger">Sí, eliminar definitivamente</button></div>
      </div>
    </div>`;
    document.body.appendChild(panel);
    panel.querySelector('.zarSkillsClose').onclick=closeSkills;
    panel.addEventListener('click',e=>{if(e.target===panel)closeSkills()});
    panel.querySelector('#zarSkillNew').onclick=()=>showEditor(); panel.querySelector('#zarLearnNew').onclick=showLearning;
    panel.querySelector('#zarSkillRefresh').onclick=loadSkills;
    const modal=panel.querySelector('#zarConfirmModal');
    modal.addEventListener('click',e=>{if(e.target===modal) closeConfirm(false)});
    panel.querySelector('#zarConfirmNo').onclick=()=>closeConfirm(false);
    panel.querySelector('#zarConfirmYes').onclick=()=>closeConfirm(true);
  }

  let confirmResolver=null;
  function openConfirm(title,text){
    ensureUI();
    const modal=document.getElementById('zarConfirmModal');
    document.getElementById('zarConfirmTitle').textContent=title||'Confirmar acción';
    document.getElementById('zarConfirmText').textContent=text||'';
    modal.hidden=false; modal.setAttribute('aria-hidden','false');
    requestAnimationFrame(()=>modal.classList.add('open'));
    return new Promise(resolve=>{confirmResolver=resolve;});
  }
  function closeConfirm(answer){
    const modal=document.getElementById('zarConfirmModal');
    if(!modal)return;
    modal.classList.remove('open'); modal.setAttribute('aria-hidden','true');
    setTimeout(()=>{modal.hidden=true;},160);
    const r=confirmResolver; confirmResolver=null; if(r)r(Boolean(answer));
  }

  async function loadSkills(){
    ensureUI();
    const list=document.getElementById('zarSkillsList');
    list.innerHTML='<div class="zarSkillEmpty">Cargando habilidades…</div>';
    try{const data=await api('/api/skills');skills=data.skills||[];render(); if(typeof window.ZARShowActiveSkills==='function') window.ZARShowActiveSkills(skills.filter(x=>x.enabled));}
    catch(e){list.innerHTML='<div class="zarSkillEmpty">⚠️ '+esc(e.message)+'</div>'}
  }

  function render(){
    const list=document.getElementById('zarSkillsList');
    document.getElementById('zarSkillsCount').textContent=skills.length+' guardadas';
    if(!skills.length){list.innerHTML='<div class="zarSkillEmpty">Aún no tienes habilidades. Crea la primera y ZAR podrá reutilizarla en futuras conversaciones.</div>';return;}
    list.innerHTML=skills.map(s=>`<article class="zarSkillCard">
      <div class="zarSkillIcon">🧩</div><div><div class="zarSkillTitle">${esc(s.name)}</div><div class="zarSkillDesc">${esc(s.description||'Sin descripción')}</div><div class="zarSkillMeta"><span>${(s.steps||[]).length} pasos</span><span>${Number(s.use_count||0)} usos</span><span class="${s.enabled?'ok':'off'}">${s.enabled?'ACTIVA':'PAUSADA'}</span></div></div>
      <div class="zarSkillActions"><button data-act="run" data-id="${esc(s.id)}">▶ Ejecutar</button><button data-act="edit" data-id="${esc(s.id)}">Editar</button><button data-act="toggle" data-id="${esc(s.id)}">${s.enabled?'Pausar':'Activar'}</button><button data-act="del" data-id="${esc(s.id)}">Eliminar</button></div>
      <div class="zarSkillRunBox" id="run-${esc(s.id)}"><label class="zarSkillRunLabel">Trabajo concreto <span>· qué quieres que haga ZAR con esta habilidad</span></label><textarea aria-label="Trabajo concreto para la habilidad" placeholder="Ej.: prepara un informe breve sobre cómo está funcionando ZAR…"></textarea><div class="zarSkillRunActions"><span class="zarSkillRunStatus">La habilidad se ejecutará con los pasos y herramientas guardados.</span><button data-act="cancelrun" data-id="${esc(s.id)}">Cancelar</button><button class="zarSkillPrimary" data-act="confirmrun" data-id="${esc(s.id)}">▶ Ejecutar ahora</button></div><div class="zarSkillResult" hidden></div></div>
    </article>`).join('');
    list.querySelectorAll('button[data-act]').forEach(b=>b.onclick=()=>skillAction(b.dataset.act,b.dataset.id));
  }

  function showLearning(){
    const box=document.getElementById('zarLearningBox'); if(!box)return;
    box.hidden=false;
    box.innerHTML=`<div class="zarLearningHead"><div><span>🧠 APRENDIZAJE PERSISTENTE 2.0</span><h3>Enseñar a ZAR</h3><p>ZAR investiga fuentes públicas, organiza un currículo, guarda el conocimiento y crea una capacidad reutilizable. El progreso se muestra por fases y fuentes, no solo por un porcentaje.</p></div><button id="zarLearnClose" type="button">×</button></div>
      <label>¿Qué quieres que aprenda?<input id="learnTopic" maxlength="180" placeholder="Ej. edición profesional de fotografía"></label>
      <label>Objetivo<textarea id="learnGoal" maxlength="1500" placeholder="Ej. que pueda analizar fotos, explicarme técnicas y ayudarme a editar imágenes profesionalmente."></textarea></label>
      <label>Referencias opcionales · una URL por línea<textarea id="learnRefs" placeholder="https://...\nhttps://..."></textarea></label>
      <div class="zarLearningNote">Puedes enseñarle fotografía, idiomas, programación, diseño, workflows de ZAR o conocimiento de un documento. El aprendizaje inicial crea conocimiento y una habilidad; después puedes pedirle que practique y superar las comprobaciones de dominio. ZAR no modifica su propio código automáticamente.</div>
      <div class="zarSkillEditorActions"><button id="zarLearnCancel">Cancelar</button><button id="zarLearnStart" class="zarSkillPrimary">🧠 Empezar a aprender</button></div>
      <div id="zarLearnStatus" class="zarLearningStatus" hidden></div>
      <div id="zarLearnMetrics" class="zarLearningMetrics" hidden></div>
      <div id="zarLearnProgressWrap" class="zarLearningProgressWrap" hidden><div class="zarLearningProgress"><span id="zarLearnProgressBar"></span></div><div id="zarLearnProgressLabel">0%</div></div>`;
    box.querySelector('#zarLearnClose').onclick=()=>box.hidden=true;
    box.querySelector('#zarLearnCancel').onclick=()=>box.hidden=true;
    box.querySelector('#zarLearnStart').onclick=startLearning;
    loadLearningState();
  }
  function formatDuration(sec){sec=Math.max(0,Math.round(Number(sec)||0)); if(sec<60)return sec+' s'; const m=Math.floor(sec/60),s=sec%60; return m+' min'+(s?' '+s+' s':'');}
  function renderLearningJob(job,status,metrics,wrap,bar,label){
    const p=Math.max(0,Math.min(100,Number(job.progress)||0));
    wrap.hidden=false; bar.style.width=p+'%'; label.textContent=p+'%';
    status.hidden=false;
    const elapsed=Number(job.elapsed_seconds)||((job.started_at?Date.now()/1000-job.started_at:0));
    const est=Number(job.estimated_seconds)||0; const remaining=est&&elapsed<est?est-elapsed:0;
    status.innerHTML='🧠 <b>'+esc(job.phase||'Aprendiendo…')+'</b> · '+esc(job.message||'Procesando…')+(job.status==='paused'&&!resumePending.has(job.id)?' <button type="button" id="zarResumeLearning" class="zarInlineResume">▶ Reanudar</button>':job.status==='paused'?' <button type="button" class="zarInlineResume isPending" disabled>⏳ Reanudando…</button>':'');
    if(job.status==='paused'){const rb=document.getElementById('zarResumeLearning');if(rb)rb.onclick=()=>resumeLearning(job.id);}
    metrics.hidden=false;
    metrics.innerHTML='<span>⏱️ Transcurrido: <b>'+formatDuration(elapsed)+'</b></span><span>⏳ Estimado restante: <b>'+(remaining?formatDuration(remaining):'calculando…')+'</b></span><span>🔎 Fuentes: <b>'+Number(job.source_count||0)+'</b></span><span>🌐 Consultas: <b>'+Number(job.queries_done||0)+'/'+Number(job.queries_total||0)+'</b></span>';
  }
  function renderLearningJobs(jobs){
    const box=document.getElementById('zarLearningJobs'); if(!box)return;
    const incoming=Array.isArray(jobs)?jobs:[];
    // Mantener el estado de reanudación de forma optimista: mientras la petición
    // /resume esté en curso, jamás volvemos a pintar el botón "Reanudar" aunque
    // una respuesta concurrente del endpoint todavía devuelva "paused".
    window.__zarLearningJobs=incoming.map(j=>{
      if(!j)return j;
      if(resumePending.has(j.id)) return {...j,status:['queued','researching','synthesizing'].includes(j.status)?j.status:'queued',phase:j.phase||'Reanudando',message:j.message||'Reanudando aprendizaje…'};
      return j;
    });
    const relevant=window.__zarLearningJobs.filter(j=>j && ['queued','researching','synthesizing','paused','completed','error'].includes(j.status)).slice(0,8);
    if(!relevant.length){box.innerHTML='';return;}
    box.innerHTML='<div class="zarLearningJobsHead">🧠 <b>Aprendizajes de ZAR</b><span>estado persistente</span></div>'+relevant.map(j=>{
      const p=Math.max(0,Math.min(100,Number(j.progress)||0));
      const pending=resumePending.has(j.id);
      const active=pending||['queued','researching','synthesizing'].includes(j.status);
      const paused=!pending&&j.status==='paused'; const failed=!pending&&j.status==='error'; const done=j.status==='completed';
      const phase=done?'Aprendizaje completado':pending?'Reanudando aprendizaje…':paused?'Aprendizaje pausado':failed?'Aprendizaje detenido · puedes reintentarlo':active?(j.phase||'Aprendizaje en curso'):'Aprendizaje detenido';
      const cls=done?'done':(paused||failed)?'paused':j.status==='error'?'error':'active';
      const canResume=paused||failed;
      const resumeBtn=canResume?'<button class="zarInlineResume" data-resume="'+esc(j.id)+'" '+(pending?'disabled':'')+'>'+ (pending?'⏳ Reanudando…':(failed?'↻ Reintentar':'▶ Reanudar')) +'</button>':'';
      return '<article class="zarLearningJobCard '+cls+'"><div class="zarLearningJobIcon">'+(done?'✓':paused?'Ⅱ':j.status==='error'?'!':'🧠')+'</div><div class="zarLearningJobMain"><div class="zarLearningJobTitle">'+esc(j.topic||'Aprendizaje')+'</div><div class="zarLearningJobPhase">'+esc(phase)+' <span>· '+esc(pending?'La sesión está arrancando de nuevo…':(j.message||''))+'</span></div><div class="zarLearningMini"><div><span style="width:'+p+'%"></span></div><b>'+p+'%</b></div><div class="zarLearningJobMeta">⏱️ '+formatDuration(j.elapsed_seconds||0)+' · 🔎 '+Number(j.source_count||0)+' fuentes · 🌐 '+Number(j.queries_done||0)+'/'+Number(j.queries_total||0)+' consultas'+(j.estimated_seconds?' · ⏳ '+(Number(j.estimated_seconds)>Number(j.elapsed_seconds||0)?formatDuration(Number(j.estimated_seconds)-Number(j.elapsed_seconds||0)):'calculando…'):'')+'</div></div><div class="zarLearningJobActions">'+resumeBtn+'<button class="zarInlineDelete" data-delete-learning="'+esc(j.id)+'" title="Eliminar aprendizaje">🗑️</button></div></article>';
    }).join('');
    box.querySelectorAll('[data-resume]').forEach(b=>b.onclick=()=>resumeLearning(b.dataset.resume));
    box.querySelectorAll('[data-delete-learning]').forEach(b=>b.onclick=()=>deleteLearning(b.dataset.deleteLearning));
  }
  async function deleteLearning(id){
    const job=(window.__zarLearningJobs||[]).find(x=>x.id===id);
    const label=job?.topic||'este aprendizaje';
    const ok=await openConfirm('Eliminar aprendizaje definitivamente', '¿Quieres eliminar definitivamente «'+label+'»? Si está en marcha, ZAR lo cancelará de forma segura. Si eliges «No, conservar», no se borrará nada.');
    if(!ok)return;
    try{await api('/api/learning/'+encodeURIComponent(id),{method:'DELETE'}); resumePending.delete(id); await loadLearningState(); await loadSkills();}
    catch(e){alert(e.message||'No se pudo eliminar el aprendizaje.');}
  }
  async function loadLearningState(){
    try{
      const data=await api('/api/learning?_='+Date.now());
      const jobs=data.jobs||[]; renderLearningJobs(jobs);
      const active=jobs.find(j=>['queued','researching','synthesizing','paused'].includes(j.status));
      if(active){
        document.getElementById('learnTopic').value=active.topic||''; document.getElementById('learnGoal').value=active.goal||''; document.getElementById('learnRefs').value=(active.references||[]).join('\n');
        const status=document.getElementById('zarLearnStatus'), metrics=document.getElementById('zarLearnMetrics'), wrap=document.getElementById('zarLearnProgressWrap'), bar=document.getElementById('zarLearnProgressBar'), label=document.getElementById('zarLearnProgressLabel');
        renderLearningJob(active,status,metrics,wrap,bar,label); pollLearning(active.id,status,metrics,wrap,bar,label); return;
      }
      const last=jobs[0]; if(last&&last.status==='completed'){
        const status=document.getElementById('zarLearnStatus'); status.hidden=false; status.innerHTML='✅ <b>Último aprendizaje completado.</b> '+esc(last.topic||'')+' · '+Number(last.source_count||0)+' fuentes · '+formatDuration(last.elapsed_seconds||0)+'.';
      }
    }catch(e){}
  }
  async function startLearning(){
    const topic=document.getElementById('learnTopic').value.trim(), goal=document.getElementById('learnGoal').value.trim(), references=document.getElementById('learnRefs').value.split('\n').map(x=>x.trim()).filter(Boolean);
    const status=document.getElementById('zarLearnStatus'), metrics=document.getElementById('zarLearnMetrics'), wrap=document.getElementById('zarLearnProgressWrap'), bar=document.getElementById('zarLearnProgressBar'), label=document.getElementById('zarLearnProgressLabel');
    status.hidden=false; status.textContent='⏳ Preparando aprendizaje…';
    try{if(!topic)throw new Error('Indica qué quieres que aprenda ZAR.'); const data=await api('/api/learning/start',{method:'POST',body:JSON.stringify({topic,goal,references})}); const id=data.job.id; renderLearningJob(data.job,status,metrics,wrap,bar,label); renderLearningJobs([data.job]); pollLearning(id,status,metrics,wrap,bar,label);}catch(e){status.textContent='⚠️ '+e.message;}
  }
  async function resumeLearning(id){
    if(resumePending.has(id))return;
    resumePending.add(id);
    // Pintado inmediato: el usuario debe ver el cambio sin cerrar/reabrir el panel.
    const current=(window.__zarLearningJobs||[]).map(j=>j&&j.id===id?{...j,status:'queued',phase:'Reanudando',message:'Reanudando aprendizaje…'}:j);
    renderLearningJobs(current);
    const status=document.getElementById('zarLearnStatus'),metrics=document.getElementById('zarLearnMetrics'),wrap=document.getElementById('zarLearnProgressWrap'),bar=document.getElementById('zarLearnProgressBar'),label=document.getElementById('zarLearnProgressLabel');
    if(status){status.hidden=false;status.innerHTML='🧠 <b>Reanudando aprendizaje…</b> · La sesión se está iniciando de nuevo.';}
    try{
      const data=await api('/api/learning/'+encodeURIComponent(id)+'/resume',{method:'POST'});
      const job=data.job||{};
      // El botón no puede volver a aparecer por una respuesta "paused" vieja.
      resumePending.delete(id);
      const normalized={...job,status:['queued','researching','synthesizing','completed'].includes(job.status)?job.status:'researching',phase:job.status==='completed'?'Completado':(job.phase||'Reanudando'),message:job.message||'Reanudando aprendizaje…'};
      const merged=[normalized].concat((window.__zarLearningJobs||[]).filter(j=>j.id!==id));
      renderLearningJobs(merged);
      renderLearningJob(normalized,status,metrics,wrap,bar,label);
      pollLearning(id,status,metrics,wrap,bar,label);
    }catch(e){
      resumePending.delete(id);
      renderLearningJobs(window.__zarLearningJobs||[]);
      if(status){status.hidden=false;status.innerHTML='⚠️ '+esc(e.message||'No se pudo reanudar el aprendizaje.');}
    }
  }
  async function pollLearning(id,status,metrics,wrap,bar,label){
    try{
      const data=await api('/api/learning/'+encodeURIComponent(id)+'?_='+Date.now()), job=data.job||{};
      renderLearningJob(job,status,metrics,wrap,bar,label);
      if(resumePending.has(id) && ['queued','researching','synthesizing','completed'].includes(job.status)) resumePending.delete(id);
      renderLearningJobs(data.jobs||[job]);
      if(job.status==='completed'){
        status.innerHTML='✅ <b>Aprendizaje inicial completado.</b> ZAR ha guardado el conocimiento y creado una habilidad reutilizable. Ahora puede practicar y comprobar dominio.'; await loadSkills(); return;
      }
      if(job.status==='error'){status.innerHTML='⚠️ <b>Aprendizaje detenido:</b> '+esc(job.message||'Error desconocido');return;}
      setTimeout(()=>pollLearning(id,status,metrics,wrap,bar,label),1800);
    }catch(e){status.innerHTML='⚠️ '+esc(e.message||'No se pudo consultar el aprendizaje.');setTimeout(()=>pollLearning(id,status,metrics,wrap,bar,label),4000);}
  }

  function showEditor(skill=null){
    editing=skill; const box=document.getElementById('zarSkillsEditor'); box.hidden=false;
    box.innerHTML=`<h3>${skill?'Editar habilidad':'Nueva habilidad'}</h3>
      <div class="zarSkillGrid"><label>Nombre<input id="skName" maxlength="100" value="${esc(skill?.name||'')}" placeholder="Ej. Informe semanal"></label><label>Descripción<textarea id="skDesc" maxlength="1000" placeholder="Qué hace esta habilidad">${esc(skill?.description||'')}</textarea></label></div>
      <label>Pasos · uno por línea<textarea id="skSteps" placeholder="Buscar la información\nAnalizarla\nGenerar el informe">${esc((skill?.steps||[]).join('\n'))}</textarea></label>
      <label>Frases de activación · separadas por comas<input id="skTriggers" value="${esc((skill?.triggers||[]).join(', '))}" placeholder="informe semanal, prepara informe semanal"></label>
      <label>Herramientas previstas · separadas por comas<input id="skTools" value="${esc((skill?.tools||[]).join(', '))}" placeholder="web, memoria, archivos, Gmail"></label>
      <label class="zarSkillCheck"><input id="skEnabled" type="checkbox" ${(skill?.enabled??true)?'checked':''}> Habilidad activa</label>
      <div class="zarSkillEditorActions"><button id="skCancel">Cancelar</button><button id="skSave" class="zarSkillPrimary">Guardar habilidad</button></div>`;
    box.querySelector('#skCancel').onclick=()=>{box.hidden=true;editing=null};
    box.querySelector('#skSave').onclick=saveSkill;
  }

  async function saveSkill(){
    const payload={name:document.getElementById('skName').value,description:document.getElementById('skDesc').value,steps:document.getElementById('skSteps').value.split('\n').map(x=>x.trim()).filter(Boolean),triggers:document.getElementById('skTriggers').value.split(',').map(x=>x.trim()).filter(Boolean),tools:document.getElementById('skTools').value.split(',').map(x=>x.trim()).filter(Boolean),enabled:document.getElementById('skEnabled').checked};
    try{if(!payload.name.trim())throw new Error('Escribe un nombre.');if(editing)await api('/api/skills/'+encodeURIComponent(editing.id),{method:'PATCH',body:JSON.stringify(payload)});else await api('/api/skills',{method:'POST',body:JSON.stringify(payload)});document.getElementById('zarSkillsEditor').hidden=true;editing=null;await loadSkills();}
    catch(e){alert(e.message)}
  }

  async function skillAction(act,id){
    const skill=skills.find(x=>x.id===id); if(!skill)return;
    const card=document.getElementById('run-'+id);
    if(act==='edit'){showEditor(skill);return}
    if(act==='del'){const ok=await openConfirm('Eliminar habilidad definitivamente','¿Quieres eliminar definitivamente la habilidad «'+skill.name+'»? Esta acción no se puede deshacer.');if(!ok)return;try{await api('/api/skills/'+encodeURIComponent(id),{method:'DELETE'});await loadSkills()}catch(e){alert(e.message)}return}
    if(act==='toggle'){try{await api('/api/skills/'+encodeURIComponent(id),{method:'PATCH',body:JSON.stringify({enabled:!skill.enabled})});await loadSkills()}catch(e){alert(e.message)}return}
    if(act==='run'){card?.classList.add('open');card?.querySelector('textarea')?.focus();return}
    if(act==='cancelrun'){card?.classList.remove('open');return}
    if(act==='confirmrun'){
      const input=card?.querySelector('textarea')?.value.trim()||'';
      const resultBox=card?.querySelector('.zarSkillResult');
      if(!input){
        resultBox.hidden=false; resultBox.className='zarSkillResult error'; resultBox.textContent='Escribe primero qué quieres que haga ZAR con esta habilidad.'; return;
      }
      card.classList.add('busy');
      resultBox.hidden=false; resultBox.className='zarSkillResult'; resultBox.textContent='⏳ Ejecutando habilidad…';
      try{
        const data=await api('/api/skills/'+encodeURIComponent(id)+'/execute',{method:'POST',body:JSON.stringify({message:input})});
        const active=data.active_skills||[];
        resultBox.className='zarSkillResult success'; resultBox.textContent=data.result||data.message||'Habilidad ejecutada correctamente.';
        // Llevar el resultado directamente al chat principal.
        closeSkills();
        if(typeof window.ZARShowActiveSkills==='function') window.ZARShowActiveSkills(active);
        if(typeof window.ZARAddChatMessage==='function'){
          window.ZARAddChatMessage('user',input);
          window.ZARAddChatMessage('assistant',data.result||data.message||'Habilidad ejecutada correctamente.');
        }
        await loadSkills();
      }catch(e){
        resultBox.className='zarSkillResult error'; resultBox.textContent='⚠️ '+e.message;
      }finally{card.classList.remove('busy');}
    }
  }

  async function openSkills(){
    ensureUI();
    document.getElementById('zarSkillsPanel').classList.add('open');
    // Al abrir Habilidades también recuperamos los aprendizajes en segundo plano.
    // Antes solo se cargaban las habilidades guardadas, por eso un aprendizaje
    // iniciado desde el chat no aparecía en este panel.
    await loadSkills();
    await loadLearningState();
  }
  function closeSkills(){document.getElementById('zarSkillsPanel')?.classList.remove('open')}
  window.ZARSkills={open:openSkills,load:loadSkills};
  window.ZARSkillsGetActive=()=>skills.filter(s=>s.enabled);

  document.addEventListener('DOMContentLoaded',()=>{ensureUI();});
})();
