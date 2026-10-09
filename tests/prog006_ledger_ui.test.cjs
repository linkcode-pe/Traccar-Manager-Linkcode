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
function setup(ledgerFetch){
 const nodes=new Map(), requests=[];
 const element=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id)};
 const initial=Array.from({length:10},(_,i)=>report(30-i));
 const data={tasks:[],runner_status:null,runner_history:[],runner_alert:null,evidence_ledger:initial,evidence_ledger_count:22,evidence_ledger_integrity:{ok:22},percentage:0,verified:0,total:77};
 let poll;
 const context={document:{getElementById:element,createElement:()=>new Element(),visibilityState:'visible'},fetch:async url=>{requests.push(url);if(url.includes('/ledger?'))return ledgerFetch?ledgerFetch(url):{ok:true,json:async()=>({items:[report(20),report(19)],next_cursor:null})};if(url.endsWith('/plan'))return {ok:true,json:async()=>({markdown:'test'})};return {ok:true,json:async()=>data}},setInterval:cb=>{poll=cb},console};
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
