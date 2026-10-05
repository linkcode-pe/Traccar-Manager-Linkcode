"""Loopback-only Traccar Manager Web bootstrap with local authentication.

No database, Traccar, filesystem, shell, or production-provider integration.
"""
from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import sys
import re
from urllib.parse import parse_qsl, urlsplit

# Direct service execution starts outside the package context. Resolve the
# checkout root from this file before importing project-local modules.
if __package__ in (None, ""):
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from manager.auth.audit import write_auth_audit
from manager.auth.auth_store import AuthStore, AuthStoreError
from manager.auth.session_store import SessionStore
from api.read_only_dashboard_v1 import DashboardAPIError, snapshot_to_dict
from manager.dashboard_http import ManagerDashboardAPI
from manager.maintenance_http import ManagerMaintenanceAPI, MaintenanceAPIError

BIND_ADDRESS = "127.0.0.1"
PORT = 8765
HEALTH = {"status": "ok", "service": "traccar-manager"}
SESSION_COOKIE = "tm_session"
COOKIE_PATH = "/manager/"
COOKIE_MAX_AGE = 900
_TOKEN_COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
PAGE = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Traccar Manager</title>
  <!-- Manager Web -->
  <style>
    :root{color-scheme:dark;--bg:#080d18;--card:#121c2d;--card2:#0f1726;--border:rgba(164,185,220,.14);--text:#edf3ff;--muted:#91a0b9;--cyan:#54d7e8;--green:#57d49a;--amber:#f4bd61;--danger:#ff8585}
    *{box-sizing:border-box}html{min-width:320px;background:var(--bg)}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 12% 0%,rgba(34,92,132,.22),transparent 38%),var(--bg);color:var(--text);font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
    main{width:min(1120px,calc(100% - 48px));margin:auto;padding:32px 0 28px}.brand{display:flex;align-items:center;gap:15px;margin-bottom:28px}.mark{display:grid;place-items:center;width:52px;height:52px;border:1px solid rgba(84,215,232,.35);border-radius:15px;background:rgba(84,215,232,.1);color:var(--cyan);font-size:23px;font-weight:800}.brand-copy{min-width:0}.eyebrow{margin:0 0 5px;color:var(--cyan);font-size:10px;font-weight:800;letter-spacing:.16em;text-transform:uppercase}h1{margin:0;font-size:clamp(22px,3vw,29px);line-height:1.15}h2{margin:0 0 12px;font-size:19px;letter-spacing:-.02em}h3{margin:0 0 7px;font-size:16px}p{line-height:1.5}.muted{color:var(--muted);margin:5px 0 0;font-size:13px}.status{color:var(--amber);font-weight:700}.notice,.card{margin-top:12px;padding:17px 18px;border:1px solid var(--border);border-radius:14px;background:linear-gradient(150deg,#131d2f,#0e1523)}
    #dashboard-panel{display:grid;gap:13px}.dashboard-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}.card{position:relative;overflow:hidden}.card:after{position:absolute;top:-55px;right:-45px;width:125px;height:125px;border:1px solid var(--cyan);border-radius:50%;content:"";opacity:.06;pointer-events:none}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:10px 0 18px;padding:11px 14px;border:1px solid var(--border);border-radius:11px;background:rgba(17,26,43,.75)}label{display:block;margin:15px 0 6px;color:#cbd5e5;font-size:11px;font-weight:700}input{width:100%;padding:11px 12px;border:1px solid var(--border);border-radius:11px;background:#0b1321;color:var(--text);font:inherit;outline:none}input:focus{border-color:rgba(84,215,232,.55);box-shadow:0 0 0 3px rgba(84,215,232,.08)}button{display:inline-flex;align-items:center;justify-content:center;min-height:42px;margin-top:13px;padding:0 15px;border:1px solid rgba(84,215,232,.32);border-radius:11px;background:rgba(84,215,232,.1);color:var(--cyan);font:inherit;font-weight:700;cursor:pointer}button:hover{background:rgba(84,215,232,.18)}button:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}button:disabled{opacity:.55;cursor:wait}.secondary{margin-top:0;border-color:var(--border);background:rgba(145,160,185,.08);color:#cbd5e5}.error{color:#ffc1c1}.notice.error{border-color:rgba(255,112,112,.3);background:rgba(255,112,112,.08)}.safety-flow{display:flex;flex-wrap:wrap;gap:7px;margin:12px 0}.safety-flow span{padding:5px 9px;border:1px solid rgba(84,215,232,.22);border-radius:999px;background:rgba(84,215,232,.07);color:#b8eef3;font-size:10px;font-weight:700}.safety-flow .locked{border-color:rgba(244,189,97,.25);background:rgba(244,189,97,.07);color:#f4d39a}.maintenance-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:13px}.maintenance-summary div{padding:10px;border:1px solid var(--border);border-radius:11px;background:rgba(17,26,43,.75)}.maintenance-summary span,.maintenance-summary strong{display:block}.maintenance-summary span{color:var(--muted);font-size:10px}.maintenance-summary strong{margin-top:3px;font-size:15px;font-variant-numeric:tabular-nums}#maintenance-candidates{margin:12px 0 0;padding-left:20px;color:#d3dced;font-size:12px}#maintenance-candidates li{padding:5px 0;border-bottom:1px solid rgba(164,185,220,.08)}[hidden]{display:none!important}noscript{display:block;margin-top:15px;color:#ffc1c1}
    @media(max-width:720px){main{width:calc(100% - 22px);padding:17px 0}.brand{margin-bottom:20px}.mark{width:44px;height:44px}.dashboard-grid{grid-template-columns:1fr}.maintenance-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.toolbar{align-items:flex-start}.card{padding:14px}.notice{padding:13px}}
    @media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;transition-duration:.01ms!important}}
  </style>
  <script src="/manager/app.js" defer></script>
