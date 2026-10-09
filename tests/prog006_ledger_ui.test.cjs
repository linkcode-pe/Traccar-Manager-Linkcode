'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
class Element {
 constructor(){this.children=[];this.hidden=false;this.disabled=false;this.textContent='';this.value='';this.open=false;this.dataset={};}
 append(...children){this.children.push(...children)}
 prepend(...children){this.children.unshift(...children)}
 replaceChildren(...children){this.children=[...children]}
 get childElementCount(){return this.children.length}
 querySelectorAll(){return []}
 addEventListener(type,cb){this['on'+type]=cb}
}
function report(i){return {event_id:'test-run-'+i.toString(16).padStart(24,'0'),recorded_at:'2026-10-09T18:00:00Z',result:'passed',report_sha256:'a'.repeat(64),integrity:'ok'}}
function setup(ledgerFetch,recoveryFetch){
 const nodes=new Map(), requests=[];
 const element=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id)};
 const initial=Array.from({length:10},(_,i)=>report(30-i));
 const data={tasks:[],runner_status:null,runner_history:[],runner_alert:null,evidence_ledger:initial,evidence_ledger_count:22,evidence_ledger_integrity:{ok:22},percentage:0,verified:0,total:77};
 let poll;
 const context={document:{getElementById:element,createElement:()=>new Element(),visibilityState:'visible'},fetch:async url=>{requests.push(url);if((url==='/manager/api/progress/ledger'||(recoveryFetch&&url.includes('/ledger?')&&url.includes('before=test-run-000000000000000000000024')))&&recoveryFetch)return recoveryFetch(url);if(url.includes('/ledger?'))return ledgerFetch?ledgerFetch(url):{ok:true,json:async()=>({items:[report(20),report(19)],next_cursor:null})};if(url.endsWith('/plan'))return {ok:true,json:async()=>({markdown:'test'})};return {ok:true,json:async()=>data}},setInterval:cb=>{poll=cb},console};
 vm.createContext(context);vm.runInContext(fs.readFileSync('manager/progress_client.js','utf8'),context);
 return {element,requests,data,poll:()=>poll(),refresh:()=>vm.runInContext('setData('+JSON.stringify(data)+')',context)};
}
test('paginates and preserves older entries during refresh',async()=>{
 const ui=setup();await new Promise(setImmediate);
 assert.equal(ui.element('ledger-history').childElementCount,10);
 assert.equal(ui.element('ledger-more').hidden,false);
 await ui.element('ledger-more').onclick();
 assert.equal(ui.element('ledger-history').childElementCount,12);
 assert.equal(ui.element('ledger-more').hidden,true);
 ui.data.evidence_ledger=[report(31),...ui.data.evidence_ledger.slice(0,9)];ui.data.evidence_ledger_count=23;
 await ui.poll();
 assert.equal(ui.element('ledger-history').childElementCount,13);
 assert.match(ui.element('ledger-history').children[0].textContent,/test-run-00000000000000000000001f/);
 assert.equal(ui.element('ledger-more').hidden,true);
 assert.equal(ui.element('ledger-count').textContent,'23');
 assert.equal(ui.requests.filter(x=>x.includes('/ledger?')).length,1);
});

test('denied session keeps current entries and allows retry',async()=>{
 let attempts=0;
 const ui=setup(async()=>{attempts++;return attempts===1?{ok:false,status:401}:{ok:true,json:async()=>({items:[report(20)],next_cursor:null})}});
 await new Promise(setImmediate);
 await ui.element('ledger-more').onclick();
 assert.equal(ui.element('ledger-history').childElementCount,10);
 assert.match(ui.element('ledger-error').textContent,/sesión caducada/);
 assert.equal(ui.element('ledger-more').disabled,false);
 await ui.element('ledger-more').onclick();
 assert.equal(ui.element('ledger-history').childElementCount,11);
 assert.equal(ui.element('ledger-error').textContent,'');
 assert.equal(attempts,2);
});
test('network failure does not discard history',async()=>{
 const ui=setup(async()=>{throw new Error('Network offline')});
 await new Promise(setImmediate);
 await ui.element('ledger-more').onclick();
 assert.equal(ui.element('ledger-history').childElementCount,10);
 assert.match(ui.element('ledger-error').textContent,/Network offline/);
 assert.equal(ui.element('ledger-more').hidden,false);
 assert.equal(ui.element('ledger-more').disabled,false);
});
test('repeated clicks during pending request make one call',async()=>{
 let resolveRequest, calls=0;
 const ui=setup(async()=>{calls++;return await new Promise(resolve=>{resolveRequest=resolve})});
 await new Promise(setImmediate);
 const a=ui.element('ledger-more').onclick();
 const b=ui.element('ledger-more').onclick();
 assert.equal(calls,1);
 assert.equal(ui.element('ledger-more').disabled,true);
 resolveRequest({ok:true,json:async()=>({items:[report(20)],next_cursor:null})});
 await Promise.all([a,b]);
 assert.equal(ui.element('ledger-history').childElementCount,11);
 assert.equal(ui.element('ledger-more').disabled,false);
});

