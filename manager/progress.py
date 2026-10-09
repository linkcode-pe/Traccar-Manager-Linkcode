"""PROG-001 persistent progress checklist, independent of official Traccar."""
import json
import re
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROLE = "development.progress.manage"
DB_PATH = Path("/var/lib/traccar-manager-progress/progress.sqlite3")
PLAN_PATH = Path(__file__).resolve().parent.parent / "docs/plan-maestro/PLAN_MAESTRO_TRACCAR_MANAGER_ACTUALIZADO.md"
STATES = ("pending", "in_development", "in_testing", "blocked", "verified")
DOC_STATES = ("pending", "in_review", "verified", "not_applicable")
GROUPS = {
    "0 Auditoría": ["AUD-001","AUD-002","AUD-003","AUD-004"],
    "1 Seguridad y continuidad": [*(f"SEC-{i:03}" for i in range(1,10)),*(f"BCP-{i:03}" for i in range(1,4))],
    "2 Centro de progreso": [*(f"PROG-{i:03}" for i in range(1,6)),"DOC-001"],
    "3 Administración y operaciones": ["ADM-001","ADM-002","OPS-001","OPS-002","OPS-003"],
    "4 Integraciones": ["TEO-001","COM-001","COM-002","COM-003"],
}
TITLES = {
 "DOC-001":"Documentación viva obligatoria",
 "PROG-001":"Permiso exclusivo de superadministrador",
 "PROG-002":"Catálogo y persistencia del checklist",
 "PROG-003":"Interfaz web de desarrollo y progreso",
 "PROG-004":"Evidencias, auditoría y progreso verificable",
 "PROG-005":"Pruebas, respaldo y despliegue",
 "COM-001":"Eventos Traccar y destinatarios WhatsApp",
 "COM-002":"Consola administrativa del bot",
 "COM-003":"Mensajería, conversaciones y observabilidad",
 "SEC-009":"Revocación segura de sesiones",
}
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
            now=datetime.now(timezone.utc).isoformat()
            for phase, ids in GROUPS.items():
                for task_id in ids:
                    db.execute("INSERT OR IGNORE INTO tasks VALUES (?,?,?,?,?,?,?)",
                      (task_id,phase,TITLES.get(task_id,task_id+" — pendiente de especificación"),
                       "pending","pending","[]",now))
    finally:
        db.close()

def plan_source():
    content = PLAN_PATH.read_text(encoding="utf-8")
    if len(content) > 200000:
        raise ProgressError("plan too large")
    return {"markdown": content, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(), "source": "docs/plan-maestro/PLAN_MAESTRO_TRACCAR_MANAGER_ACTUALIZADO.md"}

def snapshot(principal):
    if not authorized(principal): raise PermissionError("forbidden")
    db=connect()
    try:
        tasks=[]
        for row in db.execute("SELECT * FROM tasks ORDER BY phase,task_id"):
            d=dict(row);d["evidence"]=json.loads(d.pop("evidence"));tasks.append(d)
        verified=sum(t["state"]=="verified" for t in tasks)
        return {"tasks":tasks,"plan": {k:v for k,v in plan_source().items() if k != "markdown"},"verified":verified,"total":len(tasks),
                "percentage":round(verified*100/len(tasks),2) if tasks else None}
    finally: db.close()

def update(principal, payload):
    if not authorized(principal): raise PermissionError("forbidden")
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