</head>
<body>
  <main>
    <header class="brand"><div class="mark" aria-hidden="true">T</div><div class="brand-copy"><p class="eyebrow">ADMINISTRACIÓN TRACCAR</p><h1>TRACCAR MANAGER</h1><p class="muted">Control, mantenimiento y operaciones auditadas</p></div></header>
    <p id="boot-status" class="notice" role="status">Comprobando sesión…</p>
    <section id="login-panel" aria-labelledby="login-title" hidden>
      <h2 id="login-title">Iniciar sesión</h2>
      <form id="login-form" action="/manager/api/auth/login" method="post" autocomplete="on">
        <label for="username">Usuario</label>
        <input id="username" name="username" autocomplete="username" maxlength="64" required>
        <label for="password">Contraseña</label>
        <input id="password" name="password" type="password" autocomplete="current-password"
               maxlength="1024" required>
        <button id="login-button" type="submit">Iniciar sesión</button>
      </form>
      <p id="login-error" class="error" role="alert" hidden></p>
    </section>
    <div id="session-bar" class="toolbar" hidden>
      <p class="muted">Sesión autenticada</p>
      <button id="logout-button" class="secondary" type="button">Cerrar sesión</button>
    </div>
    <section id="access-panel" class="notice" aria-live="polite" hidden>
      No tienes permiso para acceder al dashboard.
    </section>
    <section id="dashboard-panel" aria-labelledby="dashboard-title" hidden>
      <h2 id="dashboard-title">Dashboard</h2>
      <div class="dashboard-grid">
      <article class="card" aria-labelledby="traccar-title">
        <h3 id="traccar-title">Traccar</h3>
        <p id="traccar-state" class="status">Proveedor pendiente</p>
        <p id="traccar-detail" class="muted">El estado real del servicio no se consulta en esta fase.</p>
      </article>
      <article id="maintenance-card" class="card" aria-labelledby="maintenance-title">
        <h3 id="maintenance-title">Centro de mantenimiento</h3>
        <p class="muted">Flujo seguro de mantenimiento de logs con vista previa y preparación auditada.</p><div class="safety-flow" aria-label="Flujo de seguridad"><span>1 · Analizar</span><span>2 · Preparar</span><span class="locked">3 · Execute validado · denegado por gate final</span></div><div class="boundary-card"><strong>Frontera destructiva aislada</strong><span id="boundary-health">Comprobando frontera de seguridad…</span><span>Sin red · sin shell · Boundary restringido por SO_PEERCRED · solo Worker puede solicitar/verificar HMAC · socket 0660 · producción DENY_PRODUCTION</span></div>
        <label for="retention-days">Retención de logs (días)</label>
        <input id="retention-days" type="number" min="30" max="3650" value="90">
        <button id="preview-logs-button" type="button">Analizar logs</button>
        <button id="prepare-logs-button" class="secondary" type="button" hidden>Preparar limpieza</button>
        <p id="maintenance-preparation" class="muted" hidden></p><p id="maintenance-readiness" class="status" hidden></p>
        <div id="maintenance-security" class="security-checks" hidden><strong>Controles verificados antes de ejecutar</strong><span>Preparación ligada a la sesión y registrada durablemente</span><span>Auditoría durable antes del consumo</span><span>Autorización one-shot y anti-replay</span><span>Revalidación del plan antes de cualquier mutación</span></div>
        <p id="maintenance-state" class="status">Sin análisis</p>
        <p id="maintenance-detail" class="muted">No se ha ejecutado ninguna vista previa.</p>
        <div id="maintenance-summary" class="maintenance-summary" hidden>
          <div><span>Históricos</span><strong id="maintenance-history-count">—</strong></div>
          <div><span>Tamaño históricos</span><strong id="maintenance-history-bytes">—</strong></div>
          <div><span>Candidatos</span><strong id="maintenance-candidate-count">—</strong></div>
          <div><span>Recuperable</span><strong id="maintenance-candidate-bytes">—</strong></div>
        </div>
        <p id="maintenance-range" class="muted" hidden></p>
        <ul id="maintenance-candidates"></ul>
        <p id="maintenance-error" class="error" role="alert" hidden></p>
      </article>
      </div>
      <p id="dashboard-error" class="error" role="alert" hidden></p>
    </section>
    <noscript>Activa JavaScript para iniciar sesión y consultar el dashboard.</noscript>
  </main>
