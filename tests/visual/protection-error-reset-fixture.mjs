import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const src=readFileSync(new URL('../../manager/web_app.py',import.meta.url),'utf8');
const start=src.indexOf('  async function loadServerStatus(){');
const end=src.indexOf('  async function loadBoundaryHealth()',start);
assert(start>0&&end>start);
const block=src.slice(start,end),catchStart=block.lastIndexOf('} catch(_e)');
assert(catchStart>0);
for(const fragment of ['journalProtection.textContent="Journal: sin evidencia reciente"','binlogProtection.textContent="Binlogs MySQL: sin evidencia reciente"','journalMeter.firstElementChild.style.width="0%"','binlogMeter.firstElementChild.style.width="0%"','journalMeterValue.textContent="—"','binlogMeterValue.textContent="—"','storageProtectionTime.textContent="Última verificación: sin evidencia confirmada"']){
 assert(block.slice(catchStart).includes(fragment),`Missing error reset ${fragment}`);
 assert(block.slice(0,catchStart).includes(fragment),`Missing partial-evidence reset ${fragment}`);
}
console.log('SERVER STORAGE PROTECTION ERROR AND PARTIAL-EVIDENCE RESETS OK');
