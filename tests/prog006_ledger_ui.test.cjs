'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
class Element {
 constructor(){this.children=[];this.hidden=false;this.disabled=false;this.textContent='';this.value='';this.open=false;this.dataset={};}
 append(...children){this.children.push(...children)}
 replaceChildren(...children){this.children=[...children]}
 get childElementCount(){return this.children.length}
 querySelectorAll(){return []}
 addEventListener(type,cb){this['on'+type]=cb}
}
function report(i){return {event_id:'test-run-'+i.toString(16).padStart(24,'0'),recorded_at:'2026-10-09T18:00:00Z',result:'passed',report_sha256:'a'.repeat(64),integrity:'ok'}}
function setup(){
 const nodes=new Map(), requests=[];
 const element=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id)};
 const initial=Array.from({length:10},(_,i)=>report(30-i));
 const data={tasks:[],runner_status:null,runner_history:[],runner_alert:null,evidence_ledger:initial,evidence_ledger_count:22,evidence_ledger_integrity:{ok:22},percentage:0,verified:0,total:77};
 let poll;
 const context={document:{getElementById:element,createElement:()=>new Element(),visibilityState:'visible'},fetch:async url=>{requests.push(url);if(url.includes('/ledger?'))return {ok:true,json:async()=>({items:[report(20),report(19)],next_cursor:null})};if(url.endsWith('/plan'))return {ok:true,json:async()=>({markdown:'test'})};return {ok:true,json:async()=>data}},setInterval:cb=>{poll=cb},console};
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
 assert.equal(ui.element('ledger-history').childElementCount,12);
 assert.equal(ui.element('ledger-more').hidden,true);
 assert.equal(ui.element('ledger-count').textContent,'23');
 assert.equal(ui.requests.filter(x=>x.includes('/ledger?')).length,1);
});
