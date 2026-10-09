import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const src=readFileSync(new URL('../../manager/web_app.py',import.meta.url),'utf8');
const start=src.indexOf('  byId("profile-avatar-file").addEventListener("change"');
const end=src.indexOf('  byId("password-save").addEventListener(',start);
assert(start>0&&end>start);
const els=Object.fromEntries(['profile-avatar-file','profile-avatar-img','profile-avatar-letter','profile-status'].map(id=>[id,{textContent:'',addEventListener(_event,fn){this.listener=fn}}]));
let created=0,requests=0;
const ctx={byId:id=>els[id],URL:{createObjectURL:()=>{created++;return 'blob:test'},revokeObjectURL:()=>{}},FileReader:class{readAsDataURL(){this.result='data:image/png;base64,YQ==';this.onload()}},fetch:async()=>{requests++;return{ok:true}},api:x=>x,loadAccountProfile:async()=>{}};
runInNewContext(src.slice(start,end),ctx,{timeout:1000});
for(const type of ['text/html','image/svg+xml','application/octet-stream','']){
 await els['profile-avatar-file'].listener({target:{files:[{size:100,type}]}});
 assert.match(els['profile-status'].textContent,/PNG, JPG o WebP/);
}
assert.equal(created,0);assert.equal(requests,0);
for(const type of ['image/png','image/jpeg','image/webp'])await els['profile-avatar-file'].listener({target:{files:[{size:100,type}]}});
assert.equal(created,3);assert.equal(requests,3);
console.log('AVATAR FILE TYPE REJECTED BEFORE PREVIEW OR NETWORK REQUEST OK');
