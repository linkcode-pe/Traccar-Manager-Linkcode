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
  <style>
    :root { color-scheme: light; font-family: system-ui, sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center;
           padding: 1.25rem 0; box-sizing: border-box; background: #f1f5f9; color: #0f172a; }
    main { width: min(44rem, calc(100% - 2rem)); box-sizing: border-box;
           padding: clamp(1.25rem, 4vw, 2.25rem); border: 1px solid #dbe3ee; border-radius: 1rem;
           background: #fff; box-shadow: 0 1rem 3rem #0f172a12; }
    .eyebrow { color: #2563eb; font-size: .8rem; font-weight: 700;
               letter-spacing: .12em; text-transform: uppercase; }
    h1 { margin: .5rem 0; font-size: clamp(2rem, 6vw, 3rem); }
    h2, h3 { margin-top: 0; }
    p { line-height: 1.5; }
    .muted { color: #475569; }
    .status { color: #92400e; font-weight: 700; }
    .notice, .card { margin-top: 1.25rem; padding: 1rem; border: 1px solid #dbe3ee;
                     border-radius: .75rem; background: #f8fafc; }
    label { display: block; margin: 1rem 0 .35rem; font-weight: 600; }
    input { width: 100%; box-sizing: border-box; padding: .75rem; border: 1px solid #94a3b8;
            border-radius: .5rem; font: inherit; }
    button { margin-top: 1rem; padding: .7rem 1rem; border: 0; border-radius: .5rem;
             background: #1d4ed8; color: #fff; font: inherit; font-weight: 650; cursor: pointer; }
    button:disabled { opacity: .65; cursor: wait; }
    .secondary { background: #475569; }
    .toolbar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
    .error { color: #b91c1c; }
    [hidden] { display: none !important; }
    noscript { display: block; margin-top: 1rem; color: #b91c1c; }
  </style>
  <script src="/manager/app.js" defer></script>
</head>
<body>
  <main>
    <p class="eyebrow">Manager Web</p>
    <h1>Traccar Manager</h1>
    <p class="muted">Panel autenticado de solo lectura.</p>
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
      <article class="card" aria-labelledby="traccar-title">
        <h3 id="traccar-title">Traccar</h3>
        <p id="traccar-state" class="status">Proveedor pendiente</p>
        <p id="traccar-detail" class="muted">El estado real del servicio no se consulta en esta fase.</p>
      </article>
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
                 dashboard_api: ManagerDashboardAPI | None = None):
        self.auth_store = auth_store if auth_store is not None else AuthStore()
        self.session_store = session_store if session_store is not None else SessionStore()
        self.audit_writer = audit_writer
        self.dashboard_api = dashboard_api if dashboard_api is not None else ManagerDashboardAPI()
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
        elif path in ("/", "/health", "/app.js", "/api/auth/me", "/api/dashboard/snapshot"):
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
