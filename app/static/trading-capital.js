/* Explicit accounting budgets for Paper. No browser credentials. */
(()=>{
 let csrf='',busy=false,last=0,capital;
 const esc=x=>String(x??'UNKNOWN').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const json=x=>`<pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(x,null,2))}</pre>`;
 window.zarTradingRefresh=async(force=false)=>{
  const panel=document.getElementById('zsTab-automaton');if(!panel?.classList.contains('active')||busy||(!force&&Date.now()-last<5000))return;
  let host=document.getElementById('zsTradingBudget');if(!host){host=document.createElement('section');host.id='zsTradingBudget';host.className='zsCard';panel.append(host);}
  if(!force && host.querySelector('form')?.dataset.dirty)return;
  busy=true;last=Date.now();
  try{
   const r=await fetch('/api/stonks/automaton/capital');const j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||'Capital no disponible');csrf=j.csrf;capital=j.capital;
   if(!force && host.querySelector('form')?.dataset.dirty)return;
   window.zarPaperCapital=capital;
   host.innerHTML=`<button type="button" class="zsBtn" data-reset-paper>RESTABLECER PAPER</button><p>Comprueba broker, cuenta, feed y Risk. Retira solo la revocación Paper; conserva pausa y motor apagado.</p><h3>WALLET ↔ TRADING CAPITAL · ${esc(capital.currency)}</h3><p>Wallet disponible para asignación: ${esc(capital.wallet_available)} · Capital asignado: ${esc(capital.assigned)}</p><p>${esc(capital.note)}</p>
   <form data-trading-capital><label>Acción <select name="action"><option value="assign">Asignar Wallet → Automaton</option><option value="return">Devolver Automaton → Wallet</option><option value="reverse">Revertir asignación completa</option></select></label><label>Importe USD <input name="amount" type="number" min="0.01" step="0.01" required></label><label>Motivo <input name="reason" required maxlength="500"></label><label>ID original si reversión <input name="reverses"></label><input name="transaction_id" type="hidden" value="${crypto.randomUUID()}"><button class="zsBtn" type="submit">Revisar movimiento</button></form><p id="zsCapitalNotice" role="status"></p><details><summary>Histórico auditable</summary>${json(capital.transactions)}</details><details open><summary>Portfolio broker Paper</summary><div id="zsAutomatonPortfolio">Consultando broker…</div></details>`;
   const portfolio=await fetch('/api/stonks/alpaca/portfolio').then(r=>r.json());const account=portfolio.account||{};
   document.getElementById('zsAutomatonPortfolio').innerHTML=portfolio.ok?json({broker:'Alpaca Paper',cash:account.cash,buying_power:account.buying_power,invested_long:account.long_market_value,invested_short:account.short_market_value,daily_pnl:portfolio.day_pl,positions:portfolio.positions,market:portfolio.market}):`<p>${esc(portfolio.state||'ERROR')} · ${esc(portfolio.error)}</p>`;
   const status=await fetch('/api/stonks/status').then(r=>r.json());const resume=document.getElementById('zsAutomatonStart');if(resume)resume.textContent=status.automaton?.state==='PAUSED'?'REANUDAR':'ENCENDER';
   const summary=document.getElementById('zsAutomatonCapital'),metrics=status.paper_account_metrics;
   if(summary)summary.textContent=`PAPER · presupuesto contable separado de equity broker\nCAPITAL ASSIGNED: ${capital.assigned} USD\nCASH: ${account.cash??'UNKNOWN'} USD\nBUYING POWER: ${account.buying_power??'UNKNOWN'} USD\nINVESTED LONG/SHORT: ${account.long_market_value??'UNKNOWN'} / ${account.short_market_value??'UNKNOWN'} USD\nDAILY P&L: ${portfolio.day_pl??'UNKNOWN'} USD\nTOTAL RETURN: ${metrics?.total_return_pct??'UNKNOWN'} %\nDRAWDOWN: ${metrics?.drawdown_pct??'UNKNOWN'} %`;
   const extra=document.createElement('details');extra.innerHTML=`<summary>Riesgo, actividad, órdenes y revisión</summary>${json({mode:status.execution_mode,broker_status:status.paper_connected?'CONNECTED':'UNVERIFIED',feed:status.market_stream,heartbeat:status.automaton?.last_heartbeat,account_metrics:status.paper_account_metrics??null,risk:{max_trade:status.max_trade_eur,max_daily_loss:status.max_daily_loss_eur,max_position_pct:status.max_position_pct},orders:status.engine_last_open_orders||[],last_decision:status.engine_last_action,activity:status.agent_last_trace||[],realized_paper_pnl:status.paper_learning?.overall?.realized_pnl??null,outcomes:status.paper_learning??null})}`;host.append(extra);
  }catch(e){host.textContent='ERROR: '+e.message;}finally{busy=false;}
 };
 document.addEventListener('click',async e=>{const b=e.target.closest('[data-reset-paper]');if(!b)return;if(!confirm('RESTABLECER PAPER: verificar preflight y retirar únicamente revocación Paper. Motor apagado y pausado; cero órdenes.'))return;b.disabled=true;try{const r=await fetch('/api/stonks/automaton/reset-paper',{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify({confirmed:true,mode:'PAPER'})});const j=await r.json();if(!r.ok||!j.ok)throw Error(j.error);await window.zsRefreshStatus?.();await zarTradingRefresh(true);document.getElementById('zsCapitalNotice').textContent='Paper restablecido: pausado y motor apagado. ENCENDER requiere acción explícita.';}catch(err){document.getElementById('zsCapitalNotice').textContent=err.message;}finally{b.disabled=false;}});
 document.addEventListener('input' ,e=>{const f=e.target.closest('[data-trading-capital]');if(f)f.dataset.dirty='true';});
 document.addEventListener('submit',async e=>{
  if(!e.target.matches('[data-trading-capital]'))return;e.preventDefault();const f=e.target,data=Object.fromEntries(new FormData(f));
  if(!confirm(`${data.action} · ${data.amount} USD\nWallet disponible: ${capital.wallet_available}\nAsignado: ${capital.assigned}\nReserva contable Paper; no depósito bancario.\nMotivo: ${data.reason}`))return;
  const b=f.querySelector('button');b.disabled=true;
  try{const r=await fetch('/api/stonks/automaton/capital',{method:'POST',headers:{'Content-Type':'application/json','X-ZAR-Business-CSRF':csrf},body:JSON.stringify({...data,confirmed:true,currency:'USD'})});const j=await r.json();if(!r.ok||!j.ok)throw Error(j.error);if(j.transaction?.status!=='CONFIRMED')throw Error('Movimiento '+(j.transaction?.status||'UNKNOWN')+'; revisar histórico antes de reintentar.');await zarTradingRefresh(true);}
  catch(err){document.getElementById('zsCapitalNotice').textContent=err.message;}finally{b.disabled=false;}
 });
})();