test('invalid or incomplete server pages never partially append records',async()=>{
 const cases=[null,{}, {items:null,next_cursor:null},
  {items:[report(20),{event_id:'bad'}],next_cursor:null},
  {items:[report(20)],next_cursor:'invalid'},
  {items:[],next_cursor:report(19).event_id},
  {items:[report(20)],next_cursor:report(21).event_id},
  {items:[report(30)],next_cursor:null},
  {items:[report(20),report(20)],next_cursor:null},
  {items:[report(20)],next_cursor:report(19).event_id},
  {items:Array.from({length:26},(_,i)=>report(i)),next_cursor:null}];
 for(const page of cases){
  const ui=setup(async()=>({ok:true,json:async()=>page}));
  await new Promise(setImmediate);
  await ui.element('ledger-more').onclick();
  assert.equal(ui.element('ledger-history').childElementCount,10,JSON.stringify(page));
  assert.match(ui.element('ledger-error').textContent,/Respuesta del historial inválida/);
  assert.equal(ui.element('ledger-more').hidden,false);
  assert.equal(ui.element('ledger-more').disabled,false);
 }
});

test('new records remain unique across successive polls',async()=>{
 const ui=setup();await new Promise(setImmediate);
 await ui.element('ledger-more').onclick();
 ui.data.evidence_ledger=[report(31),...ui.data.evidence_ledger.slice(0,9)];
 await ui.poll();await ui.poll();
 assert.equal(ui.element('ledger-history').childElementCount,13);
 ui.data.evidence_ledger=[report(32),...ui.data.evidence_ledger.slice(0,9)];
 await ui.poll();
 assert.equal(ui.element('ledger-history').childElementCount,14);
 assert.match(ui.element('ledger-history').children[0].textContent,/test-run-000000000000000000000020/);
});

test('poll updates integrity labels in place without reordering or duplicating',async()=>{
 const ui=setup();await new Promise(setImmediate);
 await ui.element('ledger-more').onclick();
 const before=ui.element('ledger-history').children.slice();
 ui.data.evidence_ledger[0]={...ui.data.evidence_ledger[0],integrity:'mismatch'};
 await ui.poll();
 assert.equal(ui.element('ledger-history').childElementCount,12);
 assert.equal(ui.element('ledger-history').children[0],before[0]);
 assert.match(before[0].textContent,/Integridad alterada/);
 assert.equal(ui.element('ledger-history').children[11],before[11]);
 ui.data.evidence_ledger=[report(31),...ui.data.evidence_ledger.slice(0,9)];
 await ui.poll();
 assert.equal(ui.element('ledger-history').childElementCount,13);
 assert.match(ui.element('ledger-history').children[0].textContent,/test-run-00000000000000000000001f/);
 assert.equal(ui.element('ledger-history').children[1],before[0]);
});

test('more than ten new records trigger a gap warning without corrupting old pages',async()=>{
 const ui=setup();await new Promise(setImmediate);
 await ui.element('ledger-more').onclick();
 const original=ui.element('ledger-history').children.slice();
 ui.data.evidence_ledger=Array.from({length:10},(_,i)=>report(45-i));
 ui.data.evidence_ledger_count=37;
 await ui.poll();
 assert.equal(ui.element('ledger-history').childElementCount,12);
 assert.deepEqual(ui.element('ledger-history').children,original);
 await new Promise(setImmediate);
 assert.match(ui.element('ledger-error').textContent,/Actualiza la página/);
});
test('count gap prevents partial insertion even when an older ID overlaps',async()=>{
 const ui=setup();await new Promise(setImmediate);
 await ui.element('ledger-more').onclick();
 ui.data.evidence_ledger=[report(34),report(33),report(30),...ui.data.evidence_ledger.slice(1,8)];
 ui.data.evidence_ledger_count=30;
 await ui.poll();
 assert.equal(ui.element('ledger-history').childElementCount,12);
 await new Promise(setImmediate);
 assert.match(ui.element('ledger-error').textContent,/Actualiza la página/);
});

test('automatically recovers missing evidence pages without replacing old rows',async()=>{
 const ui=setup(async()=>({ok:true,json:async()=>({items:[report(20),report(19)],next_cursor:null})}),
  async()=>({ok:true,json:async()=>({items:[report(34),report(33),report(32),report(31),report(30)],next_cursor:null})}));
 await new Promise(setImmediate);
 await ui.element('ledger-more').onclick();
 const old=ui.element('ledger-history').children[0];
 ui.data.evidence_ledger=[report(34),report(33),report(30),...ui.data.evidence_ledger.slice(1,8)];
 ui.data.evidence_ledger_count=26;
 await ui.poll();await new Promise(setImmediate);
 assert.equal(ui.element('ledger-error').textContent,'');
 assert.equal(ui.element('ledger-history').childElementCount,16);
 assert.equal(ui.element('ledger-history').children[4],old);
});

