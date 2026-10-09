"""PROG-001 persistent progress checklist, independent of official Traccar."""
import json
import os
import re
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from manager.progress_catalog import FUNCTIONAL_GROUPS

ROLE = "development.progress.manage"
DB_PATH = Path(os.environ.get("TRACCAR_MANAGER_PROGRESS_DB", "/var/lib/traccar-manager-progress/progress.sqlite3"))
PLAN_PATH = Path(__file__).resolve().parent.parent / "docs/plan-maestro/PLAN_MAESTRO_TRACCAR_MANAGER_ACTUALIZADO.md"
STATES = ("pending", "in_development", "in_testing", "blocked", "verified")
DOC_STATES = ("pending", "in_review", "verified", "not_applicable")
GROUPS = {
    **{phase: [task_id for task_id, _ in items] for phase, items in FUNCTIONAL_GROUPS.items()},
    "0 Auditoría": ["AUD-001","AUD-002","AUD-003","AUD-004"],
    "1 Seguridad y continuidad": [*(f"SEC-{i:03}" for i in range(1,10)),*(f"BCP-{i:03}" for i in range(1,4))],
    "2 Centro de progreso": [*(f"PROG-{i:03}" for i in range(1,7)),"DOC-001"],
    "3 Administración y operaciones": ["ADM-001","ADM-002","OPS-001","OPS-002","OPS-003"],
    "4 Integraciones": ["TEO-001","COM-001","COM-002","COM-003"],
}
TITLES = {task_id: title for items in FUNCTIONAL_GROUPS.values() for task_id, title in items}
TITLES.update({
 'AUD-001':'Inventario técnico y línea base del sistema',
 'AUD-002':'Hallazgos y riesgos de seguridad',
 'AUD-003':'Matriz de permisos y dependencias',
 'AUD-004':'Informe de auditoría y aceptación',
 'SEC-001':'Autenticación de usuarios administrativos',
 'SEC-002':'Autorización de rutas y permisos',
 'SEC-003':'Seguridad de sesiones y cookies',
 'SEC-004':'Protección frente a solicitudes no autorizadas',
 'SEC-005':'Validación de entradas y errores',
 'SEC-006':'Gestión segura de credenciales',
 'SEC-007':'Registros de seguridad y alertas',
 'SEC-008':'Pruebas de regresión de seguridad',
 'BCP-001':'Política y cobertura de respaldos',
 'BCP-002':'Procedimiento de restauración',
 'BCP-003':'Simulacro de recuperación y continuidad',
 'ADM-001':'Administración de cuentas y permisos',
 'ADM-002':'Panel de configuración administrativa',
 'OPS-001':'Supervisión de servicios y recursos',
 'OPS-002':'Procedimientos de mantenimiento controlado',
 'OPS-003':'Monitoreo y recuperación operativa',
 'TEO-001':'Integración segura con servicios Traccar oficiales',
 "DOC-001":"Documentación viva obligatoria",
 "PROG-001":"Permiso exclusivo de superadministrador",
 "PROG-002":"Catálogo y persistencia del checklist",
 "PROG-003":"Interfaz web de desarrollo y progreso",
 "PROG-004":"Evidencias, auditoría y progreso verificable",
 "PROG-005":"Pruebas, respaldo y despliegue",
 "PROG-006":"Sincronización automática de avances",
 "COM-001":"Eventos Traccar y destinatarios WhatsApp",
 "COM-002":"Consola administrativa del bot",
 "COM-003":"Mensajería, conversaciones y observabilidad",
 "SEC-009":"Revocación segura de sesiones",
})
class ProgressError(ValueError):
    pass

def authorized(principal):
    return principal is not None and ROLE in getattr(principal,"roles",())

def connect():
    db=sqlite3.connect(str(DB_PATH),timeout=5)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA busy_timeout=5000")
    return db

