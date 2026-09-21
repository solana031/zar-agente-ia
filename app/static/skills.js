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

  function ensureUI(){
    if(document.getElementById('zarSkillsPanel')) return;
    const panel=document.createElement('div');
    panel.id='zarSkillsPanel'; panel.className='zarSkillsPanel';
    panel.innerHTML=`<div class="zarSkillsShell">
      <div class="zarSkillsHead"><div><div class="zarSkillsEyebrow">ZAR · SISTEMA DE HABILIDADES</div><h2>🧩 Habilidades</h2><p>Procedimientos reutilizables que quedan guardados en el almacenamiento persistente de ZAR.</p></div><button class="zarSkillsClose" type="button" aria-label="Cerrar">×</button></div>
      <div class="zarSkillHint">Puedes crear una habilidad como «Informe semanal», indicar sus pasos y las herramientas que debería usar. Después puedes decir en el chat: <b>«ZAR, ejecuta mi habilidad Informe semanal sobre esta semana»</b>.</div>
      <div class="zarSkillsToolbar"><button id="zarSkillNew" class="zarSkillPrimary">＋ Nueva habilidad</button><button id="zarSkillRefresh">↻ Actualizar</button><span id="zarSkillsCount"></span></div>
      <div id="zarSkillsEditor" class="zarSkillsEditor" hidden></div>
      <div id="zarSkillsList" class="zarSkillsList"></div>
    </div>`;
    document.body.appendChild(panel);
    panel.querySelector('.zarSkillsClose').onclick=closeSkills;
    panel.addEventListener('click',e=>{if(e.target===panel)closeSkills()});
    panel.querySelector('#zarSkillNew').onclick=()=>showEditor();
    panel.querySelector('#zarSkillRefresh').onclick=loadSkills;
  }

  async function loadSkills(){
    ensureUI();
    const list=document.getElementById('zarSkillsList');
    list.innerHTML='<div class="zarSkillEmpty">Cargando habilidades…</div>';
    try{const data=await api('/api/skills');skills=data.skills||[];render();}
    catch(e){list.innerHTML='<div class="zarSkillEmpty">⚠️ '+esc(e.message)+'</div>'}
  }

  function render(){
    const list=document.getElementById('zarSkillsList');
    document.getElementById('zarSkillsCount').textContent=skills.length+' guardadas';
    if(!skills.length){list.innerHTML='<div class="zarSkillEmpty">Aún no tienes habilidades. Crea la primera y ZAR podrá reutilizarla en futuras conversaciones.</div>';return;}
    list.innerHTML=skills.map(s=>`<article class="zarSkillCard">
      <div class="zarSkillIcon">🧩</div><div><div class="zarSkillTitle">${esc(s.name)}</div><div class="zarSkillDesc">${esc(s.description||'Sin descripción')}</div><div class="zarSkillMeta"><span>${(s.steps||[]).length} pasos</span><span>${Number(s.use_count||0)} usos</span><span class="${s.enabled?'ok':'off'}">${s.enabled?'ACTIVA':'PAUSADA'}</span></div></div>
      <div class="zarSkillActions"><button data-act="run" data-id="${esc(s.id)}">▶ Ejecutar</button><button data-act="edit" data-id="${esc(s.id)}">Editar</button><button data-act="toggle" data-id="${esc(s.id)}">${s.enabled?'Pausar':'Activar'}</button><button data-act="del" data-id="${esc(s.id)}">Eliminar</button></div>
      <div class="zarSkillRunBox" id="run-${esc(s.id)}"><textarea placeholder="Indica el trabajo concreto que quieres hacer con esta habilidad…"></textarea><div class="zarSkillRunActions"><button data-act="cancelrun" data-id="${esc(s.id)}">Cancelar</button><button class="zarSkillPrimary" data-act="confirmrun" data-id="${esc(s.id)}">Ejecutar ahora</button></div><div class="zarSkillResult" hidden></div></div>
    </article>`).join('');
    list.querySelectorAll('button[data-act]').forEach(b=>b.onclick=()=>skillAction(b.dataset.act,b.dataset.id));
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
    if(act==='del'){if(!confirm('¿Eliminar la habilidad «'+skill.name+'»?'))return;try{await api('/api/skills/'+encodeURIComponent(id),{method:'DELETE'});await loadSkills()}catch(e){alert(e.message)}return}
    if(act==='toggle'){try{await api('/api/skills/'+encodeURIComponent(id),{method:'PATCH',body:JSON.stringify({enabled:!skill.enabled})});await loadSkills()}catch(e){alert(e.message)}return}
    if(act==='run'){card?.classList.add('open');card?.querySelector('textarea')?.focus();return}
    if(act==='cancelrun'){card?.classList.remove('open');return}
    if(act==='confirmrun'){
      const input=card?.querySelector('textarea')?.value.trim()||''; if(!input){alert('Indica qué quieres hacer con esta habilidad.');return}
      const resultBox=card.querySelector('.zarSkillResult'); resultBox.hidden=false; resultBox.textContent='Ejecutando habilidad…';
      try{const data=await api('/api/skills/'+encodeURIComponent(id)+'/execute',{method:'POST',body:JSON.stringify({message:input})});resultBox.textContent=data.result||data.message||'Habilidad ejecutada correctamente.';await loadSkills();}
      catch(e){resultBox.textContent='⚠️ '+e.message}
    }
  }

  function openSkills(){ensureUI();document.getElementById('zarSkillsPanel').classList.add('open');loadSkills()}
  function closeSkills(){document.getElementById('zarSkillsPanel')?.classList.remove('open')}
  window.ZARSkills={open:openSkills,load:loadSkills};
  document.addEventListener('DOMContentLoaded',()=>{ensureUI();});
})();
