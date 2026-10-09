"use strict";
let tasks=[],selected=null;
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
  const counts=node("span",completed+"/"+all.length,"phase-count");
  const meter=node("span",undefined,"phase-meter"),fill=node("span");fill.style.width=(completed/all.length*100)+"%";meter.append(fill);
  summary.append(title,counts,meter);details.append(summary);
  for(const t of shown){
   const row=node("div",undefined,"task"),info=node("div",undefined,"task-main");
   const title=node("strong",t.task_id+" · "+(t.title.startsWith(t.task_id+" — pendiente")?"Por especificar":t.title));
   const meta=node("small","Documentación: "+docLabels[t.doc_state]+" · "+t.evidence.length+" evidencias");
   info.append(title,meta);
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
 $("percent").textContent=(data.percentage??0)+"%";
 $("verified").textContent=data.verified;
 $("total").textContent=data.total;
 $("bar").value=data.percentage||0;
 if(data.plan)$("plan-version").textContent="Documento versionado · SHA256 "+data.plan.sha256.slice(0,12)+"…";
 render()
}
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