test('recovery spans two pages and keeps older rows intact',async()=>{
 const urls=[];
 const ui=setup(undefined,async url=>{
  urls.push(url);
  const items=url.includes('?before=')?[report(35),report(34),report(33),report(32),report(31),report(30)]:[report(45),report(44),report(43),report(42),report(41),report(40),report(39),report(38),report(37),report(36)];
  return {ok:true,json:async()=>({items,next_cursor:url.includes('?before=')?null:report(36).event_id})};
 });
 await new Promise(setImmediate);await ui.element('ledger-more').onclick();
 const old=ui.element('ledger-history').children[0];
 ui.data.evidence_ledger=Array.from({length:10},(_,i)=>report(45-i));ui.data.evidence_ledger_count=37;
 await ui.poll();await new Promise(setImmediate);
 assert.equal(urls.length,2);
 assert.equal(ui.element('ledger-history').childElementCount,27);
 assert.equal(ui.element('ledger-history').children[15],old);
 assert.equal(ui.element('ledger-error').textContent,'');
});
test('recovery network failure is atomic and allows another poll to retry',async()=>{
 let attempts=0;
 const ui=setup(undefined,async()=>{attempts++;throw Error('Connection lost')});
 await new Promise(setImmediate);await ui.element('ledger-more').onclick();
 ui.data.evidence_ledger=Array.from({length:10},(_,i)=>report(45-i));ui.data.evidence_ledger_count=37;
 await ui.poll();await new Promise(setImmediate);
 assert.equal(ui.element('ledger-history').childElementCount,12);
 assert.match(ui.element('ledger-error').textContent,/Connection lost/);
 await ui.poll();await new Promise(setImmediate);
 assert.equal(attempts,2);
});
test('concurrent polls do not duplicate recovery requests',async()=>{
 let resolvePage,calls=0;
 const ui=setup(undefined,async()=>{calls++;return new Promise(resolve=>{resolvePage=resolve})});
 await new Promise(setImmediate);await ui.element('ledger-more').onclick();
 ui.data.evidence_ledger=Array.from({length:10},(_,i)=>report(45-i));ui.data.evidence_ledger_count=37;
 await ui.poll();await ui.poll();
 assert.equal(calls,1);
 resolvePage({ok:true,json:async()=>({items:[...Array.from({length:15},(_,i)=>report(45-i))],next_cursor:null})});
 await new Promise(setImmediate);
 assert.match(ui.element('ledger-error').textContent,/Respuesta inválida/);
 assert.equal(ui.element('ledger-history').childElementCount,12);
});

test('recovery rejects reversed evidence order atomically',async()=>{
 const ui=setup(undefined,async()=>({ok:true,json:async()=>({items:[report(33),report(34),report(30)],next_cursor:null})}));
 await new Promise(setImmediate);await ui.element('ledger-more').onclick();
 ui.data.evidence_ledger=[report(34),report(33),report(30),...ui.data.evidence_ledger.slice(1,8)];
 ui.data.evidence_ledger_count=26;
 await ui.poll();await new Promise(setImmediate);
 assert.equal(ui.element('ledger-history').childElementCount,12);
 assert.match(ui.element('ledger-error').textContent,/Orden inválido/);
});
test('recovery rejects duplicate IDs across page boundaries atomically',async()=>{
 const ui=setup(undefined,async url=>({ok:true,json:async()=>url.includes('?before=')?
  {items:[report(36),report(30)],next_cursor:null}:
  {items:Array.from({length:10},(_,i)=>report(45-i)),next_cursor:report(36).event_id}}));
 await new Promise(setImmediate);await ui.element('ledger-more').onclick();
 ui.data.evidence_ledger=Array.from({length:10},(_,i)=>report(45-i));ui.data.evidence_ledger_count=37;
 await ui.poll();await new Promise(setImmediate);
 assert.equal(ui.element('ledger-history').childElementCount,12);
 assert.match(ui.element('ledger-error').textContent,/Orden inválido|repetidas/);
});

test('recovery refuses stale result when another poll advances the visible head',async()=>{
 let resolveRecovery;
 const ui=setup(undefined,async()=>new Promise(resolve=>{resolveRecovery=resolve}));
 await new Promise(setImmediate);await ui.element('ledger-more').onclick();
 ui.data.evidence_ledger=Array.from({length:10},(_,i)=>report(45-i));ui.data.evidence_ledger_count=37;
 await ui.poll();
 // An overlapping snapshot can add a newer head before the old recovery finishes.
 ui.data.evidence_ledger=[report(32),...Array.from({length:9},(_,i)=>report(30-i))];
 ui.data.evidence_ledger_count=23;
 await ui.poll();
 assert.equal(ui.element('ledger-history').childElementCount,13);
 resolveRecovery({ok:true,json:async()=>({items:[report(31),report(30)],next_cursor:null})});
 await new Promise(setImmediate);
 assert.equal(ui.element('ledger-history').childElementCount,13);
 assert.match(ui.element('ledger-error').textContent,/historial cambió/);
});
