import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const src=readFileSync(new URL('../../manager/web_app.py',import.meta.url),'utf8');
const start=src.indexOf('  byId("profile-avatar-file").addEventListener("change"');
const end=src.indexOf('  byId("password-save").addEventListener(',start);
assert(start>0&&end>start);
for(const mode of ['success','rejected','offline']){
 const els=Object.fromEntries(['profile-avatar-file','profile-avatar-img','profile-avatar-letter','profile-status'].map(id=>[id,{hidden:false,textContent:'',addEventListener(_event,fn){this.listener=fn}}]));
 const revoked=[];let reloads=0;
 const ctx={byId:id=>els[id],URL:{createObjectURL:()=> 'blob:preview',revokeObjectURL:url=>revoked.push(url)},api:x=>x,FileReader:class{readAsDataURL(){this.result='data:image/png;base64,YQ==';this.onload()}},fetch:async()=>{if(mode==='offline')throw Error('offline');return{ok:mode==='success'}},loadAccountProfile:async()=>{reloads++;els['profile-avatar-img'].onload=null;els['profile-avatar-img'].onerror=null}};
 runInNewContext(src.slice(start,end),ctx,{timeout:1000});
 await els['profile-avatar-file'].listener({target:{files:[{size:123,type:'image/png'}]}});
 assert.deepEqual(revoked,['blob:preview'],`${mode} did not release preview before profile refresh`);
 assert.equal(reloads,1);
}
console.log('AVATAR PREVIEW RELEASED BEFORE SUCCESS, HTTP ERROR AND NETWORK REFRESH OK');
