import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const src=readFileSync(new URL('../../manager/web_app.py',import.meta.url),'utf8');
assert(src.includes('class="profile-avatar" title="Cambiar foto" aria-label="Cambiar foto de perfil" role="button" tabindex="0"'));
const start=src.indexOf('  document.querySelector(".profile-avatar").addEventListener("keydown"');
const end=src.indexOf('  async function loadAccountProfile(){',start);
assert(start>0&&end>start);
let handler, clicks=0;
const ctx={document:{querySelector:()=>({addEventListener:(name,fn)=>{assert.equal(name,'keydown');handler=fn;}})},byId:id=>{assert.equal(id,'profile-avatar-file');return{click:()=>clicks++}}};
runInNewContext(src.slice(start,end),ctx,{timeout:1000});
for(const key of ['Enter',' ']){let prevented=false;handler({key,preventDefault:()=>{prevented=true}});assert(prevented)}
handler({key:'Tab',preventDefault:()=>{throw Error('Tab must not be intercepted')}});
assert.equal(clicks,2);
console.log('ACCOUNT AVATAR ACCESSIBLE BY ENTER AND SPACE, TAB UNCHANGED OK');