def init():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    if DB_PATH.is_symlink():
        raise ProgressError("symlink database forbidden")
    db=connect()
    try:
        with db:
            db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY, phase TEXT NOT NULL, title TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', doc_state TEXT NOT NULL DEFAULT 'pending',
                evidence TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                actor TEXT NOT NULL, old_state TEXT, new_state TEXT NOT NULL,
                changed_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS progress_events (
                event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, source TEXT NOT NULL,
                actor TEXT NOT NULL, state TEXT NOT NULL, recorded_at TEXT NOT NULL)""")
            now=datetime.now(timezone.utc).isoformat()
            for phase, ids in GROUPS.items():
                for task_id in ids:
                    db.execute("INSERT OR IGNORE INTO tasks VALUES (?,?,?,?,?,?,?)",
                      (task_id,phase,TITLES.get(task_id,task_id+" — pendiente de especificación"),
                       "pending","pending","[]",now))
                    if task_id in TITLES:
                        db.execute("UPDATE tasks SET title=?,phase=? WHERE task_id=?",
                                   (TITLES[task_id],phase,task_id))
    finally:
        db.close()

def plan_source():
    content = PLAN_PATH.read_text(encoding="utf-8")
    if len(content) > 200000:
        raise ProgressError("plan too large")
    return {"markdown": content, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(), "source": "docs/plan-maestro/PLAN_MAESTRO_TRACCAR_MANAGER_ACTUALIZADO.md"}

def task_spec(task_id, title, phase):
    """Versioned acceptance guidance; not proof that a capability works."""
    subject=title.lower()
    if task_id.startswith("TRC-"):
        criteria=["Consultar datos mediante la API oficial de Traccar sin modificar su núcleo.",
                  "Respetar permisos y asociaciones cliente-dispositivo en el servidor.",
                  "Probar casos autorizados, acceso denegado y errores de la API con evidencias."]
    elif task_id.startswith("MNT-"):
        criteria=["Presentar diagnóstico y previsualización de impacto antes de cualquier cambio.",
                  "Exigir autorización explícita, límites y auditoría para operaciones destructivas.",
                  "Demostrar pruebas, respaldo y procedimiento de recuperación antes de habilitar ejecución."]
    elif task_id.startswith(("WAP-","COM-")):
        criteria=["Respetar destinatarios autorizados, consentimiento y privacidad.",
                  "Gestionar fallos, reintentos y duplicados sin filtrar credenciales.",
                  "Validar flujo extremo a extremo con pruebas y evidencias verificables."]
    elif task_id.startswith(("SEC-","ADM-","BCP-")):
        criteria=["Definir controles de acceso y límites de operación.",
                  "Probar rutas permitidas y denegadas, fallos y recuperación.",
                  "Documentar resultados y evidencia de revisión de seguridad."]
    else:
        criteria=["Documentar comportamiento esperado, alcance y dependencias.",
                  "Implementar y ejecutar pruebas funcionales y de seguridad aplicables.",
                  "Registrar evidencia, documentación y aceptación antes de verificar."]
    return {"description":"Implementar y validar: "+subject+".",
            "acceptance_criteria":criteria,
            "verification_note":"Pendiente de validación independiente; el catálogo no certifica funcionalidad.",
            "specification_level":"criterios iniciales por módulo"}

def snapshot(principal):
    if not authorized(principal): raise PermissionError("forbidden")
    db=connect()
    try:
        tasks=[]
        last_events={row["task_id"]: {"source":row["source"], "state":row["state"], "recorded_at":row["recorded_at"]}
                     for row in db.execute("SELECT e.task_id,e.source,e.state,e.recorded_at FROM progress_events e JOIN (SELECT task_id,MAX(rowid) AS last_id FROM progress_events GROUP BY task_id) latest ON e.rowid=latest.last_id")}
        for row in db.execute("SELECT * FROM tasks ORDER BY phase,task_id"):
            d=dict(row);d["evidence"]=json.loads(d.pop("evidence"));d["last_event"]=last_events.get(d["task_id"]);d.update(task_spec(d["task_id"],d["title"],d["phase"]));tasks.append(d)
        runner_status = None
        status_path = DB_PATH.parent / "prog006-run-status.json"
        try:
            raw = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw.get("result") in ("passed", "skipped_unchanged", "tests_failed", "source_changed", "record_failed", "runner_failed", "running"):
                runner_status = {k:raw.get(k) for k in ("last_run", "result", "source_sha256")}
        except (OSError, ValueError):
            pass
        runner_history = []
        try:
            history = json.loads((DB_PATH.parent / "prog006-run-history.json").read_text(encoding="utf-8"))
            if isinstance(history, list):
                for item in history[:10]:
                    if isinstance(item, dict) and item.get("result") in ("passed", "skipped_unchanged", "tests_failed", "source_changed", "record_failed", "runner_failed", "running"):
                        runner_history.append({k:item.get(k) for k in ("last_run", "result")})
        except (OSError, ValueError):
            pass
        runner_alert = None
        if runner_status:
            if runner_status["result"] == "running":
                try:
                    started = datetime.fromisoformat(runner_status["last_run"].replace("Z", "+00:00"))
                    runner_alert = "running" if started.tzinfo and 0 <= (datetime.now(timezone.utc) - started).total_seconds() <= 300 else "stale"
                except (TypeError, ValueError, AttributeError):
                    runner_alert = "stale"
            elif runner_status["result"] not in ("passed", "skipped_unchanged"):
                runner_alert = "failed"
            else:
                try:
                    checked = datetime.fromisoformat(runner_status["last_run"].replace("Z", "+00:00"))
                    if checked.tzinfo is None or checked > datetime.now(timezone.utc) or (datetime.now(timezone.utc) - checked).total_seconds() > 36 * 3600:
                        runner_alert = "stale"
                except (TypeError, ValueError, AttributeError):
                    runner_alert = "stale"
        else:
            runner_alert = "missing"
        verified=sum(t["state"]=="verified" for t in tasks)
        return {"tasks":tasks,"runner_status":runner_status,"runner_history":runner_history,"runner_alert":runner_alert,"plan": {k:v for k,v in plan_source().items() if k != "markdown"},"verified":verified,"total":len(tasks),
                "percentage":round(verified*100/len(tasks),2) if tasks else None}
    finally: db.close()

def ingest_event(principal, event):
    """Apply a traceable, idempotent development event, authorized by session."""
    if not authorized(principal): raise PermissionError("forbidden")
    if not isinstance(event,dict) or set(event)!={"event_id","task_id","source","state","doc_state","evidence"}:
        raise ProgressError("invalid event")
    event_id=event["event_id"];source=event["source"]
    if not isinstance(event_id,str) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}",event_id):
        raise ProgressError("invalid event id")
    if not isinstance(source,str) or not re.fullmatch(r"[A-Za-z0-9._/-]{2,64}",source):
        raise ProgressError("invalid event source")
    payload={k:event[k] for k in ("task_id","state","doc_state","evidence")}
    validate_payload(payload)
    db=connect()
    try:
        with db:
            previous=db.execute("SELECT task_id,source,state FROM progress_events WHERE event_id=?",(event_id,)).fetchone()
            if previous:
                if previous["task_id"]!=payload["task_id"] or previous["source"]!=source or previous["state"]!=payload["state"]:
                    raise ProgressError("event id conflict")
                return {"applied":False,"duplicate":True,"event_id":event_id}
            task=db.execute("SELECT state FROM tasks WHERE task_id=?",(payload["task_id"],)).fetchone()
            if task is None:raise ProgressError("unknown task")
            now=datetime.now(timezone.utc).isoformat()
            db.execute("INSERT INTO progress_events VALUES(?,?,?,?,?,?)",
                       (event_id,payload["task_id"],source,principal.subject_id,payload["state"],now))
            db.execute("UPDATE tasks SET state=?,doc_state=?,evidence=?,updated_at=? WHERE task_id=?",
                       (payload["state"],payload["doc_state"],json.dumps(payload["evidence"]),now,payload["task_id"]))
            db.execute("INSERT INTO history(task_id,actor,old_state,new_state,changed_at) VALUES(?,?,?,?,?)",
                       (payload["task_id"],principal.subject_id,task["state"],payload["state"],now))
    finally:db.close()
    return {"applied":True,"duplicate":False,"event_id":event_id}

def validate_payload(payload):
    if not isinstance(payload,dict) or set(payload)!={"task_id","state","doc_state","evidence"}:
        raise ProgressError("invalid payload")
    task_id=payload["task_id"];state=payload["state"];doc=payload["doc_state"];evidence=payload["evidence"]
    if not isinstance(task_id,str) or not re.fullmatch(r"[A-Z]{2,8}-[0-9]{3}",task_id):
        raise ProgressError("invalid task")
    if state not in STATES or doc not in DOC_STATES: raise ProgressError("invalid status")
    if not isinstance(evidence,list) or len(evidence)>20 or any(not isinstance(e,str) or not e.strip() or len(e)>512 for e in evidence):
        raise ProgressError("invalid evidence")
    if state=="verified" and (not evidence or doc not in ("verified","not_applicable")):
        raise ProgressError("verification requires documentation and evidence")

def update(principal, payload):
    if not authorized(principal): raise PermissionError("forbidden")
    validate_payload(payload)
    task_id=payload["task_id"];state=payload["state"];doc=payload["doc_state"];evidence=payload["evidence"]
    db=connect()
    try:
        with db:
            row=db.execute("SELECT state FROM tasks WHERE task_id=?",(task_id,)).fetchone()
            if row is None: raise ProgressError("unknown task")
            now=datetime.now(timezone.utc).isoformat()
            db.execute("UPDATE tasks SET state=?,doc_state=?,evidence=?,updated_at=? WHERE task_id=?",
                       (state,doc,json.dumps(evidence),now,task_id))
            db.execute("INSERT INTO history(task_id,actor,old_state,new_state,changed_at) VALUES(?,?,?,?,?)",
                       (task_id,principal.subject_id,row["state"],state,now))
    finally: db.close()
    return snapshot(principal)