</body>
</html>
""".encode("utf-8")

APP_JS = r"""(() => {
  "use strict";
  const path = window.location.pathname.endsWith("/")
    ? window.location.pathname : window.location.pathname + "/";
  const api = (name) => path + "api/" + name;
  const byId = (name) => document.getElementById(name);
  const boot = byId("boot-status");
  const loginPanel = byId("login-panel");
  const sessionBar = byId("session-bar");
  const accessPanel = byId("access-panel");
  const dashboardPanel = byId("dashboard-panel");
  const loginForm = byId("login-form");
  const loginButton = byId("login-button");
  const usernameInput = byId("username");
  const passwordInput = byId("password");
  const loginError = byId("login-error");
  const dashboardError = byId("dashboard-error");
  const traccarState = byId("traccar-state");
  const traccarDetail = byId("traccar-detail");
  const retentionDays = byId("retention-days");
  const previewLogsButton = byId("preview-logs-button");
  const prepareLogsButton=byId("prepare-logs-button"); const maintenancePreparation=byId("maintenance-preparation"); const maintenanceReadiness=byId("maintenance-readiness"); const maintenanceSecurity=byId("maintenance-security"); let lastPreview=null;
  const maintenanceState = byId("maintenance-state");
  const maintenanceDetail = byId("maintenance-detail");
  const maintenanceCandidates = byId("maintenance-candidates");
  const maintenanceSummary = byId("maintenance-summary");
  const maintenanceHistoryCount = byId("maintenance-history-count");
  const maintenanceHistoryBytes = byId("maintenance-history-bytes");
  const maintenanceCandidateCount = byId("maintenance-candidate-count");
  const maintenanceCandidateBytes = byId("maintenance-candidate-bytes");
  const maintenanceRange = byId("maintenance-range");
  const maintenanceError = byId("maintenance-error");
  const boundaryHealth=byId("boundary-health");

  function showLogin(message) {
    boot.hidden = true;
    loginPanel.hidden = false;
    sessionBar.hidden = true;
    accessPanel.hidden = true;
    dashboardPanel.hidden = true;
    passwordInput.value = "";
    loginError.textContent = message || "";
    loginError.hidden = !message;
  }

  function showAccessDenied() {
    boot.hidden = true;
    loginPanel.hidden = true;
    sessionBar.hidden = false;
    accessPanel.hidden = false;
    dashboardPanel.hidden = true;
  }

  function showAuthenticatedLoading() {
    loginPanel.hidden = true;
    sessionBar.hidden = false;
    accessPanel.hidden = true;
    dashboardPanel.hidden = true;
    boot.textContent = "Cargando dashboard…";
    boot.hidden = false;
  }

  async function fetchApi(name, options) {
    const request = options || {};
    return fetch(api(name), {
      ...request,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: { "Accept": "application/json", ...(request.headers || {}) }
    });
  }

  function newRequestId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    if (window.crypto && typeof window.crypto.getRandomValues === "function") {
      return Array.from(window.crypto.getRandomValues(new Uint8Array(16)),
        (value) => value.toString(16).padStart(2, "0")).join("");
    }
    throw new Error("request_id_unavailable");
  }

  function formatBytes(value) {
    if (!Number.isSafeInteger(value) || value < 0) return "—";
    if (value < 1024) return value + " B";
    const units=["KiB","MiB","GiB","TiB"]; let n=value/1024, i=0;
    while (n >= 1024 && i < units.length-1) { n/=1024; i++; }
    return n.toFixed(n >= 10 ? 1 : 2) + " " + units[i];
  }

  async function loadBoundaryHealth(){ try { const requestId=newRequestId(); const r=await fetchApi("maintenance/boundary/health?request_id="+encodeURIComponent(requestId)); if(!r.ok)throw new Error(); const d=await r.json(),b=d.boundary; if(!b||b.status!=="healthy"||b.mode!=="DENY_PRODUCTION"||b.production_access!==false||b.destructive_action_performed!==false)throw new Error(); boundaryHealth.textContent="Servicio de frontera activo · health dinámico verificado por Worker · DynamicUser · DENY_PRODUCTION"; }catch(_e){ boundaryHealth.textContent="Frontera no disponible · operación bloqueada"; }}

  async function previewLogs() {
    maintenanceError.hidden=true; maintenanceCandidates.replaceChildren(); maintenanceSummary.hidden=true; maintenanceRange.hidden=true;
    const days=Number(retentionDays.value);
    if (!Number.isInteger(days) || days < 30 || days > 3650) {
      maintenanceError.textContent="La retención debe estar entre 30 y 3650 días."; maintenanceError.hidden=false; return;
    }
    previewLogsButton.disabled=true; maintenanceState.textContent="Analizando…";
    try {
      const requestId=newRequestId();
      const response=await fetchApi("maintenance/logs/preview?request_id="+encodeURIComponent(requestId)+"&retention_days="+days,{method:"GET"});
      if (response.status===401) { showLogin("La sesión expiró. Inicia sesión de nuevo."); return; }
      if (response.status===403) { maintenanceState.textContent="Sin permiso"; maintenanceDetail.textContent="Se requiere maintenance.logs.preview."; return; }
      if (!response.ok) throw new Error("maintenance_unavailable");
      const data=await response.json(), p=data && data.preview;
      if (!data || data.schema_version!==1 || data.request_id!==requestId || !p || p.destructive_action_performed!==false || p.active_log_protected!==true || !Array.isArray(p.candidates)) throw new Error("maintenance_invalid");
      maintenanceState.textContent=p.candidate_count+" archivo(s) candidato(s)";
      maintenanceDetail.textContent="Corte UTC: "+p.cutoff_utc+" · log activo protegido · solo vista previa";
      maintenanceHistoryCount.textContent=String(p.historical_count);
      maintenanceHistoryBytes.textContent=formatBytes(p.historical_bytes);
      maintenanceCandidateCount.textContent=String(p.candidate_count);
      maintenanceCandidateBytes.textContent=formatBytes(p.candidate_bytes);
      maintenanceSummary.hidden=false; lastPreview=p.candidate_count>0?{previewId:data.preview_id,days:days}:null; prepareLogsButton.hidden=p.candidate_count===0; maintenancePreparation.hidden=true; maintenanceSecurity.hidden=true;
      if(p.candidate_count===0){ maintenanceReadiness.textContent="Sin candidatos · Prepare y Execute deshabilitados · no hay nada que eliminar"; maintenanceReadiness.hidden=false; } else { maintenanceReadiness.hidden=true; }
      maintenanceRange.textContent=p.candidate_count ? "Rango candidato: "+p.oldest_candidate_utc+" → "+p.newest_candidate_utc : "No existen archivos fuera de la retención seleccionada. El flujo termina de forma segura sin Prepare ni Execute.";
      maintenanceRange.hidden=false;
      p.candidates.forEach((item)=>{ const li=document.createElement("li"); li.textContent=item.name+" — "+formatBytes(item.size_bytes)+" — "+item.mtime_utc; maintenanceCandidates.appendChild(li); });
    } catch (_error) { maintenanceState.textContent="Vista previa no disponible"; maintenanceDetail.textContent="No se realizó ninguna acción destructiva."; maintenanceError.textContent="No se pudo analizar los logs."; maintenanceError.hidden=false; }
    finally { previewLogsButton.disabled=false; }
  }


  async function prepareLogs(){ if(!lastPreview)return; prepareLogsButton.disabled=true; maintenanceError.hidden=true; try { const requestId=newRequestId(); const response=await fetchApi("maintenance/logs/prepare",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({request_id:requestId,preview_id:lastPreview.previewId,retention_days:lastPreview.days})}); if(response.status===401){showLogin("La sesión expiró. Inicia sesión de nuevo.");return;} if(response.status===403){maintenancePreparation.textContent="Sin permiso maintenance.logs.prepare.";maintenancePreparation.hidden=false;return;} if(!response.ok)throw new Error(); const data=await response.json(),q=data.preparation; if(!q||q.destructive_action_performed!==false||q.revalidated!==true||data.preparation_stored!==true||data.execution_readiness!=="READY_BLOCKED"||data.boundary_execute_probe!=="DENIED_BY_PRODUCTION_GATE"||data.boundary_candidate_count!==q.candidate_count)throw new Error(); maintenancePreparation.textContent="Preparación auditada y registro durable confirmados por Worker. Expira: "+q.expires_at_utc+" · ejecución real todavía bloqueada · no se eliminó ningún archivo.";maintenancePreparation.hidden=false; maintenanceReadiness.textContent="Plan real revalidado · "+data.boundary_candidate_count+" candidatos · denegado por gate final"; maintenanceReadiness.hidden=false; maintenanceSecurity.hidden=false; prepareLogsButton.hidden=true; }catch(e){maintenanceError.textContent="No se pudo preparar la limpieza. Vuelve a analizar los logs.";maintenanceError.hidden=false;}finally{prepareLogsButton.disabled=false;} }

  async function loadSnapshot() {
    showAuthenticatedLoading();
    dashboardError.hidden = true;
    traccarState.textContent = "Proveedor pendiente";
    traccarDetail.textContent = "El estado real del servicio no se consulta en esta fase.";
    try {
      const requestId = newRequestId();
      const response = await fetchApi("dashboard/snapshot?request_id=" + encodeURIComponent(requestId),
        { method: "GET" });
      if (response.status === 401) {
        showLogin("La sesión expiró. Inicia sesión de nuevo.");
        return;
      }
      if (response.status === 403) {
        showAccessDenied();
        return;
      }
      if (!response.ok) {
        throw new Error("dashboard_unavailable");
      }
      const snapshot = await response.json();
      if (!snapshot || snapshot.schema_version !== 1 || snapshot.request_id !== requestId) {
        throw new Error("dashboard_invalid");
      }
      const service = snapshot.general && snapshot.general.traccar_service;
      const fields = service && [service.state, service.substate, service.load_state,
        service.unit_file_state, service.result];
      if (!Array.isArray(fields) || fields.length !== 5) {
        throw new Error("dashboard_invalid");
      }
      const pending = fields.every((value) => value && value.availability === "PENDING_PROVIDER");
      if (pending) {
        traccarState.textContent = "Proveedor pendiente";
        traccarDetail.textContent = "El estado del servicio requiere el permiso traccar.status.read.";
      } else {
        const allowedState = /^[A-Za-z0-9_.+-]{1,64}$/;
        const available = fields.every((value) => value && value.availability === "AVAILABLE"
          && typeof value.value === "string" && allowedState.test(value.value)
          && typeof value.observed_at_utc === "string" && value.observed_at_utc.endsWith("Z"));
        const timestamps = available ? fields.map((value) => value.observed_at_utc) : [];
        const observed = timestamps.length && timestamps.every((value) => value === timestamps[0])
          ? timestamps[0] : null;
        if (available && observed && Number.isFinite(Date.parse(observed))) {
          traccarState.textContent = service.state.value + " / " + service.substate.value;
          traccarDetail.textContent = "LoadState: " + service.load_state.value
            + " · UnitFileState: " + service.unit_file_state.value
            + " · Result: " + service.result.value + " · Observed UTC: " + observed;
        } else {
          traccarState.textContent = "Estado no disponible";
          traccarDetail.textContent = "No se muestran datos de estado en esta versión.";
        }
      }
      dashboardPanel.hidden = false;
      loadBoundaryHealth();
      boot.hidden = true;
    } catch (_error) {
      traccarState.textContent = "Estado no disponible";
      traccarDetail.textContent = "No se pudo cargar el dashboard. Inténtalo más tarde.";
      dashboardError.textContent = "No se pudo cargar el dashboard.";
      dashboardError.hidden = false;
      dashboardPanel.hidden = true;
      boot.textContent = "No se pudo cargar el dashboard. Inténtalo más tarde.";
      boot.hidden = false;
    }
  }

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    loginError.hidden = true;
    loginButton.disabled = true;
    const credentials = { username: usernameInput.value, password: passwordInput.value };
    passwordInput.value = "";
    try {
      const response = await fetchApi("auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(credentials)
      });
      if (!response.ok) {
        throw new Error("login_failed");
      }
      const result = await response.json();
      if (!result || result.authenticated !== true) {
        throw new Error("login_failed");
      }
      loadSnapshot();
    } catch (_error) {
      showLogin("No fue posible iniciar sesión. Revisa tus datos o inténtalo más tarde.");
    } finally {
      credentials.password = "";
      passwordInput.value = "";
      loginButton.disabled = false;
    }
  });

  byId("logout-button").addEventListener("click", async () => {
    try {
      const response = await fetchApi("auth/logout", { method: "POST" });
      if (response.status === 204) {
        showLogin("Sesión cerrada.");
      } else {
        showLogin("No se pudo confirmar el cierre. Inicia sesión de nuevo.");
      }
    } catch (_error) {
      showLogin("No se pudo confirmar el cierre. Inicia sesión de nuevo.");
    }
  });

  previewLogsButton.addEventListener("click", previewLogs);
  prepareLogsButton.addEventListener("click",prepareLogs);

  (async () => {
    try {
      const response = await fetchApi("auth/me", { method: "GET" });
      if (response.status === 401) {
        showLogin("");
        return;
      }
      if (!response.ok) {
        showLogin("Autenticación temporalmente no disponible.");
        return;
      }
      const result = await response.json();
      if (!result || result.authenticated !== true) {
        showLogin("");
        return;
      }
      loadSnapshot();
    } catch (_error) {
      showLogin("No se pudo verificar la sesión.");
    }
  })();
})();
""".encode("utf-8")


class ManagerHTTPServer(HTTPServer):
    address_family = socket.AF_INET
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, port: int = PORT, *, auth_store: AuthStore | None = None,
                 session_store: SessionStore | None = None, audit_writer=write_auth_audit,
                 dashboard_api: ManagerDashboardAPI | None = None,
                 maintenance_api: ManagerMaintenanceAPI | None = None):
        self.auth_store = auth_store if auth_store is not None else AuthStore()
        self.session_store = session_store if session_store is not None else SessionStore()
        self.audit_writer = audit_writer
        self.dashboard_api = dashboard_api if dashboard_api is not None else ManagerDashboardAPI()
        self.maintenance_api = maintenance_api if maintenance_api is not None else ManagerMaintenanceAPI()
        super().__init__((BIND_ADDRESS, port), ManagerRequestHandler)
        if self.server_address[0] != BIND_ADDRESS:
            self.server_close()
            raise RuntimeError("Manager Web must bind only to 127.0.0.1")

    def server_close(self) -> None:
        try:
            dashboard_api = getattr(self, "dashboard_api", None)
            if dashboard_api is not None:
                dashboard_api.close()
        finally:
            maintenance_api = getattr(self, "maintenance_api", None)
            if maintenance_api is not None:
                maintenance_api.close()
            super().server_close()


class ManagerRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "TraccarManager"
    sys_version = ""

    def log_message(self, _format: str, *args: object) -> None:
        # Do not send request lines, headers, cookies, query strings, or bodies to logs.
        return

    def _respond(self, status: int, body: bytes, content_type: str,
                 headers: tuple[tuple[str, str], ...] = ()) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; "
                         "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("Connection", "close")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True

    def _json(self, status: int, payload: dict[str, object],
              headers: tuple[tuple[str, str], ...] = ()) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self._respond(status, body, "application/json; charset=utf-8", headers)

    def _audit(self, event: str, result: str, reason: str) -> bool:
        try:
            return self.server.audit_writer(event, result, reason)
        except Exception:
            return False

    def _method_not_allowed(self, allow: str = "GET") -> None:
        self._respond(HTTPStatus.METHOD_NOT_ALLOWED, b"Method Not Allowed\n",
                      "text/plain; charset=utf-8", (("Allow", allow),))

    def send_error(self, code: int, message: str | None = None,
                   explain: str | None = None) -> None:
        if code == HTTPStatus.NOT_IMPLEMENTED:
            self._method_not_allowed()
        else:
            self._respond(code, b"Bad Request\n", "text/plain; charset=utf-8")

    def _cookie_token(self) -> str | None:
        values = self.headers.get_all("Cookie", [])
        if len(values) != 1:
            return None
        matches: list[str] = []
        for part in values[0].split(";"):
            name, separator, value = part.strip().partition("=")
            if separator and name == SESSION_COOKIE:
                matches.append(value.strip())
        if len(matches) != 1 or not _TOKEN_COOKIE_RE.fullmatch(matches[0]):
            return None
        return matches[0]

    def _read_login_body(self) -> tuple[str, str] | None:
        if self.headers.get("Transfer-Encoding") is not None:
            return None
        types = self.headers.get_all("Content-Type", [])
        lengths = self.headers.get_all("Content-Length", [])
        if len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json":
            return None
        if len(lengths) != 1:
            return None
        try:
            length = int(lengths[0])
        except (TypeError, ValueError):
            return None
        if not 1 <= length <= 4096:
            return None
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or set(data) != {"username", "password"}:
            return None
        username, password = data.get("username"), data.get("password")
        if (not isinstance(username, str) or not isinstance(password, str) or
                len(username) > 64 or not 1 <= len(password) <= 1024):
            return None
        return username, password

    def _handle_login(self) -> None:
        credentials = self._read_login_body()
        if credentials is None:
            if not self._audit("AUTH_LOGIN", "DENIED", "INVALID_REQUEST"):
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "authentication_unavailable"})
            else:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        username, password = credentials
        try:
            user = self.server.auth_store.authenticate(username, password)
        except AuthStoreError:
            if not self._audit("AUTH_LOGIN", "UNAVAILABLE", "AUTH_STORE_UNAVAILABLE"):
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "authentication_unavailable"})
            else:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "authentication_unavailable"})
            return
        if user is None:
            if not self._audit("AUTH_LOGIN", "DENIED", "INVALID_CREDENTIALS"):
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "authentication_unavailable"})
            else:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        token, principal = self.server.session_store.create(user)
        if not self._audit("AUTH_LOGIN", "SUCCEEDED", "AUTHENTICATED"):
            self.server.session_store.revoke(token)
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "authentication_unavailable"})
            return
        cookie = (f"{SESSION_COOKIE}={token}; Path={COOKIE_PATH}; Max-Age={COOKIE_MAX_AGE}; "
                  "Secure; HttpOnly; SameSite=Strict")
        self._json(HTTPStatus.OK, {
            "authenticated": True,
            "user": principal.public_dict(),
            "expires_at_utc": principal.expires_at_utc,
        }, (("Set-Cookie", cookie),))

    def _handle_me(self) -> None:
        token = self._cookie_token()
        principal = self.server.session_store.get(token) if token is not None else None
        if principal is None:
            reason = "SESSION_ABSENT" if token is None else "SESSION_INVALID_OR_EXPIRED"
            if not self._audit("AUTH_SESSION_CHECK", "DENIED", reason):
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "authentication_unavailable"})
            else:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if not self._audit("AUTH_SESSION_CHECK", "SUCCEEDED", "SESSION_VALID"):
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "authentication_unavailable"})
            return
        self._json(HTTPStatus.OK, {
            "authenticated": True,
            "user": principal.public_dict(),
            "expires_at_utc": principal.expires_at_utc,
        })

    def _handle_logout(self) -> None:
        # Logout is idempotent and always expires the browser's cookie.
        token = self._cookie_token()
        if token is not None:
            self.server.session_store.revoke(token)
        headers = (("Set-Cookie", f"{SESSION_COOKIE}=; Path={COOKIE_PATH}; Max-Age=0; Secure; HttpOnly; SameSite=Strict"),)
        if not self._audit("AUTH_LOGOUT", "SUCCEEDED", "LOGOUT_COMPLETED"):
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "authentication_unavailable"}, headers)
            return
        self._respond(HTTPStatus.NO_CONTENT, b"", "application/json; charset=utf-8", headers)

    def _handle_dashboard_snapshot(self) -> None:
        token = self._cookie_token()
        principal = self.server.session_store.get(token) if token is not None else None
        if principal is None:
            reason = "SESSION_ABSENT" if token is None else "SESSION_INVALID_OR_EXPIRED"
            if not self._audit("AUTH_SESSION_CHECK", "DENIED", reason):
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "authentication_unavailable"})
            else:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if "dashboard.read" not in principal.roles:
            if not self._audit("AUTH_DASHBOARD_READ", "DENIED", "ROLE_NOT_ALLOWED"):
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "authentication_unavailable"})
            else:
                self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            return
        try:
            query = parse_qsl(urlsplit(self.path).query, keep_blank_values=True,
                              strict_parsing=True, max_num_fields=2)
        except (ValueError, UnicodeError):
            query = []
        if len(query) != 1 or query[0][0] != "request_id" or not query[0][1]:
            if not self._audit("AUTH_DASHBOARD_READ", "DENIED", "INVALID_REQUEST"):
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "authentication_unavailable"})
            else:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        request_id = query[0][1]
        if not self._audit("AUTH_DASHBOARD_READ", "REQUESTED", "READ_REQUESTED"):
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "authentication_unavailable"})
            return
        try:
            snapshot = self.server.dashboard_api.read(request_id, principal)
        except DashboardAPIError as exc:
            status_by_error = {
                "API_FORBIDDEN": HTTPStatus.FORBIDDEN,
                "API_INVALID_REQUEST": HTTPStatus.BAD_REQUEST,
                "API_AUDIT_UNAVAILABLE": HTTPStatus.SERVICE_UNAVAILABLE,
                "API_PROVIDER_UNAVAILABLE": HTTPStatus.SERVICE_UNAVAILABLE,
                "API_SOURCE_NOT_ALLOWED": HTTPStatus.SERVICE_UNAVAILABLE,
                "API_TIMEOUT": HTTPStatus.SERVICE_UNAVAILABLE,
            }
            status = status_by_error.get(exc.code, HTTPStatus.INTERNAL_SERVER_ERROR)
            reason = "AUDIT_UNAVAILABLE" if exc.code == "API_AUDIT_UNAVAILABLE" else (
                "PROVIDER_UNAVAILABLE" if exc.code in {"API_PROVIDER_UNAVAILABLE", "API_SOURCE_NOT_ALLOWED", "API_TIMEOUT"}
                else "INTERNAL_ERROR")
            if not self._audit("AUTH_DASHBOARD_READ", "UNAVAILABLE", reason):
                status = HTTPStatus.SERVICE_UNAVAILABLE
            self._json(status, {"error": "dashboard_unavailable", "request_id": request_id})
            return
        if not self._audit("AUTH_DASHBOARD_READ", "SUCCEEDED", "DISPATCHER_RECEIPT_VERIFIED"):
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "audit_unavailable"})
            return
        self._json(HTTPStatus.OK, snapshot_to_dict(snapshot))

    def _handle_boundary_health(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "maintenance.logs.preview" not in principal.roles: self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        try:
            query=parse_qsl(urlsplit(self.path).query,keep_blank_values=True,strict_parsing=True,max_num_fields=1); values={k:v for k,v in query}
            if len(query)!=1 or set(values)!={"request_id"} or not values["request_id"]: raise ValueError()
            result=self.server.maintenance_api.boundary_health(values["request_id"],principal)
        except MaintenanceAPIError: self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"boundary_unavailable"}); return
        except Exception: self._json(HTTPStatus.BAD_REQUEST,{"error":"invalid_request"}); return
        self._json(HTTPStatus.OK,result)

    def _handle_maintenance_logs_preview(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None:
            self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "maintenance.logs.preview" not in principal.roles:
            self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        try:
            query=parse_qsl(urlsplit(self.path).query,keep_blank_values=True,strict_parsing=True,max_num_fields=3)
            values={k:v for k,v in query}
            if len(query)!=2 or set(values)!={"request_id","retention_days"}: raise ValueError()
            days=int(values["retention_days"])
            if str(days)!=values["retention_days"] or not 30<=days<=3650 or not values["request_id"]: raise ValueError()
        except (ValueError,UnicodeError):
            self._json(HTTPStatus.BAD_REQUEST,{"error":"invalid_request"}); return
        try: result=self.server.maintenance_api.preview_logs(values["request_id"],principal,days)
        except MaintenanceAPIError as exc:
            status={"API_FORBIDDEN":HTTPStatus.FORBIDDEN,"API_INVALID_REQUEST":HTTPStatus.BAD_REQUEST,
                    "API_AUDIT_UNAVAILABLE":HTTPStatus.SERVICE_UNAVAILABLE,"API_PROVIDER_UNAVAILABLE":HTTPStatus.SERVICE_UNAVAILABLE}.get(exc.code,HTTPStatus.INTERNAL_SERVER_ERROR)
            self._json(status,{"error":"maintenance_unavailable","request_id":values["request_id"]}); return
        self._json(HTTPStatus.OK,result)

    def _handle_maintenance_logs_prepare(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "maintenance.logs.prepare" not in principal.roles: self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        try:
            length=int(self.headers.get("Content-Length","0")); raw=self.rfile.read(length); data=json.loads(raw.decode("utf-8"))
            if not isinstance(data,dict) or set(data)!={"request_id","preview_id","retention_days"}: raise ValueError()
            if not isinstance(data["request_id"],str) or not data["request_id"] or not isinstance(data["preview_id"],str) or not data["preview_id"].startswith("preview-") or len(data["preview_id"])!=72 or type(data["retention_days"]) is not int or not 30<=data["retention_days"]<=3650: raise ValueError()
        except Exception: self._json(HTTPStatus.BAD_REQUEST,{"error":"invalid_request"}); return
        try: result=self.server.maintenance_api.prepare_logs(data["request_id"],principal,data["preview_id"],data["retention_days"])
        except MaintenanceAPIError as exc:
            status={"API_FORBIDDEN":HTTPStatus.FORBIDDEN,"API_INVALID_REQUEST":HTTPStatus.BAD_REQUEST,"API_AUDIT_UNAVAILABLE":HTTPStatus.SERVICE_UNAVAILABLE,"API_PROVIDER_UNAVAILABLE":HTTPStatus.SERVICE_UNAVAILABLE}.get(exc.code,HTTPStatus.INTERNAL_SERVER_ERROR); self._json(status,{"error":"maintenance_unavailable","request_id":data["request_id"]}); return
        self._json(HTTPStatus.OK,result)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/":
            self._respond(HTTPStatus.OK, PAGE, "text/html; charset=utf-8")
        elif path == "/health":
            payload = json.dumps(HEALTH, separators=(",", ":")).encode("ascii")
            self._respond(HTTPStatus.OK, payload, "application/json")
        elif path == "/app.js":
            self._respond(HTTPStatus.OK, APP_JS, "application/javascript; charset=utf-8")
        elif path == "/api/auth/me":
            self._handle_me()
        elif path == "/api/dashboard/snapshot":
            self._handle_dashboard_snapshot()
        elif path == "/api/maintenance/boundary/health":
            self._handle_boundary_health()
        elif path == "/api/maintenance/logs/preview":
            self._handle_maintenance_logs_preview()
        elif path in ("/api/auth/login", "/api/auth/logout"):
            self._method_not_allowed("POST")
        else:
            self._respond(HTTPStatus.NOT_FOUND, b"Not Found\n", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/auth/login":
            self._handle_login()
        elif path == "/api/auth/logout":
            self._handle_logout()
        elif path == "/api/maintenance/logs/prepare":
            self._handle_maintenance_logs_prepare()
        elif path in ("/", "/health", "/app.js", "/api/auth/me", "/api/dashboard/snapshot", "/api/maintenance/logs/preview"):
            self._method_not_allowed("GET")
        else:
            self._respond(HTTPStatus.NOT_FOUND, b"Not Found\n", "text/plain; charset=utf-8")

    do_HEAD = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed
    do_TRACE = _method_not_allowed
    do_CONNECT = _method_not_allowed


def _handle_sigterm(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def main() -> int:
    if os.geteuid() == 0:
        print("Refusing to run Manager Web as root", file=sys.stderr)
        return 1
    server = ManagerHTTPServer()
    old_sigterm = signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        print(f"Traccar Manager started on http://{BIND_ADDRESS}:{PORT}", flush=True)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        signal.signal(signal.SIGTERM, old_sigterm)
        print("Traccar Manager stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
