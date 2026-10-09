"use strict";
let tasks=[],selected=null,ledgerCursor=null,ledgerBusy=false,ledgerExpanded=false;
const $=id=>document.getElementById(id);
const labels={pending:"Pendiente",in_development:"En desarrollo",in_testing:"En pruebas",blocked:"Bloqueado",verified:"Verificado"};
const docLabels={pending:"Pendiente",in_review:"En revisión",verified:"Verificada",not_applicable:"No aplica"};
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
function render(){
 const root=$("tasks"),query=$("search").value.trim().toLowerCase(),filter=$("state-filter").value;
 const expanded=new Set([...root.querySelectorAll("details.phase[open]")].map(x=>x.dataset.phase));
 root.replaceChildren();
 const phases=new Map();
 for(const t of tasks){if(!phases.has(t.phase))phases.set(t.phase,[]);phases.get(t.phase).push(t)}
 let count=0;
 for(const [phase,all] of phases){
  const shown=all.filter(t=>(!filter||t.state===filter)&&(!query||(t.task_id+" "+t.title+" "+t.phase).toLowerCase().includes(query)));
  if(!shown.length)continue;count+=shown.length;
  const details=node("details",undefined,"phase");details.dataset.phase=phase;details.open=Boolean(query||filter||expanded.has(phase));
  const summary=node("summary"),title=node("span",phase.replace(/^\d+\s+/,""),"phase-title");
  const completed=all.filter(t=>t.state==="verified").length;
  const developing=all.filter(t=>t.state==="in_development").length;
  const testing=all.filter(t=>t.state==="in_testing").length;
  const counts=node("span",undefined,"phase-summary-counts");
  if(developing)counts.append(node("span",developing+" desarrollo","working"));
  if(testing)counts.append(node("span",testing+" pruebas","testing"));
  counts.append(node("span",completed+"/"+all.length+" verificadas"));
  const meter=node("span",undefined,"phase-meter"),fill=node("span");fill.style.width=(completed/all.length*100)+"%";meter.append(fill);
  summary.append(title,counts,meter);details.append(summary);
  for(const t of shown){
   const row=node("div",undefined,"task"),info=node("div",undefined,"task-main");
   const title=node("strong",t.task_id+" · "+(t.title.startsWith(t.task_id+" — pendiente")?"Por especificar":t.title));
   const meta=node("small","Documentación: "+docLabels[t.doc_state]+" · "+t.evidence.length+" evidencias");
   info.append(title,meta);
   const detail=node("details",undefined,"task-spec"),head=node("summary","Ver alcance y criterios"),desc=node("p",t.description||"Especificación pendiente");
   detail.append(head,desc);
   if(t.acceptance_criteria){const criteria=node("ul");for(const criterion of t.acceptance_criteria)criteria.append(node("li",criterion));detail.append(criteria)}
   info.append(detail);
   if(t.evidence&&t.evidence.length){
    const evidence=node("details",undefined,"task-evidence"),heading=node("summary",t.evidence.length+" evidencias registradas"),items=node("ul");
    for(const ref of t.evidence)items.append(node("li",ref));
    evidence.append(heading,items);info.append(evidence)
   }
   if(t.last_event){
    const eventDate=new Date(t.last_event.recorded_at),when=Number.isNaN(eventDate.getTime())?"":eventDate.toLocaleString("es-PE");
    info.append(node("small","Último evento: "+t.last_event.source+(when?" · "+when:""),"task-updated"))
   }
   if(t.updated_at){
    const updated=new Date(t.updated_at);
    if(!Number.isNaN(updated.getTime()))info.append(node("small","Última actualización: "+updated.toLocaleString("es-PE"),"task-updated"))
   }
   const state=node("span",labels[t.state],"status "+t.state);
   const btn=node("button","Editar","edit");btn.type="button";btn.addEventListener("click",()=>edit(t));
   row.append(info,state,btn);details.append(row)
  }
  root.append(details)
 }
 $("visible-count").textContent=count+" tareas visibles en "+root.childElementCount+" fases";
 if(!count)root.append(node("p","No hay tareas para esos filtros.","empty"))
}
function setData(data){
 tasks=data.tasks;
 const run=data.runner_status;
 const descriptions={passed:"Pruebas aprobadas y evento registrado",skipped_unchanged:"Sin cambios; ejecución omitida",tests_failed:"Pruebas fallidas",source_changed:"Código modificado durante las pruebas",record_failed:"No se pudo registrar el evento",runner_failed:"Error interno del automatizador",running:"Pruebas en ejecución; esperando resultado",interrupted:"Ejecución anterior interrumpida"};
 const date=run?.last_run?new Date(run.last_run):null;
 $("runner-status").textContent=run?((descriptions[run.result]||"Estado desconocido")+(date&&!Number.isNaN(date.getTime())?" · "+date.toLocaleString("es-PE"):"")):"Sin ejecución registrada en el monitor";
 const alert=$("runner-alert"),alerts={running:"Pruebas en curso; todavía no existe resultado final.",failed:"Atención: la última ejecución falló. Revisar el registro del servicio.",stale:"Atención: ejecución incompleta o sin resultado reciente válido.",missing:"Atención: no se encontró estado del automatizador."};
 alert.hidden=!data.runner_alert;
 alert.textContent=alerts[data.runner_alert]||"";
 const history=$("runner-history");history.replaceChildren();
 for(const entry of (data.runner_history||[])){
  const at=new Date(entry.last_run),when=Number.isNaN(at.getTime())?"Fecha desconocida":at.toLocaleString("es-PE");
  history.append(node("li",when+" · "+(descriptions[entry.result]||"Estado desconocido")));
 }
 if(!history.childElementCount)history.append(node("li","Aún no hay registros históricos"));
 const ledger=$("ledger-history");
 if(!ledgerExpanded)ledger.replaceChildren();
 $("ledger-count").textContent=String(data.evidence_ledger_count??0);
 const integrity=data.evidence_ledger_integrity||{};
 const issues=(integrity.missing||0)+(integrity.mismatch||0)+(integrity.invalid||0)+(integrity.unavailable||0);
 $("ledger-integrity").textContent=(integrity.ok||0)+" evidencias íntegras · "+issues+" con incidencias (faltantes, alteradas o inaccesibles)";
 for(const entry of (ledgerExpanded?[]:(data.evidence_ledger||[]))){
  const at=new Date(entry.recorded_at),when=Number.isNaN(at.getTime())?"Fecha desconocida":at.toLocaleString("es-PE");
  const integrity={ok:"Integridad verificada",missing:"Informe no encontrado",mismatch:"Integridad alterada",invalid:"Referencia inválida",unavailable:"Informe inaccesible"}[entry.integrity]||"No comprobado";
  ledger.append(node("li",when+" · "+entry.event_id+" · "+entry.result+" · SHA256 "+entry.report_sha256.slice(0,16)+"… · "+integrity));
 }
 if(!ledger.childElementCount)ledger.append(node("li","Aún no hay evidencias registradas"));
 if(!ledgerExpanded){
  ledgerCursor=(data.evidence_ledger_count||0)>10&&data.evidence_ledger?.length===10?data.evidence_ledger[9].event_id:null;
  $("ledger-more").hidden=!ledgerCursor;
  $("ledger-error").textContent="";
 }
 $("percent").textContent=(data.percentage??0)+"%";
 $("developing").textContent=data.tasks.filter(t=>t.state==="in_development").length;
 $("testing").textContent=data.tasks.filter(t=>t.state==="in_testing").length;
 $("verified-total").textContent=data.verified+" / "+data.total;
 $("bar").value=data.percentage||0;
 if(data.plan)$("plan-version").textContent="Documento versionado · SHA256 "+data.plan.sha256.slice(0,12)+"…";
 render()
}
async function loadOlderLedger(){
 if(!ledgerCursor||ledgerBusy)return;
 ledgerBusy=true;$("ledger-more").disabled=true;
 try{
  const r=await fetch("/manager/api/progress/ledger?before="+encodeURIComponent(ledgerCursor),{credentials:"same-origin",cache:"no-store"});
  if(!r.ok)throw new Error(r.status===401||r.status===403?"Acceso denegado o sesión caducada":"No se pudo consultar el historial");
  const page=await r.json();
  for(const entry of page.items){
   const at=new Date(entry.recorded_at),when=Number.isNaN(at.getTime())?"Fecha desconocida":at.toLocaleString("es-PE");
   const labels={ok:"Integridad verificada",missing:"Informe no encontrado",mismatch:"Integridad alterada",invalid:"Referencia inválida",unavailable:"Informe inaccesible"};
   $("ledger-history").append(node("li",when+" · "+entry.event_id+" · "+entry.result+" · SHA256 "+entry.report_sha256.slice(0,16)+"… · "+(labels[entry.integrity]||"No comprobado")));
  }
  ledgerExpanded=true;
  ledgerCursor=page.next_cursor;$("ledger-more").hidden=!ledgerCursor;
  $("ledger-error").textContent="";
 }catch(e){$("ledger-error").textContent=e.message||"Error de consulta"}
 finally{ledgerBusy=false;$("ledger-more").disabled=false}
}
$("ledger-more").addEventListener("click",loadOlderLedger);
async function load(){
 try{
  const r=await fetch("/manager/api/progress",{credentials:"same-origin",cache:"no-store"});
  if(!r.ok)throw Error("No se pudieron cargar las tareas ("+r.status+")");
  setData(await r.json());
  const p=await fetch("/manager/api/progress/plan",{credentials:"same-origin",cache:"no-store"});
  if(p.ok){const source=await p.json();$("plan-content").textContent=source.markdown}
 }catch(e){$("message").textContent=e.message}
}
function edit(t){
 selected=t;$("edit-title").textContent=t.title;$("edit-id").textContent=t.task_id;
 $("edit-state").value=t.state;$("edit-doc").value=t.doc_state;
 $("edit-evidence").value=t.evidence.join("\n");$("edit-error").textContent="";
 $("editor").showModal()
}
$("cancel").onclick=()=>$("editor").close();
$("search").oninput=render;$("state-filter").onchange=render;
$("edit-form").onsubmit=async e=>{
 e.preventDefault();if(!selected)return;
 const payload={task_id:selected.task_id,state:$("edit-state").value,doc_state:$("edit-doc").value,evidence:$("edit-evidence").value.split("\n").map(s=>s.trim()).filter(Boolean)};
 try{
  const r=await fetch("/manager/api/progress",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-Requested-With":"TraccarManager"},body:JSON.stringify(payload)});
  const data=await r.json();if(!r.ok)throw Error(data.error||"No se pudo guardar");
  setData(data);$("editor").close();$("message").textContent="Cambio guardado correctamente."
 }catch(err){$("edit-error").textContent=err.message}
};
load();
let polling=false;
setInterval(async()=>{if(document.visibilityState!=="visible"||polling||$("editor").open)return;polling=true;try{const r=await fetch("/manager/api/progress",{credentials:"same-origin",cache:"no-store"});if(r.ok)setData(await r.json());else if(r.status===401)$("message").textContent="Sesión caducada. Vuelve al panel e inicia sesión."}catch(_e){}finally{polling=false}},15000);
