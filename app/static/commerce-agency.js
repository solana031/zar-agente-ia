/* Commerce and CRM detail inside the existing Orchestration workspace. */
(() => {
  let snapshot, csrf='', tab='Nichos', productId='', leadId='', editing=false, signature='';
  const esc=x=>String(x??'NO DISPONIBLE').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pre=x=>`<pre style="white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto">${esc(JSON.stringify(x,null,2))}</pre>`;
  const input=(name,label,value='',type='text')=>`<label>${esc(label)} <input name="${name}" type="${type}" ${type==='number'?'step="any"':''} value="${esc(value??'')}" style="max-width:100%"></label>`;
  const area=(name,label,value='')=>`<label>${esc(label)}<textarea name="${name}" rows="3" style="width:100%;box-sizing:border-box">${esc(value)}</textarea></label>`;
  const hidden=(name,value)=>`<input type="hidden" name="${name}" value="${esc(value)}">`;
  const options=(rows,label='name')=>rows.map(r=>`<option value="${esc(r.id)}">${esc(r[label]||r.id)}</option>`).join('');
  const select=(name,label,rows)=>`<label>${esc(label)} <select name="${name}" style="max-width:100%">${options(rows)}</select></label>`;
  const action=(op,label,data={})=>`<button type="button" class="zoBtn" data-ca-op="${op}" data-value="${esc(JSON.stringify(data))}">${esc(label)}</button>`;
  const form=(op,body,label,confirmation='')=>`<form data-ca-form="${op}" ${confirmation?`data-confirm="${esc(confirmation)}"`:''} style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0">${body}<button class="zoBtn">${esc(label)}</button></form>`;
  function notice(message){const el=document.getElementById('caNotice');if(el)el.textContent=message;}
  async function post(op,data){
    const r=await fetch('/api/holdings/workflows/'+op,{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify(data)});
    const result=await r.json();if(!r.ok||!result.ok)throw Error(result.error||'No disponible');
    editing=false;signature='';await window.zarWorkflowRefresh?.();await window.zarBusinessRefresh?.();notice(JSON.stringify(result.result));return result.result;
  }
  function productDetail(c){
    const p=c.products.find(x=>x.id===productId);if(!p)return '';
    const listing=c.listings.filter(x=>x.product_id===p.id);
    return `<article class="zhCard"><h3>${esc(p.name)} · ${esc(p.state)} · ${esc(p.model)}</h3>${pre(p)}
      ${form('commerce_pricing',hidden('product_id',p.id)+input('sale_price','Precio venta',p.pricing?.sale_price||p.possible_sale_price||'','number')+input('currency','Moneda',p.currency||'EUR')+
        ['product_cost','shipping','taxes','payment_fee','shopify_fee','supplier_fee','advertising','returns','other'].map(k=>input(k,k,p.pricing?.assumptions?.[k]??'','number')).join('')+input('target_margin','Margen objetivo %',30,'number')+input('premium_margin','Margen premium %',40,'number'),'Calcular supuestos')}
      <p>Vacío significa desconocido. Introducir cero es un supuesto explícito, no un coste verificado.</p>
      ${form('commerce_score',hidden('product_id',p.id)+area('evidence','Evidencias JSON: factor → {value: 0–1, classification: REAL/ESTIMADA, source}', '{}'),'Calcular score transparente')}
      ${form('commerce_product_state',hidden('product_id',p.id)+select('state','Estado',['RESEARCHING','CANDIDATE','REJECTED','APPROVED','PAUSED','DISCONTINUED'].map(x=>({id:x,name:x})))+area('review_evidence','Revisión de riesgos/certificaciones'),'Revisar estado','Confirmas revisión del candidato y sus costes. No se compra ni se publica.')}
      ${form('commerce_listing',hidden('product_id',p.id)+input('title','Título original',p.name)+area('description','Descripción original revisada')+area('bullets','Bullets, separados por coma')+input('seo_title','SEO title',p.name)+area('meta_description','Meta description')+input('tags','Tags, separados por coma')+input('collection','Colección propuesta')+input('compare_at_price','Precio anterior justificable','','number')+area('shipping_policy','Política de envío/devolución revisada')+area('faq','FAQ revisada'),'Guardar preview de listing')}
      ${listing.map(l=>`<details><summary>Listing · ${esc(l.title)} · ${esc(l.state)}</summary>${pre(l)}
        ${form('commerce_shopify_draft',hidden('listing_id',l.id),'Crear borrador Shopify','Crear borrador externo en Shopify. Revisa costes, derechos, variantes y moneda; no se publica todavía.')}
        ${action('commerce_shopify_publications','Leer canales Shopify')}
        ${form('commerce_shopify_publish',hidden('listing_id',l.id)+input('publication_id','ID del canal/publication revisado'),'Publicar listing','Publicar el producto revisado en el canal Shopify indicado. Puede quedar visible a clientes.')}
        ${form('commerce_shopify_pause',hidden('listing_id',l.id),'Pausar en Shopify','Pausar producto remoto en Shopify.')}</details>`).join('')}</article>`;
  }
  function commerce(c){
    if(tab==='Nichos')return `<h3>Nichos editables</h3>${c.niches.map(n=>`<details><summary>${esc(n.name)} · ${esc(n.country)}</summary>${form('commerce_niche',hidden('id',n.id)+input('name','Nombre',n.name)+input('country','País',n.country)+area('subniches','Subnichos, separados por coma',(n.subniches||[]).join(', '))+area('restrictions','Restricciones, separadas por coma',(n.restrictions||[]).join(', '))+input('budget','Presupuesto',n.budget||'','number')+input('minimum_margin','Margen mínimo %',n.minimum_margin||'','number')+input('target_price','Precio objetivo',n.target_price||'','number')+input('competition_tolerance','Competencia tolerada',n.competition_tolerance||'')+input('max_shipping_days','Envío máximo días',n.max_shipping_days||'','number'),'Guardar nicho')}${action('commerce_research','Investigar con fuentes públicas',{niche_id:n.id})}</details>`).join('')}
      ${form('commerce_niche',input('name','Nuevo nicho')+input('country','País','ES')+input('target_price','Precio objetivo','','number')+input('minimum_margin','Margen mínimo %','','number')+area('subniches','Subnichos / tendencia'),'Crear nicho personalizado')}${pre(c.research)}`;
    if(tab==='Proveedores')return `${form('commerce_supplier',input('name','Proveedor real')+select('model','Modelo',['DROPSHIPPING','WHOLESALE','PRINT_ON_DEMAND','MARKETPLACE','MANUAL_FULFILLMENT','NO_COMPATIBLE'].map(x=>({id:x,name:x})))+input('env_prefix','Prefijo variables','ZAR_SUPPLIER')+input('source_url','Fuente/contrato')+'<label><input name="supports_dropshipping" type="checkbox">Envío directo confirmado por proveedor</label>'+input('shipping_countries','Países, separados por coma')+area('return_policy','Devoluciones'),'Registrar proveedor')}
      <p>Contrato privado configurable por proveedor. Variables PREFIX_CATALOG_URL, PREFIX_QUOTE_URL, PREFIX_ORDER_WEBHOOK, PREFIX_TRACKING_URL, PREFIX_API_TOKEN; secrets en servidor. Sin API: MANUAL_ACTION_REQUIRED.</p>${pre(c.suppliers)}
      ${form('commerce_scout',select('supplier_id','Proveedor',c.suppliers)+select('niche_id','Nicho',c.niches)+input('query','Producto a buscar'),'Consultar catálogo conectado')}`;
    if(tab==='Productos')return `${form('commerce_product',input('name','Nombre')+select('supplier_id','Proveedor',c.suppliers)+select('niche_id','Nicho',c.niches)+input('supplier_sku','SKU proveedor')+input('category','Categoría')+input('currency','Moneda conocida','EUR')+input('cost','Coste conocido','','number')+input('shipping','Envío conocido','','number')+input('stock','Stock conocido','','number')+input('shipping_days','Días envío','','number')+area('description','Descripción revisada')+input('source_url','Fuente')+'<label><input name="dropshipping" type="checkbox">Envío directo de este producto confirmado</label>','Guardar candidato')}
      ${c.products.map(p=>action('select_product',p.name+' · '+p.state,{id:p.id})).join('')}${productDetail(c)}`;
    if(tab==='Catálogo')return `${pre(c.listings)}${c.products.map(p=>action('select_product','Detalle '+p.name,{id:p.id})).join('')}`;
    if(tab==='Pedidos'||tab==='Fulfillment')return `${action('commerce_shopify_sync','Verificar Shopify / sincronizar tienda, catálogo y pedidos')}<p>No acredita cobros ni envía órdenes al proveedor.</p>${c.orders.map(o=>`<details><summary>${esc(o.name||o.id)} · ${esc(o.state)}</summary>${pre(o)}
      ${form('commerce_quote',hidden('order_id',o.id)+select('product_id','Producto proveedor correspondiente al SKU',c.products)+input('quantity','Cantidad exacta línea',1,'number')+input('country','País destino'),'Obtener quote real')}
      ${form('commerce_order_prepare',select('quote_id','Quote vigente',c.quotes.filter(q=>q.order_id===o.id)),'Preparar compra / aprobación Wallet')}
      <p>Revisar y reservar la aprobación en el panel Wallet. Ejecución posterior exige confirmación específica.</p>
      ${form('commerce_order_execute',hidden('order_id',o.id)+input('total','Total exacto del quote')+area('shipping_address','Dirección revisada JSON: name,address1,city,postal_code,country'),'Ejecutar compra aprobada','Enviar orden al proveedor con posible cargo REAL. Confirmas SKU, cantidad, dirección, impuestos, envío, total y reserva Wallet.')}
      ${form('commerce_order_reconcile',hidden('order_id',o.id),'Reconciliar intención / cargo existente','Consultar intención enviada al proveedor. No reenvía la compra; libera reserva solo ante cancelación sin cargo confirmada.')}
      ${action('commerce_tracking','Consultar tracking real',{order_id:o.id})}
      ${form('commerce_fulfill',hidden('order_id',o.id)+input('fulfillment_order_ids','IDs fulfillment orders revisados, separados por coma'),'Actualizar fulfillment Shopify','Marcar solo unidades enviadas por proveedor en Shopify. No se notificará automáticamente al cliente.')}
      ${form('commerce_receipt',hidden('order_id',o.id)+input('amount','Cobro bancario recibido','','number')+input('currency','Moneda',o.currency)+input('bank_reference','Referencia bancaria'),'Registrar RECEIVED','Confirmas dinero realmente recibido. Un pedido PAID no demuestra cobro bancario.')}
      ${form('commerce_ticket',hidden('order_id',o.id)+area('message','Consulta real del cliente'),'Preparar respuesta de soporte')}
      ${form('commerce_return',hidden('order_id',o.id)+area('reason','Motivo de devolución'),'Abrir solicitud; no reembolsar')}</details>`).join('')}${pre(c.fulfillments)}`;
    if(tab==='Ventas'||tab==='Márgenes')return `${pre(c.dashboard)}${action('commerce_optimization','Analizar rentabilidad / stock')}${pre(c.optimization)}${pre(c.products.map(p=>({product:p.name,pricing:p.pricing,score:p.score})))}`;
    if(tab==='Devoluciones')return `${pre(c.returns)}${pre(c.tickets)}<p>Respuestas son borradores. Excepciones, fraude, chargebacks y cuestiones legales escalan a Pablo.</p>`;
    return `<p>Capacidades persistentes en el registro BusinessOrchestrator; las operaciones externas se revisan desde estas vistas.</p>${pre(c.operations.slice(-30))}
      ${form('queue',select('agent','Agente',['NicheResearchAgent','ProductScoutAgent','SupplierAgent','MarginAgent','PricingAgent','ListingAgent','OptimizationAgent'].map(x=>({id:x,name:x})))+select('tool','Herramienta',['commerce_research','commerce_score','commerce_compare','commerce_pricing','commerce_listing','commerce_review'].map(x=>({id:x,name:x})))+area('payload','Input JSON revisado','{}'),'Asignar tarea BusinessOrchestrator')}`;
  }
  function agency(a){
    const lead=a.leads.find(x=>x.id===leadId);
    return `<h2>Web Agency · CRM</h2>${form('agency_lead',input('name','Negocio real')+input('sector','Sector')+input('city','Ciudad')+input('address','Dirección pública')+input('phone','Teléfono público')+input('email','Email público')+input('website','Web existente')+input('source_url','Fuente pública')+area('services','Servicios reales')+area('branding','Branding confirmado'),'Registrar lead')}
      ${form('agency_discover',input('query','Google Maps: sector / ciudad')+input('limit','Máximo resultados',10,'number'),'Buscar leads Maps','Consulta limitada a Google Places; puede consumir cuota. No envía contactos.')}
      <div style="display:flex;gap:10px;overflow:auto">${['LEAD','RESEARCH','DEMO','CONTACTED','REPLIED','NEGOTIATING','WON','LOST','DO_NOT_CONTACT'].map(s=>`<section class="zhCard" style="min-width:160px"><b>${s}</b>${a.leads.filter(x=>x.state===s).map(x=>`<p>${action('select_lead',x.name,{id:x.id})}</p>`).join('')}</section>`).join('')}</div>
      ${lead?`<article class="zhCard"><h3>${esc(lead.name)} · ${esc(lead.state)}</h3>${pre(lead)}
      ${form('agency_lead',hidden('id',lead.id)+input('name','Nombre',lead.name)+input('sector','Sector',lead.sector)+input('city','Ciudad',lead.city)+input('email','Email público revisado',lead.email||'')+area('services','Servicios reales',lead.services||'')+area('branding','Branding',lead.branding||''),'Editar lead')}
      ${action('agency_research','Investigar fuentes públicas',{lead_id:lead.id})}
      ${form('agency_pricing',hidden('lead_id',lead.id)+input('cost','Coste estimado','','number')+input('minimum','MINIMUM','','number')+input('target','TARGET total incluido','','number')+input('premium','PREMIUM','','number')+input('currency','Moneda','EUR')+input('taxes','Impuestos incluidos conocidos','','number')+area('scope','Alcance/supuestos y fiscalidad revisados'),'Guardar propuesta')}
      ${form('agency_demo',hidden('lead_id',lead.id)+input('price','Precio propuesto','','number'),'Crear demo específica local')}
      ${form('agency_outreach',hidden('lead_id',lead.id)+input('preview_url','URL compartible revisada (opcional)'),'Preparar outreach; no enviar')}
      ${action('agency_inbound_sync','Leer respuestas Gmail y clasificar',{lead_id:lead.id})}
      ${(lead.emails||[]).filter(x=>!x.sent).map(d=>form('agency_send',hidden('lead_id',lead.id)+hidden('draft_id',d.id)+pre({to:d.to,subject:d.subject,body:d.body,send_intent:d.send_intent}),'Enviar este borrador por Gmail','Confirmas destinatario, asunto, texto e identidad ZAR revisados; este envío es real.')).join('')}
      ${form('agency_state',hidden('lead_id',lead.id)+select('state','Etapa CRM',['LEAD','RESEARCH','DEMO','CONTACTED','REPLIED','NEGOTIATING','WON','LOST','DO_NOT_CONTACT'].map(x=>({id:x,name:x})))+area('evidence','Evidencia de contacto/respuesta real'),'Registrar etapa','Confirmas evidencia y cambio de etapa. Un borrador no cuenta como email enviado.')}
      ${form('agency_inbound',hidden('lead_id',lead.id)+input('message_id','ID real del mensaje Gmail')+select('classification','Clasificación revisada',['INTERESTED','TOO_EXPENSIVE','QUESTION','NOT_INTERESTED','DO_NOT_CONTACT','ACCEPTED','OTHER'].map(x=>({id:x,name:x}))),'Importar respuesta del buzón')}
      ${form('agency_negotiate',hidden('lead_id',lead.id)+area('message','Respuesta real / objeción')+input('offer','Oferta propuesta','','number')+area('scope_change','Cambio de alcance'),'Preparar negociación dentro de MINIMUM')}
      ${action('agency_payment_probe','Verificar cuenta Stripe')}
      ${form('agency_checkout',hidden('lead_id',lead.id)+input('total','TARGET exacto de propuesta'),'Crear checkout Stripe','Crear enlace real de pago para propuesta y total revisados. No se piden tarjetas por email ni se acredita dinero todavía.')}
      ${action('agency_payment_sync','Verificar pago con Stripe',{lead_id:lead.id})}
      ${form('agency_receipt',hidden('lead_id',lead.id)+input('amount','Cobro bancario real','','number')+input('bank_reference','Referencia bancaria'),'Registrar cobro Wallet','Confirmas recepción bancaria real de un pago live verificado; test mode no suma ingresos.')}
      ${form('agency_delivery',hidden('lead_id',lead.id)+input('url','URL HTTPS del proyecto entregado')+area('notes','Notas de entrega'),'Registrar entrega revisada','Confirmas revisión y entrega real del proyecto pagado; no se despliega desde este control.')}
      ${lead.demo?.relative_url?`<a href="${esc(lead.demo.relative_url)}" target="_blank" rel="noopener">Abrir demo compartible</a>`:''}</article>`:''}${pre(a.payments)}`;
  }
  function render(j){
    snapshot=j;csrf=j.csrf;const workspace=document.getElementById('orchestrationWorkspaceInner');if(!workspace)return;
    let host=document.getElementById('zarCommerceAgency');if(!host){host=document.createElement('section');host.id='zarCommerceAgency';host.className='workspaceCard';workspace.append(host);}
    if(editing)return;const next=JSON.stringify([j.commerce,j.agency,tab,productId,leadId]);if(next===signature)return;signature=next;
    const c=j.commerce||{niches:[],products:[],suppliers:[],listings:[],orders:[],quotes:[],fulfillments:[],operations:[]};
    host.innerHTML=`<h2>ZAR Commerce</h2><p id="caNotice" role="status"></p><nav>${['Nichos','Productos','Proveedores','Catálogo','Pedidos','Fulfillment','Ventas','Márgenes','Devoluciones','Agentes','BusinessOrchestrator'].map(x=>action('tab',x,{name:x})).join('')}</nav>${commerce(c)}${agency(j.agency||{leads:[],payments:[]})}`;
  }
  window.addEventListener('zar-workflow-state',e=>render(e.detail));
  document.addEventListener('input',e=>{if(e.target.closest('#zarCommerceAgency form'))editing=true;});
  document.addEventListener('click',async e=>{
    const b=e.target.closest('#zarCommerceAgency [data-ca-op]');if(!b)return;
    const op=b.dataset.caOp,data=JSON.parse(b.dataset.value);
    try{
      if(op==='tab'){tab=data.name;editing=false;signature='';render(snapshot);}
      else if(op==='select_product'){productId=data.id;tab='Productos';editing=false;signature='';render(snapshot);}
      else if(op==='select_lead'){leadId=data.id;editing=false;signature='';render(snapshot);}
      else await post(op,data);
    }catch(error){notice(error.message);}
  });
  document.addEventListener('submit',async e=>{
    const f=e.target;if(!f.matches('#zarCommerceAgency form'))return;e.preventDefault();const data=Object.fromEntries(new FormData(f));
    try{
      if(f.dataset.confirm){if(!await ZarUI.confirm(f.dataset.confirm))return;data.confirmed=true;}
      for(const k of ['subniches','restrictions','shipping_countries','tags','bullets','fulfillment_order_ids'])if(k in data)data[k]=data[k].split(',').map(x=>x.trim()).filter(Boolean);
      for(const k of ['evidence','payload','shipping_address'])if(k in data && (f.dataset.caForm==='commerce_score'||k!=='evidence'))data[k]=JSON.parse(data[k]);
      for(const k of ['quantity','limit'])if(k in data)data[k]=Number(data[k]);
      for(const k of ['supports_dropshipping','dropshipping'])if(f.elements[k])data[k]=f.elements[k].checked;
      if(f.dataset.caForm==='queue'){
        const r=await fetch('/api/holdings/orchestration/task',{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify({...data,request_id:crypto.randomUUID()})});
        const result=await r.json();if(!r.ok)throw Error(result.error);editing=false;await window.zarBusinessRefresh?.();notice('Tarea persistida; ejecución sujeta a modo y JEV.');
      }else await post(f.dataset.caForm,data);
    }catch(error){notice(error.message);}
  });
})();
