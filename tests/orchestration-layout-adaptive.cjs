const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const html = fs.readFileSync('app/templates/index.html', 'utf8');
const match = html.match(/<script id="zar-orchestration-global-js-v31-3-49">([\s\S]*?)<\/script>/);
assert(match, 'No se encontró el script de orquestación v31.3.49');

const sandbox = {
  window: { addEventListener() {} },
  document: {},
  console,
  localStorage: { getItem(){ return null; }, setItem(){} },
  ResizeObserver: class { observe(){} },
  setTimeout(){},
  setInterval(){},
  clearInterval(){},
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(match[1], sandbox);

assert.strictEqual(typeof sandbox.window.zoLayout, 'function', 'zoLayout debe existir');

function agents(generalCount, financeOuterCount) {
  const out = [
    {id:'zar_supervisor', domain:'core'},
    {id:'stonks_supervisor', domain:'finance'},
  ];
  for (let i=0;i<generalCount;i++) out.push({id:`general_${i}`, domain:'general'});
  const coreIds=['stonks_data_plane','stonks_event_router','stonks_ai_gate','stonks_self_test'];
  coreIds.forEach(id=>out.push({id,domain:'finance'}));
  for (let i=0;i<financeOuterCount;i++) out.push({id:`stonks_outer_${i}`, domain:'finance'});
  return out;
}

const base = sandbox.window.zoLayout(agents(6,8));
const moreFinance = sandbox.window.zoLayout(agents(6,16));
const moreGeneral = sandbox.window.zoLayout(agents(14,8));

assert(moreFinance.finance.rx > base.finance.rx, 'La esfera Finance debe crecer al añadir agentes');
assert(moreFinance.width > base.width, 'El lienzo debe crecer cuando Finance necesita más espacio');
assert(moreGeneral.general.rx > base.general.rx, 'La esfera Core debe crecer al añadir agentes generales');
assert(moreGeneral.width > base.width, 'El lienzo debe crecer cuando Core necesita más espacio');

console.log('Adaptive orchestration layout: PASS');
console.log({
  base: { width: base.width, generalRx: base.general.rx, financeRx: base.finance.rx },
  moreFinance: { width: moreFinance.width, financeRx: moreFinance.finance.rx },
  moreGeneral: { width: moreGeneral.width, generalRx: moreGeneral.general.rx },
});
