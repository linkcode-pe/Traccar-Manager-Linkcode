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
from urllib.parse import parse_qsl, parse_qs, urlsplit

# Direct service execution starts outside the package context. Resolve the
# checkout root from this file before importing project-local modules.
if __package__ in (None, ""):
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from manager.auth.audit import write_auth_audit, read_recent_auth_audit
from manager.auth.auth_store import AuthStore, AuthStoreError
from manager.auth.session_store import SessionStore
from api.read_only_dashboard_v1 import DashboardAPIError, snapshot_to_dict
from manager.dashboard_http import ManagerDashboardAPI
from manager.maintenance_http import ManagerMaintenanceAPI, MaintenanceAPIError
from manager.server_status import read_server_status
from manager.device_inventory import read_device_inventory
from manager.health_history import read_health_history
from manager.incident_history import read_incidents
from manager.incident_decisions import read_incident_decisions, read_global_interventions
from manager.preventive_diagnostics import diagnostic_center, incident_casefile
from manager.operational_health import operational_health
from manager.operational_health_history import read_operational_health_history, read_operational_availability
from manager.administrative_attention_history import read_administrative_attention_history, read_administrative_attention_metrics
from manager.administrative_index_history import read_administrative_index_history
from manager.progress import init as progress_init, snapshot as progress_snapshot, update as progress_update, authorized as progress_authorized, plan_source as progress_plan_source, ingest_event as progress_ingest_event, ProgressError
from manager.progress_page import PAGE as PROGRESS_PAGE
from pathlib import Path as _ProgressPath
from manager.account_profile import read_profile, save_profile, save_avatar, read_avatar, save_password, alert_unread, mark_alert_seen

BIND_ADDRESS = "127.0.0.1"
PORT = 8765
HEALTH = {"status": "ok", "service": "traccar-manager"}
BRAND_ICON = "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 64 64\"><rect width=\"64\" height=\"64\" rx=\"14\" fill=\"#0d1728\"/><path d=\"M32 7C21 7 12 16 12 27c0 15 20 31 20 31s20-16 20-31C52 16 43 7 32 7Z\" fill=\"none\" stroke=\"#54d7e8\" stroke-width=\"4\"/><circle cx=\"32\" cy=\"26\" r=\"7\" fill=\"none\" stroke=\"#54d7e8\" stroke-width=\"4\"/></svg>".encode('utf-8')
SESSION_COOKIE = "tm_session"
COOKIE_PATH = "/manager/"
COOKIE_MAX_AGE = 900
_TOKEN_COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
PAGE = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Geocontrol GPS · Traccar Manager</title>
  <link rel="icon" type="image/svg+xml" href="/manager/brand-icon.svg">
  <!-- Manager Web -->
  <style>
    :root{color-scheme:dark;--bg:#080d18;--card:#121c2d;--card2:#0f1726;--border:rgba(164,185,220,.14);--text:#edf3ff;--muted:#91a0b9;--cyan:#54d7e8;--green:#57d49a;--amber:#f4bd61;--danger:#ff8585}
    *{box-sizing:border-box}html{min-width:320px;background:var(--bg)}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 12% 0%,rgba(34,92,132,.22),transparent 38%),var(--bg);color:var(--text);font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
    main{width:min(1120px,calc(100% - 48px));margin:auto;padding:32px 0 28px}.brand{display:flex;align-items:center;gap:15px;margin-bottom:28px}.mark{display:grid;place-items:center;width:58px;height:58px;border:1px solid rgba(84,215,232,.22);border-radius:15px;background:rgba(84,215,232,.06);overflow:hidden}.brand-symbol{width:44px;height:44px;color:var(--cyan);display:block}.brand-name{display:flex;align-items:baseline;gap:7px;margin:0;font-size:clamp(22px,3vw,29px);font-weight:800;line-height:1.05;letter-spacing:-.035em}.brand-name span{color:#edf3ff}.brand-name b{color:#39a9ff}.brand-slogan{margin:5px 0 0;color:#a8b5ca;font-size:11px;letter-spacing:.06em}.brand-copy{min-width:0}.eyebrow{margin:0 0 5px;color:var(--cyan);font-size:10px;font-weight:800;letter-spacing:.16em;text-transform:uppercase}h1{margin:0;font-size:clamp(22px,3vw,29px);line-height:1.15}h2{margin:0 0 12px;font-size:19px;letter-spacing:-.02em}h3{margin:0 0 7px;font-size:16px}p{line-height:1.5}.muted{color:var(--muted);margin:5px 0 0;font-size:13px}.status{color:var(--amber);font-weight:700}.phase-banner{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:0 0 18px;padding:15px 17px;border:1px solid rgba(87,212,154,.24);border-radius:14px;background:linear-gradient(135deg,rgba(87,212,154,.10),rgba(84,215,232,.05))}.phase-copy{min-width:0}.phase-label{margin:0;color:var(--green);font-size:10px;font-weight:800;letter-spacing:.14em;text-transform:uppercase}.phase-title{margin:3px 0 0;font-size:15px;font-weight:750}.phase-badge{flex:0 0 auto;padding:7px 10px;border:1px solid rgba(87,212,154,.3);border-radius:999px;background:rgba(87,212,154,.08);color:#9aebc2;font-size:10px;font-weight:800;white-space:nowrap}.notice,.card{margin-top:12px;padding:17px 18px;border:1px solid var(--border);border-radius:14px;background:linear-gradient(150deg,#131d2f,#0e1523)}
    .login-shell{display:grid;grid-template-columns:minmax(0,1fr) minmax(340px,440px);gap:34px;align-items:center;min-height:430px;padding:28px 0 42px}.login-context{max-width:520px;padding:10px 4px}.login-context h2{font-size:clamp(25px,4vw,38px);margin:7px 0 10px;letter-spacing:-.035em}.login-context>.muted{max-width:480px;font-size:14px}.login-assurance{display:flex;flex-wrap:wrap;gap:8px;margin-top:22px}.login-assurance span{padding:7px 10px;border:1px solid rgba(87,212,154,.2);border-radius:999px;background:rgba(87,212,154,.055);color:#a9e9c8;font-size:10px;font-weight:750}.login-card{padding:24px;border:1px solid rgba(164,185,220,.18);border-radius:18px;background:linear-gradient(155deg,rgba(19,29,47,.98),rgba(11,18,31,.98));box-shadow:0 24px 70px rgba(0,0,0,.28)}.login-card-head{display:flex;align-items:center;gap:12px;padding-bottom:15px;border-bottom:1px solid var(--border)}.login-card-head h2{margin:0;font-size:20px}.login-lock{display:grid;place-items:center;width:44px;height:44px;border:1px solid rgba(84,215,232,.24);border-radius:11px;background:rgba(84,215,232,.06);overflow:hidden}.login-lock{color:#9aebc2;font-size:20px;font-weight:800}.login-card label{margin-top:14px}.login-card input{min-height:46px;background:#0a1220}.login-card button{width:100%;min-height:46px;margin-top:18px;background:rgba(84,215,232,.13)}.login-foot{margin:14px 0 0;color:var(--muted);font-size:10px;text-align:center}.login-card .error{margin:12px 0 0}.login-shell[hidden]{display:none!important}#dashboard-panel{display:grid;gap:13px}.dashboard-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:16px}.dashboard-heading h2{margin:0}.dashboard-live{padding:6px 9px;border:1px solid rgba(87,212,154,.24);border-radius:999px;background:rgba(87,212,154,.07);color:#9aebc2;font-size:10px;font-weight:800}.manager-nav{display:flex;gap:6px;overflow-x:auto;padding:4px;border:1px solid var(--border);border-radius:12px;background:rgba(10,17,29,.72);scrollbar-width:none}.manager-nav::-webkit-scrollbar{display:none}.manager-nav .nav-item{flex:0 0 auto;min-height:34px;margin:0;padding:0 12px;border-color:transparent;background:transparent;color:var(--muted);font-size:10px}.manager-nav .nav-item.active{border-color:rgba(84,215,232,.28);background:rgba(84,215,232,.10);color:var(--cyan)}.manager-shell{display:grid;grid-template-columns:190px minmax(0,1fr);gap:14px;align-items:start}.manager-sidebar{position:sticky;top:12px;padding:12px;border:1px solid var(--border);border-radius:15px;background:rgba(10,17,29,.94)}.sidebar-brand{display:flex;align-items:center;gap:9px;padding:5px 6px 13px;border-bottom:1px solid var(--border)}.sidebar-brand>span{display:grid;place-items:center;width:30px;height:30px;border:1px solid rgba(84,215,232,.28);border-radius:9px;color:var(--cyan);font-size:10px;font-weight:900}.sidebar-brand strong{font-size:12px}.manager-sidebar .manager-nav{display:grid;gap:4px;margin-top:10px;padding:0;border:0;background:none;overflow:visible}.manager-sidebar .nav-item{width:100%;justify-content:flex-start;gap:9px;min-height:38px;padding:0 10px;border-radius:9px}.manager-sidebar .nav-item b{width:16px;text-align:center;font-size:13px}.manager-content{position:relative;display:grid;gap:13px;min-width:0}.manager-topbar{display:flex;align-items:center;gap:7px;min-height:46px;padding:6px 8px;border:1px solid var(--border);border-radius:13px;background:rgba(10,17,29,.82)}.topbar-spacer{flex:1}.icon-button,.notification-button,.account-chip{min-height:32px;margin:0;padding:0 10px}.notification-button{position:relative;font-size:16px}.notification-button>span{position:absolute;top:-5px;right:-5px;min-width:17px;height:17px;padding:0 4px;border-radius:9px;background:var(--danger);color:#fff;font-size:9px;line-height:17px}.account-chip{gap:6px;color:#cbd5e5}.account-chip span{color:#57d49a}.notification-drawer{position:absolute;z-index:20;top:52px;right:0;width:min(390px,calc(100vw - 32px));padding:13px;border:1px solid var(--border);border-radius:13px;background:#0d1727;box-shadow:0 20px 55px rgba(0,0,0,.38)}.notification-drawer>div:first-child{display:flex;align-items:center;justify-content:space-between}.notification-drawer>div:first-child button{min-height:28px;margin:0;padding:0 9px}.notification-drawer .alert-item{margin-top:6px}.full-card{grid-column:1/-1}.section-intro{display:flex;align-items:flex-start;justify-content:space-between;gap:15px}.section-intro h3{margin:0}.account-avatar{display:grid;place-items:center;width:42px;height:42px;border:1px solid rgba(84,215,232,.28);border-radius:50%;color:var(--cyan);font-weight:900}.account-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:14px}.account-grid>div{padding:11px;border:1px solid var(--border);border-radius:10px;background:rgba(8,13,24,.32)}.account-grid span,.account-grid strong{display:block}.account-grid span{color:var(--muted);font-size:9px;text-transform:uppercase}.account-grid strong{margin-top:4px;font-size:11px}.sidebar-collapsed .manager-shell{grid-template-columns:66px minmax(0,1fr)}.sidebar-collapsed .sidebar-brand strong,.sidebar-collapsed .manager-sidebar .nav-item span{display:none}.sidebar-collapsed .manager-sidebar .nav-item{justify-content:center;padding:0}.sidebar-collapsed .sidebar-brand{justify-content:center}.alerts-panel{padding:15px 16px;border:1px solid rgba(87,212,154,.20);border-radius:14px;background:linear-gradient(135deg,rgba(87,212,154,.06),rgba(84,215,232,.025))}.alerts-head{display:flex;align-items:center;justify-content:space-between;gap:14px}.alerts-head h3{margin:0}.alerts-badge{padding:6px 9px;border:1px solid var(--border);border-radius:999px;color:#cbd5e5;font-size:10px;font-weight:800}.alerts-badge.ok{border-color:rgba(87,212,154,.28);background:rgba(87,212,154,.08);color:#9aebc2}.alerts-badge.warn{border-color:rgba(244,189,97,.28);background:rgba(244,189,97,.08);color:#f4d39a}.alerts-badge.bad{border-color:rgba(255,133,133,.28);background:rgba(255,133,133,.08);color:#ffb0b0}.alerts-list{display:grid;gap:6px;margin-top:11px}.alert-item{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 10px;border:1px solid rgba(164,185,220,.09);border-radius:9px;background:rgba(8,13,24,.32);font-size:10px}.alert-item strong{color:#dce6f7}.alert-item span{color:var(--muted);text-align:right}.alert-item.ok strong{color:#9aebc2}.alert-item.warn strong{color:#f4d39a}.alert-item.bad strong{color:#ffb0b0}.capacity-card{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 14px;border:1px solid rgba(84,215,232,.18);border-radius:12px;background:rgba(84,215,232,.035)}.capacity-card span,.capacity-card strong{display:block}.capacity-card span{color:var(--muted);font-size:9px;letter-spacing:.08em}.capacity-card strong{margin-top:3px;color:#b8eef3;font-size:12px}.capacity-card strong.warn{color:#f4d39a}.capacity-card strong.bad{color:#ffb0b0}.capacity-card p{margin:0;color:var(--muted);font-size:10px;text-align:right}.health-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.health-strip>div{padding:11px 12px;border:1px solid var(--border);border-radius:12px;background:rgba(17,26,43,.72)}.health-strip span,.health-strip strong{display:block}.health-strip span{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.08em}.health-strip strong{margin-top:3px;font-size:11px;color:#cbd5e5}.health-strip strong.ok{color:#9aebc2}.health-strip strong.warn{color:#f4d39a}.health-strip strong.bad{color:#ffb0b0}.audit-panel{padding:15px 16px;border:1px solid var(--border);border-radius:14px;background:rgba(15,23,38,.82)}.audit-panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.audit-panel-head h3{margin:0}.audit-panel-head>strong{color:var(--cyan);font-size:10px;white-space:nowrap}.audit-events{display:grid;gap:6px;margin-top:12px}.audit-event{display:grid;grid-template-columns:145px minmax(120px,1fr) 100px minmax(140px,1.2fr);gap:10px;align-items:center;padding:8px 10px;border:1px solid rgba(164,185,220,.09);border-radius:9px;background:rgba(8,13,24,.35);font-size:10px}.audit-event time,.audit-event .reason{color:var(--muted)}.audit-event .event{color:#cbd5e5;font-weight:700}.audit-event .result{font-weight:800}.audit-event .result.ok{color:#9aebc2}.audit-event .result.warn{color:#f4d39a}.audit-event .result.bad{color:#ffb0b0}.capacity-center{grid-column:1/-1}.capacity-center-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.capacity-center-head>strong{color:#9aebc2;font-size:12px}.capacity-breakdown{display:grid;gap:8px;margin-top:13px}.capacity-row{display:grid;grid-template-columns:125px minmax(100px,1fr) 82px 54px;gap:9px;align-items:center;font-size:10px}.capacity-row>span:first-child{color:#cbd5e5;font-weight:700}.capacity-row .meter{height:6px}.capacity-row strong,.capacity-row em{font-style:normal;text-align:right;font-variant-numeric:tabular-nums}.capacity-row strong{color:#dce6f7}.capacity-row em{color:var(--muted)}.growth-diagnosis{display:flex;justify-content:space-between;gap:12px;margin-top:11px;padding:9px 10px;border:1px solid rgba(84,215,232,.14);border-radius:9px;background:rgba(84,215,232,.035);font-size:10px}.growth-diagnosis strong{color:#b8eef3}.growth-diagnosis span{color:var(--muted);text-align:right}.trends-card{grid-column:1/-1}.trends-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.trend-tabs{display:flex;gap:5px}.trend-tab{min-height:30px;margin:0;padding:0 10px;font-size:9px}.trend-tab.active{background:rgba(84,215,232,.18);color:#b8eef3}.trend-legend{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0 7px;color:var(--muted);font-size:9px}.trend-legend span:before{content:'— ';color:var(--cyan)}.trend-chart{height:155px;padding:7px;border:1px solid var(--border);border-radius:11px;background:rgba(8,13,24,.35)}.trend-chart svg{width:100%;height:100%;overflow:visible}.trend-line{fill:none;stroke:currentColor;stroke-width:2;vector-effect:non-scaling-stroke}.trend-disk{color:#54d7e8}.trend-memory{color:#57d49a}.trend-logs{color:#f4bd61}.trend-db{color:#b39cff}.services-grid{display:grid;gap:7px;margin-top:12px}.service-row{display:grid;grid-template-columns:minmax(110px,1fr) 90px 90px minmax(150px,1.4fr);gap:9px;align-items:center;padding:9px 10px;border:1px solid rgba(164,185,220,.10);border-radius:10px;background:rgba(8,13,24,.35);font-size:10px}.service-row .service-name{font-weight:800;color:#dce6f7}.service-row .service-status{font-weight:800;color:#9aebc2}.service-row .service-status.bad{color:#ffb0b0}.service-row .service-meta{color:var(--muted)}.dashboard-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}.card{position:relative;overflow:hidden}.card:after{position:absolute;top:-55px;right:-45px;width:125px;height:125px;border:1px solid var(--cyan);border-radius:50%;content:"";opacity:.06;pointer-events:none}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:10px 0 18px;padding:11px 14px;border:1px solid var(--border);border-radius:11px;background:rgba(17,26,43,.75)}label{display:block;margin:15px 0 6px;color:#cbd5e5;font-size:11px;font-weight:700}input{width:100%;padding:11px 12px;border:1px solid var(--border);border-radius:11px;background:#0b1321;color:var(--text);font:inherit;outline:none}input:focus{border-color:rgba(84,215,232,.55);box-shadow:0 0 0 3px rgba(84,215,232,.08)}button{display:inline-flex;align-items:center;justify-content:center;min-height:42px;margin-top:13px;padding:0 15px;border:1px solid rgba(84,215,232,.32);border-radius:11px;background:rgba(84,215,232,.1);color:var(--cyan);font:inherit;font-weight:700;cursor:pointer}button:hover{background:rgba(84,215,232,.18)}button:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}button:disabled{opacity:.55;cursor:wait}.secondary{margin-top:0;border-color:var(--border);background:rgba(145,160,185,.08);color:#cbd5e5}.error{color:#ffc1c1}.notice.error{border-color:rgba(255,112,112,.3);background:rgba(255,112,112,.08)}.safety-flow{display:flex;flex-wrap:wrap;gap:7px;margin:12px 0}.safety-flow span{padding:5px 9px;border:1px solid rgba(84,215,232,.22);border-radius:999px;background:rgba(84,215,232,.07);color:#b8eef3;font-size:10px;font-weight:700}.safety-flow .done{border-color:rgba(87,212,154,.28);background:rgba(87,212,154,.08);color:#9aebc2}.safety-flow .pending{border-color:rgba(244,189,97,.28);background:rgba(244,189,97,.08);color:#f4d39a}.safety-flow .locked{border-color:rgba(255,133,133,.25);background:rgba(255,133,133,.07);color:#ffb0b0}.maintenance-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:13px}.maintenance-summary div{padding:10px;border:1px solid var(--border);border-radius:11px;background:rgba(17,26,43,.75)}.maintenance-summary span,.maintenance-summary strong{display:block}.maintenance-summary span{color:var(--muted);font-size:10px}.maintenance-summary strong{margin-top:3px;font-size:15px;font-variant-numeric:tabular-nums}.metric-charts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:13px}.metric-chart{padding:12px;border:1px solid var(--border);border-radius:12px;background:rgba(8,13,24,.35)}.metric-chart-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:8px}.metric-chart-head span{color:var(--muted);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em}.metric-chart-head strong{font-size:16px;font-variant-numeric:tabular-nums}.meter{height:7px;overflow:hidden;border-radius:999px;background:rgba(145,160,185,.13)}.meter>span{display:block;width:0;height:100%;border-radius:inherit;background:var(--cyan);transition:width .35s ease}.meter.warning>span{background:var(--amber)}.meter.critical>span{background:var(--danger)}.metric-foot{display:flex;justify-content:space-between;gap:8px;margin-top:7px;color:var(--muted);font-size:10px}.protection-bars{display:grid;gap:9px;margin-top:11px}.protection-row{display:grid;grid-template-columns:minmax(95px,.8fr) minmax(110px,1.5fr) auto;align-items:center;gap:8px}.protection-row>span{color:#cbd5e5;font-size:11px}.protection-row>strong{font-size:10px;font-variant-numeric:tabular-nums;color:var(--muted)}#maintenance-candidates{margin:12px 0 0;padding-left:20px;color:#d3dced;font-size:12px}#maintenance-candidates li{padding:5px 0;border-bottom:1px solid rgba(164,185,220,.08)}[hidden]{display:none!important}noscript{display:block;margin-top:15px;color:#ffc1c1}
body.authenticated{background:#eef2f6;color:#162033}body.authenticated main{width:100%;max-width:none;padding:0}body.authenticated>main>.brand,body.authenticated>main>.phase-banner,body.authenticated>main>#session-bar,body.authenticated>main>#boot-status{display:none!important}body.authenticated #dashboard-panel{min-height:100vh;gap:0}body.authenticated .dashboard-heading{position:fixed;z-index:8;top:0;left:230px;right:0;height:72px;padding:0 28px;background:#fff;border-bottom:1px solid #e5eaf0;align-items:center}body.authenticated .dashboard-heading .eyebrow{display:none}body.authenticated .dashboard-heading h2{color:#141b28;font-size:20px}body.authenticated .dashboard-live{border-color:#d7efe5;background:#f0faf6;color:#268b65}body.authenticated .manager-shell{grid-template-columns:230px minmax(0,1fr);gap:0;min-height:100vh}body.authenticated .manager-sidebar{position:fixed;z-index:15;inset:0 auto 0 0;width:230px;padding:28px 18px;border:0;border-radius:0;background:#111722;color:#fff}body.authenticated .sidebar-brand{padding:0 7px 26px;border-bottom:0}body.authenticated .sidebar-brand>span{width:36px;height:36px;border:0;border-radius:50%;background:#fff;color:#111722}body.authenticated .sidebar-brand strong{font-size:16px;color:#fff}body.authenticated .manager-sidebar .manager-nav{gap:7px;margin-top:34px}body.authenticated .manager-sidebar .nav-item{min-height:44px;border:0;color:#aeb7c5;font-size:12px}body.authenticated .manager-sidebar .nav-item.active{background:#202733;color:#fff}body.authenticated .manager-content{grid-column:2;padding:94px 28px 30px;gap:16px;min-width:0}body.authenticated .manager-topbar{position:fixed;z-index:10;top:0;right:0;left:230px;height:72px;padding:0 28px;border:0;border-radius:0;background:transparent;pointer-events:none}body.authenticated .manager-topbar button{pointer-events:auto}body.authenticated .manager-topbar #sidebar-toggle{display:none}body.authenticated .notification-button,body.authenticated .account-chip{border-color:#e5eaf0;background:#f8fafc;color:#253044}body.authenticated .account-chip span{color:#29a879}body.authenticated .notification-drawer{position:fixed;top:66px;right:28px;background:#fff;border-color:#e1e6ed;color:#172033;box-shadow:0 18px 45px rgba(21,31,48,.15)}body.authenticated .card,body.authenticated .alerts-panel,body.authenticated .capacity-card,body.authenticated .health-strip>div,body.authenticated .audit-panel{border-color:#e1e6ed;background:#fff;color:#172033;box-shadow:0 1px 2px rgba(21,31,48,.025)}body.authenticated .card:after{display:none}body.authenticated .muted,body.authenticated .metric-foot,body.authenticated .capacity-card p,body.authenticated .alert-item span{color:#7e8999}body.authenticated .executive-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}body.authenticated .executive-kpis article{display:flex;align-items:flex-start;gap:12px;min-height:116px;padding:18px;border:1px solid #e1e6ed;border-radius:9px;background:#fff}body.authenticated .kpi-icon{display:grid;place-items:center;width:38px;height:38px;border-radius:7px;background:#f1f4f7;color:#172033;font-size:17px}body.authenticated .executive-kpis div{min-width:0}body.authenticated .executive-kpis small,body.authenticated .executive-kpis strong,body.authenticated .executive-kpis em{display:block}body.authenticated .executive-kpis small{color:#929cab;font-size:10px}body.authenticated .executive-kpis strong{margin-top:5px;color:#141b28;font-size:18px;font-style:normal;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}body.authenticated .executive-kpis em{margin-top:4px;color:#98a2b1;font-size:9px;font-style:normal}body.authenticated .dashboard-grid{gap:14px}body.authenticated .metric-chart,body.authenticated .maintenance-summary div,body.authenticated .alert-item,body.authenticated .service-row,body.authenticated .growth-diagnosis,body.authenticated .trend-chart{border-color:#e7ebf0;background:#f8fafc}body.authenticated .metric-chart-head strong,body.authenticated .maintenance-summary strong,body.authenticated .alert-item strong,body.authenticated .service-row .service-name,body.authenticated .capacity-row strong{color:#1d2736}body.authenticated .meter{background:#e9edf2}body.authenticated .alerts-panel{grid-column:span 1}body.authenticated .capacity-card{grid-column:span 1}body.authenticated .health-strip{grid-column:1/-1}body.authenticated .dashboard-grid>[data-view="summary"]{min-height:180px}body.authenticated .eyebrow{color:#298fa2}body.authenticated{--ui-text:#172033;--ui-title:#111827;--ui-muted:#667085;--ui-soft:#98a2b3;--ui-line:#e4e8ee;--ui-surface:#fff;--ui-canvas:#f3f5f8;--ui-blue:#238da2;--ui-green:#17845e;--ui-amber:#a96912;--ui-red:#c13b3b}body.authenticated .dashboard-overview{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(280px,.8fr);gap:14px}body.authenticated .dashboard-overview>article{padding:20px;border:1px solid var(--ui-line);border-radius:10px;background:var(--ui-surface)}body.authenticated .overview-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}body.authenticated .overview-head small{color:var(--ui-soft);font-size:9px;font-weight:750;letter-spacing:.08em}body.authenticated .overview-head h3{margin:3px 0 0;color:var(--ui-title);font-size:15px}body.authenticated .text-action{min-height:28px;margin:0;padding:0;border:0;background:none;color:var(--ui-blue);font-size:10px}body.authenticated .overview-meters{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:24px}body.authenticated .overview-meters span,body.authenticated .overview-meters strong{display:block}body.authenticated .overview-meters span{color:var(--ui-muted);font-size:10px}body.authenticated .overview-meters strong{margin-top:5px;color:var(--ui-title);font-size:25px}body.authenticated .overview-track{height:8px;margin-top:10px;overflow:hidden;border-radius:999px;background:#edf0f4}body.authenticated .overview-track i{display:block;width:0;height:100%;border-radius:inherit;background:#222b38;transition:width .3s ease}body.authenticated #overview-resource-detail{margin:17px 0 0;color:var(--ui-muted);font-size:10px}body.authenticated .overview-services-list{display:grid;gap:9px;margin-top:18px}body.authenticated .overview-service{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid #edf0f3;color:var(--ui-text);font-size:10px}body.authenticated .overview-service:last-child{border:0}body.authenticated .overview-service b{color:var(--ui-green);font-size:9px}body.authenticated .alerts-panel{border-color:var(--ui-line);background:var(--ui-surface)}body.authenticated .alerts-head h3,body.authenticated .section-intro h3,body.authenticated .audit-panel-head h3,body.authenticated .card h3{color:var(--ui-title)}body.authenticated .alerts-badge.ok{border-color:#cce8dc;background:#eef8f4;color:var(--ui-green)}body.authenticated .alerts-badge.warn{border-color:#f1dfbf;background:#fff8ec;color:var(--ui-amber)}body.authenticated .alerts-badge.bad{border-color:#f0caca;background:#fff1f1;color:var(--ui-red)}body.authenticated .alert-item.ok strong,body.authenticated .health-strip strong.ok{color:var(--ui-green)}body.authenticated .alert-item.warn strong,body.authenticated .health-strip strong.warn{color:var(--ui-amber)}body.authenticated .alert-item.bad strong,body.authenticated .health-strip strong.bad{color:var(--ui-red)}body.authenticated .status{color:var(--ui-amber)}body.authenticated .capacity-card strong{color:var(--ui-blue)}body.authenticated .account-grid>div{border-color:var(--ui-line);background:#fafbfc}body.authenticated .account-grid span{color:var(--ui-muted)}body.authenticated .account-grid strong{color:var(--ui-title)}body.authenticated .secondary{border-color:#dfe4ea;background:#f8fafc;color:#344054}body.authenticated label{color:#344054}body.authenticated input{border-color:#d8dee7;background:#fff;color:#172033}    @media(max-width:720px){body.authenticated .dashboard-overview{grid-template-columns:1fr}body.authenticated .dashboard-overview>article{padding:15px}body.authenticated .overview-meters{gap:14px;margin-top:17px}body.authenticated .overview-meters strong{font-size:20px}body.authenticated.sidebar-open:after{content:"";position:fixed;z-index:14;inset:0;background:rgba(17,24,39,.48)}body.authenticated .manager-sidebar{z-index:16;width:min(80vw,280px)}body.authenticated .executive-kpis article{min-height:96px}body.authenticated .kpi-icon{width:32px;height:32px;font-size:14px}body.authenticated .executive-kpis small{font-size:9px}body.authenticated .executive-kpis em{font-size:8px}body.authenticated main{width:100%;padding:0}body.authenticated .dashboard-heading{left:0;height:64px;padding:0 70px 0 16px}body.authenticated .dashboard-heading h2{font-size:18px}body.authenticated .dashboard-live{display:none}body.authenticated .manager-shell{display:block}body.authenticated .manager-content{padding:82px 14px 22px}body.authenticated .manager-topbar{left:0;height:64px;padding:0 14px}body.authenticated .manager-topbar #sidebar-toggle{display:inline-flex;position:relative;z-index:20}body.authenticated .manager-sidebar{display:block;transform:translateX(-105%);transition:transform .2s ease;width:250px;padding:22px 16px;box-shadow:12px 0 35px rgba(0,0,0,.22)}body.authenticated.sidebar-open .manager-sidebar{transform:translateX(0)}body.authenticated .sidebar-brand{display:flex}body.authenticated .manager-sidebar .manager-nav{display:grid;overflow:visible;margin-top:24px}body.authenticated .manager-sidebar .nav-item{width:100%;padding:0 10px;justify-content:flex-start}body.authenticated .manager-sidebar .nav-item span{display:inline}body.authenticated .executive-kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}body.authenticated .executive-kpis article{min-height:105px;padding:13px;gap:9px}body.authenticated .executive-kpis strong{font-size:15px}body.authenticated .alerts-panel,body.authenticated .capacity-card{grid-column:1/-1}body.authenticated .notification-drawer{top:60px;right:10px;width:calc(100vw - 20px)}body.authenticated .account-chip{font-size:0;padding:0 10px}body.authenticated .account-chip span{font-size:12px}main{width:calc(100% - 28px);padding:20px 0}.brand{margin-bottom:14px}.login-shell{grid-template-columns:1fr;gap:18px;min-height:0;padding:18px 0 28px}.login-context{padding:0 2px}.login-context h2{font-size:25px;margin-top:5px}.login-context>.muted{font-size:12px}.login-assurance{margin-top:14px;gap:6px}.login-assurance span{padding:5px 8px;font-size:9px}.login-card{padding:18px;border-radius:15px}.login-card-head{padding-bottom:12px}.login-card input{min-height:48px}.phase-banner{align-items:flex-start;flex-direction:column;gap:10px}.mark{width:48px;height:48px}.brand-symbol{width:37px;height:37px}.brand-name{font-size:22px}.brand-slogan{font-size:10px}.health-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.dashboard-heading{align-items:flex-start}.dashboard-grid{grid-template-columns:1fr}.maintenance-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.metric-charts{grid-template-columns:1fr}.protection-row{grid-template-columns:92px 1fr auto}.toolbar{align-items:flex-start}.audit-event{grid-template-columns:1fr 1fr;gap:4px 8px}.audit-event .reason{grid-column:1/-1}.audit-panel-head{flex-direction:column;gap:6px}.capacity-row{grid-template-columns:100px 1fr 70px 44px}.growth-diagnosis{flex-direction:column;gap:3px}.growth-diagnosis span{text-align:left}.service-row{grid-template-columns:1fr 1fr}.service-row .service-meta:last-child{grid-column:1/-1}.alerts-head{align-items:flex-start}.capacity-card{align-items:flex-start;flex-direction:column;gap:4px}.capacity-card p{text-align:left}.alert-item{align-items:flex-start;flex-direction:column;gap:2px}.alert-item span{text-align:left}.card{padding:14px}.notice{padding:13px}.manager-shell{grid-template-columns:1fr}.manager-sidebar{position:static;padding:7px}.sidebar-brand{display:none}.manager-sidebar .manager-nav{display:flex;overflow-x:auto;margin:0}.manager-sidebar .nav-item{width:auto;min-width:44px;padding:0 10px}.manager-sidebar .nav-item span{display:none}.manager-topbar{position:sticky;top:5px;z-index:12}.account-grid{grid-template-columns:1fr}.dashboard-heading{margin-bottom:2px}.sidebar-collapsed .manager-shell{grid-template-columns:1fr}}
body.authenticated .ui-icon{display:block;width:20px;height:20px;flex:0 0 20px;stroke:currentColor;stroke-width:1.8}body.authenticated .manager-sidebar .nav-item b{display:grid;place-items:center;width:22px;height:22px}body.authenticated .manager-sidebar .nav-item b .ui-icon{width:19px;height:19px}body.authenticated .kpi-icon .ui-icon{width:20px;height:20px}body.authenticated .icon-button .ui-icon,body.authenticated .notification-button .ui-icon{width:19px;height:19px}body.authenticated .account-chip>span{display:grid;place-items:center}body.authenticated .account-chip .ui-icon{width:17px;height:17px}body.authenticated .sidebar-brand strong{display:flex;align-items:baseline;gap:4px}body.authenticated .sidebar-brand strong b{font:inherit;color:#fff}body.authenticated .sidebar-brand strong em{font-style:normal;color:#54d7e8;font-weight:800}
@media(max-width:720px){body.authenticated .dashboard-heading{padding:0 116px 0 72px}body.authenticated .manager-topbar{padding:0 14px}body.authenticated .manager-topbar #sidebar-toggle{position:absolute;left:14px;top:12px;width:40px;height:40px;min-height:40px;padding:0;border:1px solid #263244;border-radius:9px;background:#172131;color:#f5f8fc;box-shadow:none}body.authenticated .manager-topbar #sidebar-toggle:hover{background:#202c3e}body.authenticated .notification-button,body.authenticated .account-chip{border-color:#263244;background:#172131;color:#f5f8fc}body.authenticated .account-chip span{color:#58d3ad}body.authenticated .dashboard-heading h2{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}body.authenticated .sidebar-brand strong{font-size:15px}}
body.authenticated{--ui-blue:#17677a;--cyan:#17677a}body.authenticated .eyebrow,body.authenticated .text-action{color:#17677a}body.authenticated .manager-topbar #sidebar-toggle,body.authenticated .notification-button,body.authenticated .account-chip{border-color:transparent!important;background:transparent!important;color:#253044!important;box-shadow:none!important}body.authenticated .manager-topbar #sidebar-toggle:hover,body.authenticated .notification-button:hover,body.authenticated .account-chip:hover{background:#eef2f6!important}body.authenticated .account-chip span{color:#17677a!important}body.authenticated .notification-drawer>div:first-child button{border-color:#5d6979!important;background:#fff!important;color:#344054!important}body.authenticated .notification-drawer>div:first-child button:hover{border-color:#344054!important;background:#f2f4f7!important}body.authenticated .sidebar-brand strong em{color:#55c8d8}body.authenticated .account-subnav{display:grid;gap:6px;margin-top:18px;padding:6px;border:1px solid var(--ui-line);border-radius:10px;background:#f7f9fb}body.authenticated .account-subnav button{justify-content:flex-start;min-height:42px;margin:0;border:0;background:transparent;color:#4b5565}body.authenticated .account-subnav button.active{background:#fff;color:#17677a;box-shadow:0 1px 3px rgba(17,24,39,.08)}body.authenticated .account-tab-panels{margin-top:14px}body.authenticated .account-tab-panels>section{padding:18px;border:1px solid var(--ui-line);border-radius:10px;background:#fafbfc}body.authenticated .account-tab-panels h4{margin:0 0 12px;color:var(--ui-title)}body.authenticated .account-tab-panels button:not(.secondary){background:#17677a;color:#fff;border-color:#17677a}body.authenticated .logout-zone{margin-top:24px;padding-top:20px;border-top:1px solid #d7dde5}body.authenticated .logout-zone .secondary{margin-top:12px}body.authenticated .profile-avatar{position:relative;display:grid;place-items:center;width:58px;height:58px;margin:0;border:1px solid #72808f;border-radius:50%;overflow:hidden;color:#17677a;cursor:pointer;background:#fff}body.authenticated .profile-avatar img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;background:#fff}body.authenticated .profile-avatar span{font-size:17px;font-weight:800}body.authenticated .account-sections{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-top:18px}body.authenticated .account-sections section{padding:16px;border:1px solid var(--ui-line);border-radius:10px;background:#fafbfc}body.authenticated .account-sections h4{margin:0 0 10px;color:var(--ui-title);font-size:13px}body.authenticated .account-sections label{margin-top:10px}body.authenticated .profile-avatar{position:relative;display:grid;place-items:center;width:58px;height:58px;margin:0;border:1px solid #9ab7bf;border-radius:50%;overflow:hidden;color:#17677a;cursor:pointer}body.authenticated .profile-avatar img{width:100%;height:100%;object-fit:cover}body.authenticated .profile-avatar span{font-size:17px;font-weight:800}body.authenticated .account-sections button{background:#17677a;color:#fff;border-color:#17677a}body.authenticated #profile-status,body.authenticated #password-status{min-height:18px;margin-top:8px}@media(max-width:720px){body.authenticated .account-sections{grid-template-columns:1fr}}body.authenticated .account-drawer{top:66px;right:28px;width:min(330px,calc(100vw - 28px))}body.authenticated .account-drawer-profile{display:flex;align-items:center;gap:12px;padding:16px 2px;border-bottom:1px solid #e5e9ef}body.authenticated .account-drawer-profile>div:last-child{min-width:0}body.authenticated .account-drawer-profile strong,body.authenticated .account-drawer-profile span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}body.authenticated .account-drawer-profile strong{color:#172033}body.authenticated .account-drawer-profile span{margin-top:2px;color:#7e8999;font-size:11px}body.authenticated .account-drawer-avatar{position:relative;display:grid;place-items:center;width:42px;height:42px;flex:0 0 42px;overflow:hidden;border:1px solid #72808f;border-radius:50%;color:#17677a;font-weight:800}body.authenticated .account-drawer-avatar img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}body.authenticated .account-drawer-action{width:100%;justify-content:flex-start;margin:6px 0 0;border:0;background:transparent;color:#344054}body.authenticated .account-drawer-action:hover{background:#f2f4f7}@media(max-width:720px){body.authenticated .account-drawer{top:60px;right:10px;width:calc(100vw - 20px)}}body.authenticated .sidebar-overlay{display:none}@media(max-width:720px){body.authenticated .sidebar-overlay{display:block;position:fixed;z-index:14;inset:0;margin:0;padding:0;border:0;border-radius:0;background:rgba(17,24,39,.48);opacity:0;pointer-events:none;transition:opacity .2s ease}body.authenticated.sidebar-open .sidebar-overlay{opacity:1;pointer-events:auto}body.authenticated.sidebar-open:after{display:none}}html{background:#f3f5f8}body:not(.authenticated){background:#f3f5f8;color:#172033}body:not(.authenticated) main{width:min(420px,calc(100% - 36px));padding:72px 0 40px}body:not(.authenticated) .brand{justify-content:center;margin-bottom:28px}body:not(.authenticated) .mark{width:46px;height:46px;border-color:#d7e1e8;background:#fff}body:not(.authenticated) .brand-symbol{width:34px;height:34px;color:#17677a}body:not(.authenticated) .brand-name{font-size:24px}body:not(.authenticated) .brand-name span{color:#172033}body:not(.authenticated) .brand-name b{color:#17677a}body:not(.authenticated) .brand-slogan{color:#7e8999}body:not(.authenticated) .boot-clean{margin:80px auto 0;color:#7e8999;text-align:center;background:none;border:0}body:not(.authenticated) .login-shell{display:block;min-height:0;padding:0}body:not(.authenticated) .login-card{padding:28px;border:1px solid #e1e6ed;border-radius:14px;background:#fff;box-shadow:0 8px 30px rgba(21,31,48,.08)}body:not(.authenticated) .login-card-head{padding:0 0 8px;border:0}body:not(.authenticated) .login-card-head h2{color:#172033;font-size:24px}body:not(.authenticated) .login-card label{color:#344054}body:not(.authenticated) .login-card input{min-height:50px;border-color:#d8dee7;background:#fff;color:#172033}body:not(.authenticated) .login-card button{min-height:50px;border-color:#17677a;background:#17677a;color:#fff}body:not(.authenticated) .login-card .muted{color:#7e8999}body.authenticated .account-drawer{max-height:calc(100vh - 78px);overflow:auto;padding:18px}body.authenticated .account-drawer-action{display:inline-flex;width:auto;margin:10px 6px 8px 0;padding:0 12px;min-height:36px;border:1px solid #e1e6ed;border-radius:8px}body.authenticated .account-drawer-action.active{border-color:#b9d8df;background:#eef7f8;color:#17677a}body.authenticated #account-modal-content{margin-top:8px}body.authenticated #account-modal-content>section{padding:4px 0 0!important;border:0!important;background:#fff!important}body.authenticated #account-modal-content h4{display:none}body.authenticated #account-modal-content label{margin-top:10px}body.authenticated #account-modal-content input{min-height:42px;padding:9px 10px}body.authenticated #account-modal-content button{min-height:40px;margin-top:12px}body.authenticated #account-modal-content .account-grid{grid-template-columns:1fr 1fr;gap:6px}body.authenticated #account-modal-content .account-grid>div{padding:8px}body.authenticated #account-card{display:none!important}@media(max-width:720px){body:not(.authenticated) main{width:calc(100% - 36px);padding:52px 0 30px}body:not(.authenticated) .brand{justify-content:flex-start;margin-bottom:24px}body:not(.authenticated) .login-card{padding:22px}body.authenticated .account-drawer{max-height:calc(100vh - 72px)}body.authenticated #account-modal-content .account-grid{grid-template-columns:1fr 1fr}}body.authenticated .notification-drawer,body.authenticated .account-drawer{width:min(390px,calc(100vw - 32px));padding:18px;border-radius:13px}body.authenticated .notification-drawer>div:first-child,body.authenticated .account-drawer>div:first-child{min-height:40px}body.authenticated .notification-drawer>div:first-child button,body.authenticated .account-drawer>div:first-child button{width:40px;height:40px;min-height:40px;padding:0;border:1px solid #5d6979!important;border-radius:10px;background:#fff!important;color:#344054!important;font-size:18px}body.authenticated .notification-drawer .secondary[data-go-section]{min-height:42px;margin-top:12px;padding:0 16px}body.authenticated .account-drawer-footer{margin-top:20px;padding-top:16px;border-top:1px solid #e5e9ef}body.authenticated .danger-logout{width:100%;min-height:42px;margin:0;border:1px solid #e6b7b7;background:#fff5f5;color:#b42318}body.authenticated .danger-logout:hover{background:#feecec;border-color:#d88d8d}@media(max-width:720px){body.authenticated .notification-drawer,body.authenticated .account-drawer{top:60px;right:10px;width:calc(100vw - 20px);padding:18px}}@media(max-width:720px){
body.authenticated .dashboard-heading h2{font-size:22px}
body.authenticated .manager-content{padding:84px 16px 26px;gap:18px}
body.authenticated .executive-kpis{gap:11px}
body.authenticated .executive-kpis article{min-height:122px;padding:16px 14px;gap:11px;border-radius:11px}
body.authenticated .kpi-icon{width:42px;height:42px;flex:0 0 42px;border-radius:9px}
body.authenticated .kpi-icon .ui-icon{width:25px;height:25px}
body.authenticated .executive-kpis small{font-size:12px;line-height:1.25}
body.authenticated .executive-kpis strong{margin-top:7px;font-size:20px;line-height:1.2}
body.authenticated .executive-kpis em{margin-top:7px;font-size:11px;line-height:1.3}
body.authenticated .dashboard-overview{gap:16px}
body.authenticated .dashboard-overview>article{padding:20px;border-radius:12px}
body.authenticated .overview-head small{font-size:11px}
body.authenticated .overview-head h3{margin-top:5px;font-size:19px}
body.authenticated .text-action{font-size:13px;min-height:34px;padding:0 4px}
body.authenticated .overview-meters{gap:20px;margin-top:25px}
body.authenticated .overview-meters span{font-size:13px}
body.authenticated .overview-meters strong{margin-top:8px;font-size:27px}
body.authenticated .overview-track{height:9px;margin-top:13px}
body.authenticated .overview-chart>p{margin-top:19px;font-size:12px;line-height:1.5}
body.authenticated .overview-services-list{margin-top:20px}
body.authenticated .overview-service{min-height:62px;font-size:13px}
body.authenticated .overview-service b{font-size:12px}
body.authenticated .manager-topbar #sidebar-toggle{width:44px;height:44px;min-height:44px;top:10px}
body.authenticated .icon-button .ui-icon,body.authenticated .notification-button .ui-icon{width:24px;height:24px}
body.authenticated .notification-button,body.authenticated .account-chip{min-width:44px;min-height:44px;padding:0 10px}
body.authenticated .account-chip .ui-icon{width:22px;height:22px}
body.authenticated .notification-button>span{min-width:19px;height:19px;font-size:10px;line-height:19px}
body.authenticated .manager-sidebar .nav-item{min-height:50px;font-size:14px}
body.authenticated .manager-sidebar .nav-item b .ui-icon{width:22px;height:22px}
body.authenticated .sidebar-brand strong{font-size:17px}
}@media(max-width:720px){
body.authenticated{font-size:15px}
body.authenticated .eyebrow{font-size:12px;letter-spacing:.12em}
body.authenticated label{font-size:14px;margin-top:16px}
body.authenticated input{min-height:48px;font-size:16px}
body.authenticated button{font-size:14px}
body.authenticated .alerts-badge{font-size:12px;padding:7px 10px}
body.authenticated .alert-item{font-size:13px;line-height:1.45;padding:11px 12px}
body.authenticated .capacity-card span{font-size:12px}
body.authenticated .capacity-card strong{font-size:16px}
body.authenticated .capacity-card p{font-size:13px;line-height:1.45}
body.authenticated .health-strip>div{padding:14px}
body.authenticated .health-strip span{font-size:11px}
body.authenticated .health-strip strong{font-size:14px;margin-top:5px}
body.authenticated .audit-panel-head>strong{font-size:12px}
body.authenticated .audit-event{font-size:13px;line-height:1.4;padding:11px 12px}
body.authenticated .capacity-center-head>strong{font-size:14px}
body.authenticated .capacity-row{grid-template-columns:105px minmax(70px,1fr) 72px 48px;font-size:12px;gap:7px}
body.authenticated .capacity-row .meter{height:8px}
body.authenticated .growth-diagnosis{font-size:13px;line-height:1.45;padding:12px}
body.authenticated .trend-tab{min-height:38px;font-size:12px;padding:0 13px}
body.authenticated .trend-legend{font-size:12px;gap:10px}
body.authenticated .trend-chart{height:180px}
body.authenticated .service-row{font-size:13px;line-height:1.4;padding:12px}
body.authenticated .safety-flow span{font-size:12px;padding:7px 10px}
body.authenticated .maintenance-summary div{padding:13px}
body.authenticated .maintenance-summary span{font-size:12px}
body.authenticated .maintenance-summary strong{font-size:19px;margin-top:5px}
body.authenticated .metric-chart{padding:15px}
body.authenticated .metric-chart-head span{font-size:12px}
body.authenticated .metric-chart-head strong{font-size:20px}
body.authenticated .metric-foot{font-size:12px;line-height:1.4}
body.authenticated .protection-row{grid-template-columns:105px minmax(80px,1fr) auto;gap:9px}
body.authenticated .protection-row>span{font-size:13px}
body.authenticated .protection-row>strong{font-size:12px}
body.authenticated #maintenance-candidates{font-size:14px;line-height:1.45}
body.authenticated .account-grid span{font-size:11px}
body.authenticated .account-grid strong{font-size:14px}
body.authenticated .account-drawer-profile span{font-size:13px}
body.authenticated .account-drawer-action{font-size:14px;min-height:42px}
body.authenticated #account-modal-content label{font-size:14px}
body.authenticated #account-modal-content input{min-height:48px;font-size:16px}
body.authenticated .notification-drawer,body.authenticated .account-drawer{font-size:14px}
body.authenticated .notification-drawer .secondary[data-go-section]{font-size:14px}
body.authenticated .danger-logout{font-size:14px}
body.authenticated .section-intro h3,body.authenticated .audit-panel-head h3,body.authenticated .capacity-center-head h3,body.authenticated .trends-head h3{font-size:19px}
body.authenticated .muted{font-size:13px;line-height:1.45}
body.authenticated .notice{font-size:14px;line-height:1.5}
body.authenticated .card{font-size:14px}
body.authenticated .toolbar{font-size:14px}
body.authenticated .manager-sidebar .nav-item{font-size:15px}
body.authenticated .manager-sidebar .nav-item b .ui-icon{width:23px;height:23px}
body.authenticated .sidebar-brand strong{font-size:18px}
body:not(.authenticated) .brand-slogan{font-size:12px}
body:not(.authenticated) .login-card label{font-size:14px}
body:not(.authenticated) .login-card input{font-size:16px}
body:not(.authenticated) .login-card button{font-size:16px}
body:not(.authenticated) .login-foot{font-size:12px;line-height:1.45}
}body.authenticated .overview-ring-metric{display:grid;justify-items:center;gap:10px}body.authenticated .overview-ring-metric>span{color:var(--ui-muted)}body.authenticated .overview-ring{--progress:0;position:relative;display:grid;place-items:center;width:116px;height:116px;border-radius:50%;background:conic-gradient(#222b38 calc(var(--progress)*1%),#edf0f4 0)}body.authenticated .overview-ring:after{content:"";position:absolute;width:88px;height:88px;border-radius:50%;background:#fff}body.authenticated .overview-ring strong{position:relative;z-index:1;margin:0!important;font-size:25px!important} @media(max-width:720px){body.authenticated .overview-meters{align-items:start}body.authenticated .overview-ring{width:126px;height:126px}body.authenticated .overview-ring:after{width:96px;height:96px}body.authenticated .overview-ring strong{font-size:28px!important}body.authenticated .overview-ring-metric>span{font-size:14px!important}}
/* Geocontrol authenticated visual system */
body.authenticated{--ui-title:#172033;--ui-text:#344054;--ui-muted:#758195;--ui-line:#dfe5ec;--ui-soft:#f6f8fa;--ui-accent:#17677a;--ui-accent-soft:#edf6f7;--ui-success:#267a62;--ui-success-soft:#eef8f4;--ui-warning:#a56a16;--ui-warning-soft:#fff7e8;--ui-danger:#b42318;--ui-danger-soft:#fff1f0;--green:#267a62;--amber:#a56a16;--danger:#b42318;color:var(--ui-text)}
body.authenticated h2,body.authenticated h3,body.authenticated h4,body.authenticated strong{color:var(--ui-title)}
body.authenticated .muted,body.authenticated .metric-foot,body.authenticated .capacity-row em,body.authenticated .audit-event time,body.authenticated .audit-event .reason{color:var(--ui-muted)}
body.authenticated .card,body.authenticated .alerts-panel,body.authenticated .audit-panel,body.authenticated .health-strip>div{border-color:var(--ui-line);background:#fff}
body.authenticated .status{color:var(--ui-accent)}
body.authenticated .status:before{content:"";display:inline-block;width:7px;height:7px;margin-right:8px;border-radius:50%;background:currentColor;vertical-align:1px}
body.authenticated .audit-event{border-color:#e7ebf0;background:#f8fafb;color:var(--ui-text)}
body.authenticated .audit-event .event{color:#344054}
body.authenticated .audit-event .result.ok{color:var(--ui-success)}
body.authenticated .audit-event .result.warn{color:var(--ui-warning)}
body.authenticated .audit-event .result.bad{color:var(--ui-danger)}
body.authenticated .audit-panel-head>strong,body.authenticated .text-action,body.authenticated .capacity-center-head>strong{color:var(--ui-accent)}
body.authenticated .safety-flow span{border-color:#c8d9dd;background:#f3f8f9;color:#3d6670}
body.authenticated .safety-flow .done{border-color:#b8d9ce;background:var(--ui-success-soft);color:var(--ui-success)}
body.authenticated .safety-flow .pending{border-color:#ead3a9;background:var(--ui-warning-soft);color:var(--ui-warning)}
body.authenticated .safety-flow .locked{border-color:#ecc7c4;background:var(--ui-danger-soft);color:var(--ui-danger)}
body.authenticated .phase-label,body.authenticated .phase-badge{color:var(--ui-success)}
body.authenticated #maintenance-card>.status,body.authenticated #maintenance-card>p[style]{color:var(--ui-accent)!important}
body.authenticated #boundary-health{display:block;margin:14px 0;padding:12px 14px;border:1px solid #ead3a9;border-radius:10px;background:var(--ui-warning-soft);color:#7b5319!important;line-height:1.5}
body.authenticated .security-checks{border-color:#c8d9dd!important;background:#f7fafb!important;color:var(--ui-text)!important}
body.authenticated .security-checks strong{color:var(--ui-accent)!important}
body.authenticated .metric-chart,body.authenticated .maintenance-summary div,body.authenticated .account-grid>div{border-color:#e2e7ed;background:#f8fafb}
body.authenticated .metric-chart-head span,body.authenticated .protection-row>span{color:#667386}
body.authenticated .meter{background:#e8edf2}
body.authenticated .meter>span{background:var(--ui-accent)}
body.authenticated .meter.warning>span{background:var(--ui-warning)}
body.authenticated .meter.critical>span{background:var(--ui-danger)}
body.authenticated .capacity-row>span:first-child{color:#526071}
body.authenticated .capacity-row strong{color:var(--ui-title)}
body.authenticated .growth-diagnosis{border-color:#cddfe3;background:var(--ui-accent-soft)}
body.authenticated .growth-diagnosis strong{color:var(--ui-accent)}
body.authenticated .trend-tab{border-color:#cfd8e1;background:#fff;color:#526071}
body.authenticated .trend-tab.active{border-color:#9fc6ce;background:var(--ui-accent-soft);color:var(--ui-accent)}
body.authenticated .trend-legend{color:#667386}
body.authenticated .trend-legend span:before{color:currentColor}
body.authenticated .trend-chart{border-color:#e0e6ec;background:#f8fafb}
body.authenticated .trend-disk{color:#17677a}
body.authenticated .trend-memory{color:#3f7d8b}
body.authenticated .trend-logs{color:#7295a0}
body.authenticated .trend-db{color:#9ab0b7}
body.authenticated .service-row{border-color:#e4e9ef;background:#f8fafb}
body.authenticated .service-row .service-name{color:#344054}
body.authenticated .service-row .service-status{color:var(--ui-success)}
body.authenticated .service-row .service-status.bad{color:var(--ui-danger)}
body.authenticated .health-strip strong.ok,body.authenticated .alerts-badge.ok,body.authenticated .alert-item.ok strong{color:var(--ui-success)}
body.authenticated .health-strip strong.warn,body.authenticated .alerts-badge.warn,body.authenticated .alert-item.warn strong{color:var(--ui-warning)}
body.authenticated .health-strip strong.bad,body.authenticated .alerts-badge.bad,body.authenticated .alert-item.bad strong{color:var(--ui-danger)}
body.authenticated .alerts-badge.ok{border-color:#b8d9ce;background:var(--ui-success-soft)}
body.authenticated .alerts-badge.warn{border-color:#ead3a9;background:var(--ui-warning-soft)}
body.authenticated .alerts-badge.bad{border-color:#ecc7c4;background:var(--ui-danger-soft)}
body.authenticated .overview-service b{color:var(--ui-success)}
body.authenticated .overview-ring{background:conic-gradient(var(--ui-accent) calc(var(--progress)*1%),#e8edf2 0)}
body.authenticated .dashboard-live{border-color:#b8d9ce;background:var(--ui-success-soft);color:var(--ui-success)}
body.authenticated .notification-button>span{background:var(--ui-danger)}
body.authenticated .capacity-card{border-color:#cddfe3;background:var(--ui-accent-soft)}
body.authenticated .capacity-card strong{color:var(--ui-accent)}
body.authenticated .capacity-card strong.warn{color:var(--ui-warning)}
body.authenticated .capacity-card strong.bad{color:var(--ui-danger)}
body.authenticated .protection-row>strong{color:#667386}
body:not(.authenticated) #session-bar{display:none!important}body:not(.authenticated) .boot-spinner{display:grid;place-items:center;margin:34vh auto 0;width:44px;height:44px;border:0;background:transparent}.boot-spinner>span{display:block;width:28px;height:28px;border:3px solid #dce3e9;border-top-color:#17677a;border-radius:50%;animation:manager-spin .75s linear infinite}@keyframes manager-spin{to{transform:rotate(360deg)}}body:not(.authenticated):has(#boot-status:not([hidden])) .brand{display:none!important}@media(prefers-reduced-motion:reduce){.boot-spinner>span{animation-duration:1.5s}}    @media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;transition-duration:.01ms!important}}

    body.authenticated .growth-diagnosis{display:block}
    body.authenticated .growth-diagnosis>div{display:flex;justify-content:space-between;gap:12px}
    body.authenticated .growth-recommendation{margin:10px 0 0;padding-top:10px;border-top:1px solid var(--ui-line);color:var(--ui-muted);font-size:13px;line-height:1.5}
    @media(max-width:720px){body.authenticated .growth-diagnosis>div{display:block}body.authenticated .growth-diagnosis span{display:block;margin-top:4px}}

    body.authenticated .diagnostic-center{grid-column:1/-1}
    body.authenticated .diagnostic-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
    body.authenticated .diagnostic-head h3{margin:2px 0 0;color:var(--ui-title);font-size:19px}
    body.authenticated .diagnostic-risk{padding:7px 10px;border:1px solid #dfe4ea;border-radius:999px;background:#f8fafc;color:var(--ui-muted);font-size:12px;font-weight:750;white-space:nowrap}
    body.authenticated .diagnostic-risk.warn{border-color:#f1dfbf;background:#fff8ec;color:var(--ui-amber)}
    body.authenticated .diagnostic-risk.bad{border-color:#f0caca;background:#fff1f1;color:var(--ui-red)}
    body.authenticated .diagnostic-risk.ok{border-color:#cce8dc;background:#eef8f4;color:var(--ui-green)}
    body.authenticated .diagnostic-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:16px}
    body.authenticated .diagnostic-grid>div{padding:15px;border:1px solid var(--ui-line);border-radius:10px;background:#f8fafc}
    body.authenticated .diagnostic-grid small,body.authenticated .diagnostic-grid strong,body.authenticated .diagnostic-grid span{display:block}
    body.authenticated .diagnostic-grid small{color:var(--ui-soft);font-size:10px;font-weight:750;letter-spacing:.07em}
    body.authenticated .diagnostic-grid strong{margin-top:7px;color:var(--ui-title);font-size:17px}
    body.authenticated .diagnostic-grid span{margin-top:5px;color:var(--ui-muted);font-size:13px;line-height:1.45}
    body.authenticated .diagnostic-safety{margin:14px 0 0;color:var(--ui-muted);font-size:12px;line-height:1.5}
    @media(max-width:720px){body.authenticated .diagnostic-head{display:block}body.authenticated .diagnostic-risk{display:inline-block;margin-top:10px}body.authenticated .diagnostic-grid{grid-template-columns:1fr}body.authenticated .diagnostic-grid>div{padding:14px}body.authenticated .diagnostic-grid strong{font-size:18px}body.authenticated .diagnostic-grid span{font-size:14px}body.authenticated .diagnostic-safety{font-size:13px}}

    body.authenticated .capacity-forecast{grid-column:1/-1}
    body.authenticated .forecast-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
    body.authenticated .forecast-head h3{margin:2px 0 0;color:var(--ui-title);font-size:19px}
    body.authenticated .forecast-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:16px}
    body.authenticated .forecast-grid>div{padding:15px;border:1px solid var(--ui-line);border-radius:10px;background:#f8fafc}
    body.authenticated .forecast-grid small,body.authenticated .forecast-grid strong,body.authenticated .forecast-grid span{display:block}
    body.authenticated .forecast-grid small{color:var(--ui-soft);font-size:10px;font-weight:750;letter-spacing:.07em}
    body.authenticated .forecast-grid strong{margin-top:7px;color:var(--ui-title);font-size:22px}
    body.authenticated .forecast-grid span{margin-top:5px;color:var(--ui-muted);font-size:13px}
    @media(max-width:720px){body.authenticated .forecast-head{display:block}body.authenticated .forecast-grid{grid-template-columns:1fr}body.authenticated .forecast-grid>div{padding:14px}body.authenticated .forecast-grid strong{font-size:24px}body.authenticated .forecast-grid span{font-size:14px}}

    body.authenticated .incident-history{grid-column:1/-1}
    body.authenticated .incident-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
    body.authenticated .incident-head h3{margin:2px 0 0;font-size:19px}
    body.authenticated .incident-head>strong{color:var(--ui-accent);font-size:12px;white-space:nowrap}
    body.authenticated .incident-list{display:grid;gap:8px;margin-top:15px}
    body.authenticated .incident-row{display:grid;grid-template-columns:minmax(180px,.85fr) minmax(220px,1.35fr) 150px;gap:12px;align-items:center;padding:13px;border:1px solid var(--ui-line);border-radius:10px;background:#f8fafc;font-size:12px}
    body.authenticated .incident-main{min-width:0}.incident-summary{display:block;color:var(--ui-title);font-weight:750}.incident-meta{display:block;margin-top:5px;color:var(--ui-muted);font-size:10px}.incident-detail{color:var(--ui-muted);line-height:1.45}
    body.authenticated .incident-life{display:grid;justify-items:end;gap:6px}.incident-state{padding:5px 8px;border-radius:999px;background:var(--ui-success-soft);color:var(--ui-success);font-size:10px;font-weight:800}.incident-state.watch{background:var(--ui-warning-soft);color:var(--ui-warning)}.incident-state.bad{background:var(--ui-danger-soft);color:var(--ui-danger)}.incident-duration{color:var(--ui-muted);font-size:10px;font-variant-numeric:tabular-nums}
    body.authenticated .incident-track{display:flex;align-items:center;gap:4px}.incident-track i{display:block;width:7px;height:7px;border-radius:50%;background:#cfd6df}.incident-track i.done{background:var(--ui-success)}.incident-track i.current{background:var(--ui-warning)}.incident-track b{width:15px;height:1px;background:#d9dfe7}
    @media(max-width:720px){body.authenticated .incident-head{display:block}body.authenticated .incident-head>strong{display:block;margin-top:8px}body.authenticated .incident-row{grid-template-columns:1fr;gap:9px;font-size:13px}body.authenticated .incident-life{justify-items:start}.incident-meta,.incident-duration{font-size:11px}}

    body.authenticated .operational-health-summary{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:17px 20px;border:1px solid var(--ui-line);border-radius:10px;background:#fff}
    body.authenticated .operational-health-summary small,body.authenticated .operational-health-summary strong,body.authenticated .operational-health-summary span{display:block}
    body.authenticated .operational-health-summary small{color:var(--ui-accent);font-size:10px;font-weight:800;letter-spacing:.08em}.operational-health-summary strong{margin-top:4px;color:var(--ui-title);font-size:20px}.operational-health-summary>div>span{margin-top:3px;color:var(--ui-muted);font-size:12px}
    body.authenticated .operational-health-summary.state-observation{border-left:4px solid var(--ui-accent)}body.authenticated .operational-health-summary.state-attention{border-left:4px solid var(--ui-warning)}body.authenticated .operational-health-summary.state-critical{border-left:4px solid var(--ui-danger)}body.authenticated .operational-health-summary.state-healthy{border-left:4px solid var(--ui-success)}
    body.authenticated .operational-health-factors{display:flex;justify-content:flex-end;gap:6px;flex-wrap:wrap}.operational-health-factors span{padding:5px 8px;border-radius:999px;background:#f3f6f8;color:var(--ui-muted)!important;font-size:10px!important}
    @media(max-width:720px){body.authenticated .operational-health-summary{display:block;padding:15px}.operational-health-summary strong{font-size:22px}.operational-health-summary>div>span{font-size:13px;line-height:1.45}.operational-health-factors{justify-content:flex-start!important;margin-top:12px}}

    body.authenticated .operational-health-history{grid-column:1/-1}.health-history-timeline{display:grid;gap:0;margin-top:16px}.health-history-row{display:grid;grid-template-columns:22px 130px minmax(180px,1fr) 120px;gap:10px;align-items:start;min-height:58px}.health-history-node{position:relative;display:flex;justify-content:center;height:100%}.health-history-node:after{content:"";position:absolute;top:12px;bottom:-5px;width:1px;background:var(--ui-line)}.health-history-row:last-child .health-history-node:after{display:none}.health-history-node i{position:relative;z-index:1;width:9px;height:9px;margin-top:5px;border-radius:50%;background:var(--ui-success);box-shadow:0 0 0 4px #fff}.health-history-row.observation .health-history-node i{background:var(--ui-accent)}.health-history-row.attention .health-history-node i{background:var(--ui-warning)}.health-history-row.critical .health-history-node i{background:var(--ui-danger)}.health-history-state strong,.health-history-cause strong{display:block;color:var(--ui-title);font-size:12px}.health-history-state span,.health-history-cause span,.health-history-duration{display:block;margin-top:4px;color:var(--ui-muted);font-size:10px;line-height:1.4}.health-history-duration{text-align:right}.health-history-current{color:var(--ui-accent)!important;font-weight:750}
    @media(max-width:720px){.health-history-row{grid-template-columns:18px 1fr auto;min-height:72px}.health-history-cause{grid-column:2/-1}.health-history-duration{grid-column:3;grid-row:1}.health-history-state strong,.health-history-cause strong{font-size:13px}.health-history-state span,.health-history-cause span,.health-history-duration{font-size:11px}}

    body.authenticated .operational-availability{grid-column:1/-1}.availability-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:16px}.availability-window{padding:15px;border:1px solid var(--ui-line);border-radius:10px;background:#f8fafc}.availability-window>span,.availability-window>strong,.availability-window>small,.availability-window>em{display:block}.availability-window>span{color:var(--ui-muted);font-size:10px;font-weight:800;letter-spacing:.06em}.availability-window>strong{margin-top:6px;color:var(--ui-title);font-size:25px}.availability-window>small{margin-top:3px;color:var(--ui-muted);font-size:11px}.availability-window>em{margin-top:7px;color:var(--ui-muted);font-size:10px;font-style:normal}.availability-meter{height:6px;margin-top:11px;overflow:hidden;border-radius:999px;background:#e6ebf0}.availability-meter i{display:block;width:0;height:100%;border-radius:inherit;background:var(--ui-success);transition:width .25s ease}.availability-window.incomplete .availability-meter i{background:var(--ui-accent)}
    @media(max-width:720px){.availability-grid{grid-template-columns:1fr}.availability-window>strong{font-size:27px}.availability-window>small,.availability-window>em{font-size:12px}}

    body.authenticated .slo-budget{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:14px}.slo-budget>div{padding:10px 12px;border:1px solid var(--ui-line);border-radius:8px;background:#fff}.slo-budget small,.slo-budget strong,.slo-budget span{display:block}.slo-budget small{color:var(--ui-muted);font-size:9px;font-weight:800}.slo-budget strong{margin-top:4px;color:var(--ui-title);font-size:15px}.slo-budget span{margin-top:3px;color:var(--ui-muted);font-size:10px}.slo-budget span.budget-ok{color:var(--ui-success);font-weight:750}.slo-budget span.budget-bad{color:var(--ui-danger);font-weight:750}.slo-budget span.budget-provisional{color:var(--ui-accent);font-weight:750}
    @media(max-width:720px){body.authenticated .slo-budget{grid-template-columns:1fr}.slo-budget strong{font-size:17px}}

    body.authenticated .slo-forecast{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:8px}.slo-forecast>div{padding:11px 12px;border:1px solid var(--ui-line);border-radius:8px;background:#f8fafc}.slo-forecast small,.slo-forecast strong,.slo-forecast span{display:block}.slo-forecast small{color:var(--ui-muted);font-size:9px;font-weight:800}.slo-forecast strong{margin-top:4px;color:var(--ui-title);font-size:13px}.slo-forecast span{margin-top:3px;color:var(--ui-muted);font-size:10px;line-height:1.4}.slo-forecast strong.risk{color:var(--ui-danger)}.slo-forecast strong.track{color:var(--ui-success)}.slo-forecast strong.collecting{color:var(--ui-accent)}
    @media(max-width:720px){body.authenticated .slo-forecast{grid-template-columns:1fr}.slo-forecast strong{font-size:14px}.slo-forecast span{font-size:11px}}

    body.authenticated .preventive-diagnostics{grid-column:1/-1}.diagnostic-list{display:grid;gap:10px;margin-top:15px}.diagnostic-item{border:1px solid var(--ui-line);border-radius:10px;background:#f8fafc;padding:14px}.diagnostic-top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.diagnostic-top strong{color:var(--ui-title);font-size:13px}.diagnostic-mode{font-size:9px;font-weight:800;color:var(--ui-accent);border:1px solid color-mix(in srgb,var(--ui-accent) 28%,transparent);border-radius:999px;padding:4px 7px;white-space:nowrap}.diagnostic-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:12px}.diagnostic-fields div{padding-top:8px;border-top:1px solid var(--ui-line)}.diagnostic-fields small,.diagnostic-fields span{display:block}.diagnostic-fields small{font-size:9px;font-weight:800;color:var(--ui-muted);letter-spacing:.05em}.diagnostic-fields span{margin-top:4px;font-size:11px;line-height:1.45;color:var(--ui-text)}.diagnostic-fields .recommendation{grid-column:1/-1}.diagnostic-fields .recommendation span{color:var(--ui-title);font-weight:650}
    @media(max-width:720px){.diagnostic-fields{grid-template-columns:1fr}.diagnostic-fields .recommendation{grid-column:auto}.diagnostic-top strong{font-size:14px}.diagnostic-fields span{font-size:12px}}

    .diagnostic-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.diagnostic-actions button{border:1px solid var(--ui-line);background:#fff;color:var(--ui-title);border-radius:7px;padding:7px 10px;font-size:10px;font-weight:750;cursor:pointer}.diagnostic-actions button:hover{border-color:var(--ui-accent);color:var(--ui-accent)}.diagnostic-actions button.primary{background:var(--ui-accent);border-color:var(--ui-accent);color:#fff}.diagnostic-evidence-panel{display:none;margin-top:10px;padding:10px 12px;border-left:3px solid var(--ui-accent);background:#fff;border-radius:6px;font-size:11px;line-height:1.5;color:var(--ui-text)}.diagnostic-evidence-panel.open{display:block}.protection-check{margin-top:10px;font-size:10px;font-weight:700;color:var(--ui-muted)}.protection-check.ok{color:var(--ui-success)}.protection-check.bad{color:var(--ui-danger)}
    @media(max-width:720px){.diagnostic-actions button{flex:1 1 auto;font-size:11px;padding:9px}.diagnostic-evidence-panel{font-size:12px}}

    .diagnostic-runbook{margin-top:12px;padding-top:11px;border-top:1px solid var(--ui-line)}.diagnostic-runbook>small{display:block;font-size:9px;font-weight:800;color:var(--ui-muted);letter-spacing:.05em;margin-bottom:9px}.runbook-steps{display:grid;gap:7px}.runbook-step{display:grid;grid-template-columns:20px 110px minmax(0,1fr) auto;gap:8px;align-items:center}.runbook-step i{width:8px;height:8px;border-radius:50%;background:var(--ui-accent);justify-self:center}.runbook-step.auth i{background:var(--ui-warning)}.runbook-step strong{font-size:10px;color:var(--ui-title)}.runbook-step span{font-size:10px;color:var(--ui-muted);line-height:1.35}.runbook-step em{font-style:normal;font-size:8px;font-weight:800;border-radius:999px;padding:3px 6px;background:#eef2f6;color:var(--ui-muted);white-space:nowrap}.runbook-step.auth em{background:#fff7e6;color:var(--ui-warning)}
    @media(max-width:720px){.runbook-step{grid-template-columns:16px 86px 1fr}.runbook-step em{grid-column:3;margin-top:2px;justify-self:start}.runbook-step strong,.runbook-step span{font-size:11px}}
.runbook-step.status-verified i{background:var(--ui-success)}.runbook-step.status-verified em{color:var(--ui-success);background:#eef9f2}.runbook-step.status-observing i{background:var(--ui-accent)}.runbook-step.status-observing em{color:var(--ui-accent);background:#eef7f8}.runbook-step.status-attention i{background:var(--ui-danger)}.runbook-step.status-attention em{color:var(--ui-danger);background:#fff0f0}.runbook-step.status-pending i{background:#94a3b8}

    .casefile-modal{position:fixed;inset:0;z-index:80;background:rgba(15,23,42,.42);display:none;align-items:center;justify-content:center;padding:20px}.casefile-modal.open{display:flex}.casefile-shell{width:min(760px,100%);max-height:88vh;overflow:auto;background:#fff;border-radius:14px;box-shadow:0 24px 70px rgba(15,23,42,.24);padding:18px}.casefile-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;border-bottom:1px solid var(--ui-line);padding-bottom:12px}.casefile-head h3{margin:3px 0 0}.casefile-head button{border:0;background:#eef2f6;border-radius:8px;width:32px;height:32px;font-size:20px;cursor:pointer}.casefile-body{display:grid;gap:12px;margin-top:14px}.casefile-block{border:1px solid var(--ui-line);border-radius:10px;padding:12px;background:#f8fafc}.casefile-block>small{display:block;font-size:9px;font-weight:800;color:var(--ui-muted);letter-spacing:.05em;margin-bottom:7px}.casefile-timeline{display:grid;gap:8px}.casefile-event{display:grid;grid-template-columns:10px 140px 1fr;gap:8px;align-items:center;font-size:11px}.casefile-event i{width:8px;height:8px;border-radius:50%;background:var(--ui-accent)}.casefile-event strong{color:var(--ui-title)}.casefile-event span{color:var(--ui-muted)}.incident-row{cursor:pointer}.incident-row:hover{border-color:var(--ui-accent)}
    @media(max-width:720px){.casefile-modal{padding:8px;align-items:flex-end}.casefile-shell{max-height:92vh;border-radius:14px 14px 0 0}.casefile-event{grid-template-columns:10px 1fr}.casefile-event span{grid-column:2;font-size:11px}}
.incident-intervention-context{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid #b9dfe3;background:#f1fafb;border-radius:9px;padding:10px 12px;margin-bottom:12px}.incident-intervention-context>div{display:grid;gap:2px}.incident-intervention-context small{font-size:8px;font-weight:800;color:var(--ui-accent);letter-spacing:.06em}.incident-intervention-context strong{font-size:11px;color:var(--ui-title)}.incident-intervention-context span{font-size:9px;color:var(--ui-muted);font-family:monospace}.incident-intervention-context button{border:1px solid var(--ui-line);background:#fff;border-radius:7px;padding:6px 9px;font-size:9px;font-weight:750;cursor:pointer}
.casefile-trace-ok{display:inline-flex;align-items:center;border:1px solid #b9dfe3;background:#f1fafb;color:#0f6972;border-radius:999px;padding:5px 8px;font-size:8px;font-weight:850;letter-spacing:.04em;margin:0 0 8px}
.casefile-intervention-state{display:flex;align-items:center;justify-content:space-between;gap:10px;border:1px solid var(--ui-line);border-radius:9px;padding:8px 10px;margin-bottom:8px;background:#fff}.casefile-intervention-state span{font-size:8px;font-weight:800;color:var(--ui-muted);letter-spacing:.05em}.casefile-intervention-state strong{font-size:10px}.casefile-intervention-state.state-executed strong,.casefile-intervention-state.state-authorized strong{color:var(--ui-success)}.casefile-intervention-state.state-failed strong{color:var(--ui-danger)}.casefile-intervention-state.state-prepared strong{color:var(--ui-accent)}
.intervention-cycle{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:8px 0 10px}.intervention-cycle-step{position:relative;display:grid;justify-items:center;gap:4px;text-align:center;color:var(--ui-muted);font-size:8px;font-weight:750}.intervention-cycle-step i{font-style:normal;width:22px;height:22px;border-radius:50%;display:grid;place-items:center;border:1px solid var(--ui-line);background:#fff;font-size:9px}.intervention-cycle-step.completed{color:var(--ui-success)}.intervention-cycle-step.completed i{border-color:#a9d9c3;background:#eef9f3}.intervention-cycle-step.failed{color:var(--ui-danger)}.intervention-cycle-step.failed i{border-color:#efb4b4;background:#fff2f2}.intervention-cycle-step:not(:last-child):after{content:"";position:absolute;height:1px;background:var(--ui-line);left:calc(50% + 15px);right:calc(-50% + 15px);top:11px;z-index:0}.intervention-cycle-step i{z-index:1}
.intervention-cycle-step b{font-size:8px;font-weight:700;color:var(--ui-muted)}.intervention-cycle-step.completed b{color:var(--ui-success)}.intervention-cycle-step.failed b{color:var(--ui-danger)}

.intervention-history-title{
  display:block;
  margin-top:10px;
  margin-bottom:6px;
  font-size:8px;
  font-weight:850;
  color:var(--ui-muted);
  letter-spacing:.06em
}
.intervention-history{
  display:grid;
  gap:7px;
  margin-top:6px
}
.intervention-history-card{
  border:1px solid var(--ui-line);
  border-radius:8px;
  padding:9px;
  background:#fff
}
.intervention-history-card>div{
  display:flex;
  justify-content:space-between;
  gap:8px;
  align-items:center
}
.intervention-history-card strong{
  font-size:9px;
  color:var(--ui-title)
}
.intervention-history-card span{
  font-size:8px;
  font-weight:800;
  color:var(--ui-accent)
}
.intervention-history-card p{
  font-size:8px;
  margin:4px 0 0
}


.global-interventions{display:grid;gap:7px;margin-top:12px}.global-intervention-row{display:grid;grid-template-columns:minmax(170px,1.4fr) minmax(130px,1fr) 90px 110px 100px 70px;gap:9px;align-items:center;padding:10px 11px;border:1px solid var(--ui-line);border-radius:9px;background:#f8fafb;font-size:10px}.global-intervention-row strong{color:var(--ui-title);overflow:hidden;text-overflow:ellipsis}.global-intervention-row b{color:var(--ui-accent)}.global-intervention-row span{color:var(--ui-muted)}@media(max-width:720px){.global-intervention-row{grid-template-columns:1fr 1fr}.global-intervention-row strong{grid-column:1/-1}.global-intervention-row span,.global-intervention-row b{font-size:9px}}

.intervention-filters{display:grid;grid-template-columns:minmax(190px,1.4fr) minmax(120px,.7fr) minmax(110px,.6fr) auto;gap:8px;align-items:end;margin-top:13px}.intervention-filters label{margin:0;color:var(--ui-muted);font-size:9px}.intervention-filters input,.intervention-filters select{width:100%;height:36px;margin-top:5px;padding:0 9px;border:1px solid var(--ui-line);border-radius:8px;background:#fff;color:var(--ui-text);font:inherit}.intervention-filters button{height:36px;min-height:36px;margin:0}@media(max-width:720px){.intervention-filters{grid-template-columns:1fr 1fr}.intervention-filters label:first-child{grid-column:1/-1}.intervention-filters button{align-self:end}}
.global-intervention-row[role="button"]{cursor:pointer}.global-intervention-row[role="button"]:hover,.global-intervention-row[role="button"]:focus{border-color:var(--ui-accent);outline:none;box-shadow:0 0 0 2px rgba(37,99,235,.06)}

.intervention-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:13px}.intervention-kpis>div{border:1px solid var(--ui-line);border-radius:9px;padding:9px 11px;background:#f8fafb;display:flex;align-items:center;justify-content:space-between}.intervention-kpis small{font-size:8px;font-weight:800;color:var(--ui-muted);letter-spacing:.04em}.intervention-kpis strong{font-size:16px;color:var(--ui-title)}.intervention-kpis .executed strong{color:#16845b}.intervention-kpis .progress strong{color:#a36b00}.intervention-kpis .failed strong{color:#c33b3b}.global-intervention-row.state-executed{border-left:3px solid #27a875}.global-intervention-row.state-authorized,.global-intervention-row.state-prepared{border-left:3px solid #d49a25}.global-intervention-row.state-failed{border-left:3px solid #d9534f}.global-intervention-row.state-executed b,.intervention-detail-summary.state-executed p:first-of-type{color:#16845b}.global-intervention-row.state-authorized b,.global-intervention-row.state-prepared b{color:#a36b00}.global-intervention-row.state-failed b,.intervention-detail-summary.state-failed p:first-of-type{color:#c33b3b}@media(max-width:720px){.intervention-kpis{grid-template-columns:1fr 1fr}.intervention-kpis>div{padding:8px 9px}}

.intervention-kpis{grid-template-columns:repeat(5,1fr)}.intervention-kpis .stalled strong{color:#b56b00}.global-intervention-row.is-stalled{border-color:#e0aa50;background:#fffaf0}.global-intervention-row .stall-warning{grid-column:1/-1;color:#9a5b00;font-weight:800;font-size:9px}.intervention-detail-summary .stall-warning{color:#9a5b00;font-weight:800;background:#fff7e6;border:1px solid #efcf91;border-radius:7px;padding:7px 8px}@media(max-width:720px){.intervention-kpis{grid-template-columns:1fr 1fr}.intervention-kpis .stalled{grid-column:1/-1}}

.alert-item .alert-intervention-link{flex:0 0 auto;min-height:28px;margin:0;padding:0 9px;border-color:#d6dee8;background:#fff;color:var(--ui-blue);font-size:9px}.alert-item .alert-intervention-link:hover{background:#f5f8fb}@media(max-width:720px){.alert-item .alert-intervention-link{align-self:flex-start;margin-top:4px}}

body.authenticated .administrative-attention{grid-column:1/-1;padding:18px 20px;border:1px solid var(--ui-line);border-radius:10px;background:#fff}.admin-attention-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:14px}.admin-attention-grid button{min-height:78px;margin:0;padding:12px 14px;text-align:left;border:1px solid var(--ui-line);border-radius:9px;background:#f8fafc;color:var(--ui-text)}.admin-attention-grid small,.admin-attention-grid strong,.admin-attention-grid span{display:block}.admin-attention-grid small{font-size:8px;color:var(--ui-muted);font-weight:800}.admin-attention-grid strong{margin-top:4px;font-size:20px;color:var(--ui-title)}.admin-attention-grid span{margin-top:3px;font-size:9px;color:var(--ui-muted)}.admin-attention-grid button[data-admin-attention="stalled"] strong{color:#b56b00}.admin-attention-grid button[data-admin-attention="failed"] strong{color:var(--ui-red)}.administrative-attention.has-attention{border-color:#ead4ad}@media(max-width:720px){.admin-attention-grid{grid-template-columns:1fr}.admin-attention-grid button{min-height:64px}}

.admin-attention-state{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:14px;padding:11px 13px;border:1px solid var(--ui-line);border-radius:9px;background:#f8fafc}.admin-attention-state div{display:flex;align-items:center;gap:9px}.admin-attention-state small{font-size:8px;color:var(--ui-muted);font-weight:800}.admin-attention-state strong{font-size:12px;color:var(--ui-green)}.admin-attention-state span{font-size:9px;color:var(--ui-muted);text-align:right}.admin-attention-state.observation{border-color:#ead9b9;background:#fffaf1}.admin-attention-state.observation strong{color:var(--ui-amber)}.admin-attention-state.attention{border-color:#efc6c6;background:#fff5f5}.admin-attention-state.attention strong{color:var(--ui-red)}@media(max-width:720px){.admin-attention-state{align-items:flex-start;flex-direction:column;gap:5px}.admin-attention-state span{text-align:left}}

.admin-attention-history{margin-top:12px;padding:10px 12px;border:1px solid var(--ui-line);border-radius:9px;background:#fafbfc}.admin-history-head{display:flex;justify-content:space-between;gap:10px}.admin-history-head small,.admin-history-head span{font-size:8px;color:var(--ui-muted);font-weight:800}.admin-history-list{display:grid;gap:5px;margin-top:8px}.admin-history-row{display:grid;grid-template-columns:90px 1fr auto;gap:8px;align-items:center;font-size:9px}.admin-history-row strong{color:var(--ui-green)}.admin-history-row.observation strong{color:var(--ui-amber)}.admin-history-row.attention strong{color:var(--ui-red)}.admin-history-row span,.admin-history-row small{color:var(--ui-muted)}@media(max-width:720px){.admin-history-row{grid-template-columns:80px 1fr}.admin-history-row small{grid-column:2}}

.admin-attention-metrics{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}.admin-attention-metrics>div{padding:10px 12px;border:1px solid var(--ui-line);border-radius:9px;background:#fafbfc}.admin-attention-metrics small,.admin-attention-metrics strong,.admin-attention-metrics span{display:block}.admin-attention-metrics small{font-size:8px;color:var(--ui-muted);font-weight:800}.admin-attention-metrics strong{margin-top:4px;font-size:11px;color:var(--ui-title)}.admin-attention-metrics span{margin-top:3px;font-size:8px;color:var(--ui-muted)}@media(max-width:720px){.admin-attention-metrics{grid-template-columns:1fr}}

.admin-attention-trend{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:12px;padding:10px 12px;border:1px solid var(--ui-line);border-radius:9px;background:#fafbfc}.admin-attention-trend small,.admin-attention-trend strong{display:block}.admin-attention-trend small{font-size:8px;color:var(--ui-muted);font-weight:800}.admin-attention-trend strong{margin-top:3px;font-size:11px;color:var(--ui-title)}.admin-attention-trend span{font-size:8px;color:var(--ui-muted);text-align:right}.admin-attention-trend.improving strong{color:var(--ui-green)}.admin-attention-trend.deteriorating{border-color:#efc6c6;background:#fff5f5}.admin-attention-trend.deteriorating strong{color:var(--ui-red)}.admin-attention-trend.stable strong{color:var(--ui-blue)}@media(max-width:720px){.admin-attention-trend{align-items:flex-start;flex-direction:column;gap:4px}.admin-attention-trend span{text-align:left}}

.admin-attention-index{display:flex;align-items:center;gap:18px;margin-top:12px;padding:12px 14px;border:1px solid var(--ui-line);border-radius:9px;background:#f7fbf8}.admin-index-score{min-width:100px}.admin-index-score small,.admin-index-score strong,.admin-index-score span{display:block}.admin-index-score small{font-size:8px;color:var(--ui-muted);font-weight:800}.admin-index-score strong{font-size:26px;line-height:1.05;color:var(--ui-green)}.admin-index-score span{font-size:9px;color:var(--ui-muted)}.admin-index-factors{display:flex;flex-wrap:wrap;gap:6px}.admin-index-factors span{padding:4px 7px;border:1px solid var(--ui-line);border-radius:12px;background:#fff;font-size:8px;color:var(--ui-muted)}.admin-attention-index.attention,.admin-attention-index.critical{background:#fff5f5;border-color:#efc6c6}.admin-attention-index.attention .admin-index-score strong,.admin-attention-index.critical .admin-index-score strong{color:var(--ui-red)}.admin-attention-index.stable .admin-index-score strong{color:var(--ui-amber)}@media(max-width:720px){.admin-attention-index{align-items:flex-start;flex-direction:column;gap:8px}}

.admin-index-history{margin-top:8px;padding:10px 12px;border:1px solid var(--ui-line);border-radius:9px;background:#fafbfc}.admin-index-history-list{display:grid;gap:5px;margin-top:8px}.admin-index-history-row{display:grid;grid-template-columns:100px 1fr auto;gap:8px;align-items:center;font-size:8px}.admin-index-history-row strong{color:var(--ui-title)}.admin-index-history-row span,.admin-index-history-row small{color:var(--ui-muted)}@media(max-width:720px){.admin-index-history-row{grid-template-columns:90px 1fr}.admin-index-history-row small{grid-column:2}}
body.authenticated #devices-overview .section-intro>strong{max-width:210px;color:var(--ui-muted);font-size:10px;font-weight:700;text-align:right;overflow-wrap:anywhere}body.authenticated #devices-overview .boundary-card{display:grid;gap:6px;padding:12px 14px;border:1px solid var(--ui-line);border-radius:9px;background:#f8fafc}body.authenticated #devices-overview .boundary-card strong,body.authenticated #devices-overview .boundary-card span{display:block}body.authenticated #devices-overview .boundary-card strong{color:var(--ui-title);font-size:11px}body.authenticated #devices-overview .boundary-card span{color:var(--ui-muted);font-size:10px;line-height:1.5}@media(max-width:700px){body.authenticated #devices-overview .section-intro{display:block}body.authenticated #devices-overview .section-intro>strong{display:block;max-width:none;margin-top:7px;text-align:left}body.authenticated #devices-overview .maintenance-summary{grid-template-columns:repeat(2,minmax(0,1fr))}}
body.authenticated #fleet-health-card.fleet-warning{border-color:#ead7b7;background:#fffaf1}body.authenticated #fleet-health-card.fleet-critical{border-color:#efcaca;background:#fff6f6}body.authenticated #fleet-health.bad{color:var(--ui-red)}body.authenticated #fleet-health.warn{color:var(--ui-amber)}
body.authenticated #devices-overview .inventory-card{margin-top:13px;padding:14px;border:1px solid var(--ui-line);border-radius:10px;background:#fff}body.authenticated #devices-overview .inventory-toolbar{display:grid;grid-template-columns:minmax(0,1fr) minmax(190px,240px);gap:9px;margin:12px 0 14px}body.authenticated #devices-overview .inventory-search{height:44px;display:flex;align-items:center;gap:9px;padding:0 12px;border:1px solid var(--ui-line);border-radius:9px;background:#f8fafc;color:var(--ui-muted)}body.authenticated #devices-overview .inventory-search:focus-within{border-color:var(--ui-teal);background:#fff;box-shadow:0 0 0 2px rgba(18,112,122,.08)}body.authenticated #devices-overview .inventory-search span{font-size:23px;line-height:1}body.authenticated #devices-overview .inventory-search input{width:100%;border:0!important;outline:0!important;background:transparent!important;color:var(--ui-ink);font:inherit;padding:0!important;box-shadow:none!important}body.authenticated #devices-overview .inventory-search input::placeholder{color:#8c98a5}body.authenticated #devices-overview .inventory-filter-wrap{position:relative;height:44px;display:flex;align-items:center;border:1px solid var(--ui-line);border-radius:9px;background:#f8fafc;overflow:hidden}body.authenticated #devices-overview .inventory-filter-wrap>span{padding-left:12px;font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--ui-muted);white-space:nowrap}body.authenticated #devices-overview .inventory-toolbar select{appearance:none;-webkit-appearance:none;width:100%;height:100%;border:0!important;outline:0;background:transparent;color:var(--ui-ink);font:inherit;font-weight:700;padding:0 30px 0 9px;box-shadow:none!important}body.authenticated #devices-overview .inventory-filter-wrap:after{content:'⌄';position:absolute;right:11px;top:10px;color:var(--ui-muted);pointer-events:none}@media(max-width:640px){body.authenticated #devices-overview .inventory-toolbar{grid-template-columns:1fr}body.authenticated #devices-overview .inventory-filter-wrap{width:100%}}body.authenticated #devices-overview .device-inventory-list{display:grid;gap:7px}body.authenticated #devices-overview .device-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 12px;padding:10px 12px;border:1px solid var(--ui-line);border-radius:8px;background:#f8fafc}body.authenticated #devices-overview .device-row strong{overflow-wrap:anywhere}body.authenticated #devices-overview .device-row span{font-size:10px;color:var(--ui-muted)}body.authenticated #devices-overview .device-state{font-weight:800;text-align:right}body.authenticated #devices-overview .device-state.bad{color:var(--ui-red)}body.authenticated #devices-overview .device-state.warn{color:var(--ui-amber)}body.authenticated #devices-overview .device-state.ok{color:var(--ui-teal)}
body.authenticated #devices-overview .device-row{cursor:pointer}body.authenticated #devices-overview .device-row:hover{border-color:#b7c6d6;background:#fff}body.authenticated .device-diagnostic{display:grid;gap:10px}body.authenticated .device-diagnostic .diag-hero{padding:14px;border:1px solid var(--ui-line);border-radius:9px;background:#f8fafc}body.authenticated .device-diagnostic .diag-hero strong{display:block;font-size:16px;margin-bottom:5px}body.authenticated .device-diagnostic .diag-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}body.authenticated .device-diagnostic .diag-grid div{padding:10px;border:1px solid var(--ui-line);border-radius:8px}body.authenticated .device-diagnostic small{display:block;color:var(--ui-muted);margin-bottom:4px}body.authenticated .device-timeline{display:grid;gap:6px;padding:4px 0}body.authenticated .device-timeline span{padding-left:14px;position:relative;color:var(--ui-muted)}body.authenticated .device-timeline span:before{content:'•';position:absolute;left:2px;color:var(--ui-teal)}@media(max-width:500px){body.authenticated .device-diagnostic .diag-grid{grid-template-columns:1fr}}
body.authenticated #devices-overview .device-row{padding:13px 14px;gap:7px 12px;grid-template-columns:minmax(0,1fr) auto;align-items:start}body.authenticated #devices-overview .device-row>strong{display:grid;grid-template-columns:28px minmax(0,1fr);align-items:center;gap:9px;min-width:0;font-size:14px;line-height:1.28;font-weight:720}body.authenticated #devices-overview .vehicle-type-icon{display:block;width:26px!important;height:26px!important;min-width:26px;stroke:#263642!important;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;fill:none!important;overflow:visible}body.authenticated #devices-overview .vehicle-type-icon path{stroke:#263642!important;fill:none!important;vector-effect:non-scaling-stroke}body.authenticated #devices-overview .device-row>span{font-size:12px;line-height:1.3}body.authenticated #devices-overview .device-state{font-size:12.5px;line-height:1.3;white-space:nowrap;font-weight:750}@media(max-width:640px){body.authenticated #devices-overview .device-row{padding:12px 13px;gap:6px 9px}body.authenticated #devices-overview .device-row>strong{grid-template-columns:27px minmax(0,1fr);gap:8px;font-size:13.5px}body.authenticated #devices-overview .vehicle-type-icon{width:25px!important;height:25px!important;min-width:25px}body.authenticated #devices-overview .device-state{font-size:12px}}body.authenticated #devices-overview .vehicle-type-image{display:block!important;width:58px!important;height:32px!important;min-width:58px!important;background-position:0 0;stroke:none!important;filter:none!important}body.authenticated #devices-overview .device-row>strong{grid-template-columns:58px minmax(0,1fr)!important;gap:10px!important}@media(max-width:640px){body.authenticated #devices-overview .vehicle-type-image{width:54px!important;height:30px!important;min-width:54px!important;}body.authenticated #devices-overview .device-row>strong{grid-template-columns:54px minmax(0,1fr)!important;gap:9px!important}}
/* Device inventory mobile refinement */
body.authenticated #devices-overview .device-row{position:relative;padding:16px 16px 14px;column-gap:12px;row-gap:10px;border-radius:14px;background:#fff}body.authenticated #devices-overview .device-row>strong{grid-column:1;grid-row:1;display:grid;grid-template-columns:62px minmax(0,1fr)!important;gap:12px!important;align-items:center;font-size:15px;line-height:1.28;font-weight:720;letter-spacing:-.12px}body.authenticated #devices-overview .vehicle-type-image{width:62px!important;height:34px!important;min-width:62px!important;background-position:0 0}body.authenticated #devices-overview .device-state{grid-column:2;grid-row:1;align-self:center;justify-self:end;padding:5px 9px;border-radius:999px;background:#f8f9fa;font-size:11.5px;line-height:1.15;white-space:nowrap}body.authenticated #devices-overview .device-state.bad{background:#fff1f0;color:#b6403f}body.authenticated #devices-overview .device-state.ok{background:#edf8f4;color:#16745f}body.authenticated #devices-overview .device-state.warn{background:#fff7e8;color:#8a5b00}body.authenticated #devices-overview .device-row>span{font-size:12.5px;line-height:1.35;color:#7b8792}body.authenticated #devices-overview .device-row>span:nth-of-type(1){grid-column:1;grid-row:2}body.authenticated #devices-overview .device-row>span:nth-of-type(2){grid-column:2;grid-row:2;text-align:right}body.authenticated #devices-overview .device-row:hover{background:#fbfcfd}
@media(max-width:640px){body.authenticated #devices-overview .device-row{grid-template-columns:minmax(0,1fr) auto;padding:15px 14px 13px;column-gap:8px;row-gap:9px}body.authenticated #devices-overview .device-row>strong{grid-template-columns:58px minmax(0,1fr)!important;gap:10px!important;font-size:14.5px;line-height:1.3}body.authenticated #devices-overview .vehicle-type-image{width:58px!important;height:32px!important;min-width:58px!important;}body.authenticated #devices-overview .device-state{font-size:11px;padding:5px 8px}body.authenticated #devices-overview .device-row>span{font-size:12px}body.authenticated #devices-overview .device-row>span:nth-of-type(2){max-width:190px}}

/* Mobile device card: prioritize unit name width */
@media(max-width:640px){body.authenticated #devices-overview .device-row{grid-template-columns:minmax(0,1fr) auto!important;align-items:center!important}body.authenticated #devices-overview .device-row>strong{grid-column:1 / -1!important;grid-row:1!important;grid-template-columns:58px minmax(0,1fr)!important;padding-right:0!important;width:100%!important;max-width:none!important}body.authenticated #devices-overview .device-state{grid-column:2!important;grid-row:2!important;justify-self:end!important;align-self:center!important}body.authenticated #devices-overview .device-row>span:nth-of-type(1){grid-column:1!important;grid-row:2!important;align-self:center!important}body.authenticated #devices-overview .device-row>span:nth-of-type(2){grid-column:1 / -1!important;grid-row:3!important;text-align:left!important;max-width:none!important}body.authenticated #devices-overview .device-row>strong{overflow:visible!important;white-space:normal!important;word-break:normal!important;overflow-wrap:break-word!important}}

.casefile-head #device-detail-title{display:grid;grid-template-columns:68px minmax(0,1fr);align-items:center;gap:12px;margin-top:8px}.casefile-head #device-detail-title .detail-vehicle-icon{display:block!important;width:68px!important;height:38px!important;min-width:68px!important;filter:none!important}.casefile-head #device-detail-title>span:last-child{min-width:0;line-height:1.22}@media(max-width:640px){.casefile-head #device-detail-title{grid-template-columns:62px minmax(0,1fr);gap:10px}.casefile-head #device-detail-title .detail-vehicle-icon{width:62px!important;height:34px!important;min-width:62px!important;}.casefile-head #device-detail-title .detail-vehicle-icon[style*="-58px"]{}.casefile-head #device-detail-title .detail-vehicle-icon[style*="-116px"]{}.casefile-head #device-detail-title .detail-vehicle-icon[style*="-174px"]{}.casefile-head #device-detail-title .detail-vehicle-icon[style*="-32px"]{}}

/* Vehicle artwork fidelity: keep the 3D silhouettes at their native tile ratio. */
body.authenticated #devices-overview .device-row>strong{grid-template-columns:76px minmax(0,1fr)!important;gap:12px!important}
body.authenticated #devices-overview .vehicle-type-image{width:76px!important;height:42px!important;min-width:76px!important;background-color:transparent!important;image-rendering:auto!important;filter:none!important;transform:none!important}
@media(max-width:640px){body.authenticated #devices-overview .device-row>strong{grid-template-columns:72px minmax(0,1fr)!important;gap:11px!important}body.authenticated #devices-overview .vehicle-type-image{width:72px!important;height:40px!important;min-width:72px!important;}}
.casefile-head #device-detail-title{grid-template-columns:82px minmax(0,1fr)!important;gap:13px!important}.casefile-head #device-detail-title .detail-vehicle-icon{width:82px!important;height:46px!important;min-width:82px!important;background-color:transparent!important;image-rendering:auto!important;transform:none!important}
@media(max-width:640px){.casefile-head #device-detail-title{grid-template-columns:76px minmax(0,1fr)!important;gap:11px!important}.casefile-head #device-detail-title .detail-vehicle-icon{width:76px!important;height:42px!important;min-width:76px!important;}.casefile-head #device-detail-title .detail-vehicle-icon[style*="-58px"]{}.casefile-head #device-detail-title .detail-vehicle-icon[style*="-116px"]{}.casefile-head #device-detail-title .detail-vehicle-icon[style*="-174px"]{}.casefile-head #device-detail-title .detail-vehicle-icon[style*="-32px"]{}}
/* Individual transparent PNG vehicle assets: native ratio, no sprite scaling or distortion. */
body.authenticated #devices-overview .vehicle-type-image{display:block!important;width:64px!important;height:43px!important;min-width:64px!important;object-fit:contain!important;object-position:center!important;background:none!important;image-rendering:auto!important;filter:none!important;transform:none!important}
body.authenticated #devices-overview .device-row>strong{grid-template-columns:64px minmax(0,1fr)!important}
.casefile-head #device-detail-title .detail-vehicle-icon{display:block!important;width:64px!important;height:43px!important;min-width:64px!important;object-fit:contain!important;object-position:center!important;background:none!important;image-rendering:auto!important;filter:none!important;transform:none!important}
.casefile-head #device-detail-title{grid-template-columns:64px minmax(0,1fr)!important}
@media(max-width:640px){body.authenticated #devices-overview .vehicle-type-image{width:64px!important;height:43px!important;min-width:64px!important}body.authenticated #devices-overview .device-row>strong{grid-template-columns:64px minmax(0,1fr)!important}.casefile-head #device-detail-title{grid-template-columns:64px minmax(0,1fr)!important}.casefile-head #device-detail-title .detail-vehicle-icon{width:64px!important;height:43px!important;min-width:64px!important}}

/* Canonical vehicle pack: SVG only; legacy sprites disabled. */
body.authenticated #devices-overview .vehicle-type-image,.casefile-head #device-detail-title .detail-vehicle-icon{background:none!important;background-image:none!important;object-fit:contain!important;object-position:center!important;filter:none!important;transform:none!important}

    /* Device inventory: visible keyboard focus, without changing card geometry. */
    body.authenticated #devices-overview .device-row:focus-visible{outline:3px solid #14858d!important;outline-offset:3px!important;border-color:#14858d!important;background:#f0faf9!important}
    @media (prefers-reduced-motion:reduce){body.authenticated #devices-overview .device-row{transition:none!important}}

    /* Login visual polish: semantic lock pictogram and clearer keyboard focus. */
    .login-card-head .login-lock{flex:0 0 44px;color:#9aebc2;background:linear-gradient(135deg,rgba(87,212,154,.13),rgba(84,215,232,.07));border-color:rgba(87,212,154,.30)}
    .login-card input:focus-visible,.login-card button:focus-visible{outline:3px solid #54d7e8;outline-offset:3px}

    /* Device detail: calm, readable administrative diagnostic (scoped). */
    #device-detail-modal .casefile-shell{width:min(700px,100%);border:1px solid #dce6eb;border-radius:18px;padding:22px;background:#fff}
    #device-detail-modal .casefile-head{padding-bottom:16px;margin-bottom:16px;border-bottom:1px solid #e7edf0}
    #device-detail-modal .casefile-head .eyebrow{color:#167d7c;letter-spacing:.10em}
    #device-detail-modal #device-detail-title{line-height:1.3;overflow-wrap:anywhere}
    #device-detail-modal .diag-hero{background:linear-gradient(120deg,#f0faf7,#f5f9fc)!important;border:1px solid #d7e9e5!important;border-radius:12px!important;padding:17px!important}
    #device-detail-modal .diag-hero strong{color:#155b61;font-size:17px!important}
    #device-detail-modal .diag-hero span{display:block;color:#506471;line-height:1.55}
    #device-detail-modal .diag-grid{gap:10px!important}
    #device-detail-modal .diag-grid>div{min-width:0;padding:13px 14px!important;background:#fcfdfd;border:1px solid #e5ebef!important;border-radius:11px!important}
    #device-detail-modal .diag-grid small{font-size:10px;letter-spacing:.06em;font-weight:750;text-transform:uppercase}
    #device-detail-modal .diag-grid strong{display:block;font-size:13px;line-height:1.45;overflow-wrap:anywhere;color:#243846}
    #device-detail-modal .device-timeline{padding:13px 15px!important;border:1px solid #e5ebef;border-radius:12px;background:#fafcfd}
    #device-detail-modal .device-timeline>strong{color:#243846}
    #device-detail-modal #device-detail-close:focus-visible{outline:3px solid #14858d;outline-offset:3px}
    @media(max-width:640px){#device-detail-modal .casefile-shell{padding:17px 15px 22px;border-radius:18px 18px 0 0}#device-detail-modal .diag-grid{grid-template-columns:1fr!important}#device-detail-modal .casefile-head{gap:8px}#device-detail-modal .diag-hero{padding:15px!important}}

    /* Operational state chips: readable without relying on color alone. */
    body.authenticated #devices-overview .device-state{display:inline-flex;align-items:center;justify-content:center;gap:6px;max-width:100%;width:max-content;justify-self:end;padding:6px 10px;border:1px solid #d7e2e8;border-radius:999px;background:#f4f7f9;color:#344b5a!important;font-size:11px;line-height:1.25;letter-spacing:.01em;text-align:center;white-space:normal}
    body.authenticated #devices-overview .device-state::before{content:'';display:inline-block;flex:0 0 7px;width:7px;height:7px;border-radius:50%;background:#728596}
    body.authenticated #devices-overview .device-state.ok{background:#e9f7f1;border-color:#addbc7;color:#116346!important}
    body.authenticated #devices-overview .device-state.ok::before{background:#138457}
    body.authenticated #devices-overview .device-state.warn{background:#fff5df;border-color:#e9c77f;color:#82500c!important}
    body.authenticated #devices-overview .device-state.warn::before{background:#ad6c0a}
    body.authenticated #devices-overview .device-state.bad{background:#fff0ef;border-color:#eeb9b6;color:#9b2823!important}
    body.authenticated #devices-overview .device-state.bad::before{background:#c43a32}
    @media(max-width:640px){body.authenticated #devices-overview .device-state{padding:6px 9px;font-size:11px;justify-self:end}}

    /* Inventory refinement: consistent vehicle artwork footprint and readable metadata. */
    body.authenticated #devices-overview .device-inventory-list{gap:10px}
    body.authenticated #devices-overview .device-row{border:1px solid #e1e9ed;border-radius:14px;box-shadow:0 2px 8px rgba(27,49,61,.035);transition:border-color .16s ease,box-shadow .16s ease,background .16s ease}
    body.authenticated #devices-overview .device-row:hover{border-color:#a8c9c7;box-shadow:0 5px 16px rgba(27,84,86,.09);background:#fcfefd}
    body.authenticated #devices-overview .device-row>strong{min-width:0;line-height:1.38;overflow-wrap:anywhere}
    body.authenticated #devices-overview .device-row .vehicle-type-image{width:64px!important;height:43px!important;min-width:64px!important;object-fit:contain!important;object-position:center!important;image-rendering:auto!important;filter:none!important}
    body.authenticated #devices-overview .device-row>span{color:#526575;line-height:1.45}
    body.authenticated #devices-overview .inventory-search input::placeholder{color:#627587}
    body.authenticated #devices-overview .inventory-filter-wrap:focus-within{outline:3px solid rgba(20,133,141,.23);outline-offset:2px;border-color:#14858d}
    @media(max-width:640px){body.authenticated #devices-overview .device-row{padding:14px!important}body.authenticated #devices-overview .device-row>strong{gap:12px!important}}
    @media(prefers-reduced-motion:reduce){body.authenticated #devices-overview .device-row{transition:none}}

    /* Inventory feedback: distinguish empty results from unavailable data. */
    body.authenticated #devices-overview .inventory-empty{display:grid;justify-items:center;gap:8px;padding:28px 18px;border:1px dashed #b9d7d5;border-radius:14px;background:linear-gradient(145deg,#f3faf9,#fbfdfd);text-align:center;color:#254a53}
    body.authenticated #devices-overview .inventory-empty-icon{display:grid;place-items:center;width:38px;height:38px;border-radius:50%;background:#e0f2ee;color:#15756c;font-size:23px;line-height:1}
    body.authenticated #devices-overview .inventory-empty strong{font-size:15px;line-height:1.4}
    body.authenticated #devices-overview .inventory-empty p{max-width:410px;margin:0;color:#506775;font-size:12.5px;line-height:1.6}
    body.authenticated #devices-overview .inventory-unavailable{border-color:#e4cba3;background:#fffaf1;color:#79521c}

    body.authenticated #devices-overview .inventory-actions{display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:10px}body.authenticated #devices-overview .inventory-actions .fleet-refresh{margin:0;min-height:36px}
    body.authenticated #devices-overview .inventory-retry{margin-top:7px;padding:10px 17px;border:1px solid #b88742;border-radius:9px;background:#fff;color:#70450d;font-size:12px;font-weight:750;cursor:pointer}
    body.authenticated #devices-overview .inventory-retry:hover{background:#fff1d9}
    body.authenticated #devices-overview .inventory-retry:focus-visible{outline:3px solid #14858d;outline-offset:3px}

    /* Dashboard: compact, data-backed fleet overview (no location or identifiers). */
    body.authenticated .fleet-summary{display:grid;gap:16px;padding:21px 23px;border:1px solid #dce6e9;border-radius:14px;background:#fff;box-shadow:0 3px 14px rgba(27,49,61,.035)}
    body.authenticated .fleet-summary-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}
    body.authenticated .fleet-summary-heading h3{margin:5px 0;font-size:20px;color:#223847}
    body.authenticated .fleet-summary-heading p:last-child{margin:4px 0 0;color:#586e7a;font-size:12px;line-height:1.5}
    body.authenticated .fleet-summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
    body.authenticated .fleet-summary-tile{display:grid;align-content:start;gap:9px;min-width:0;padding:16px;border:1px solid #e1e9ed;border-radius:12px;background:#f8fafb}
    body.authenticated .fleet-summary-tile>span{font-size:12px;font-weight:750;color:#3f5967}
    body.authenticated .fleet-summary-tile>strong{font-size:clamp(25px,3vw,34px);line-height:1.1;color:#213746;font-variant-numeric:tabular-nums}
    body.authenticated .fleet-summary-tile>small{font-size:11px;line-height:1.45;color:#59707d}
    body.authenticated .fleet-online{background:#eff9f4;border-color:#cce7d8}
    body.authenticated .fleet-online>strong{color:#116346}
    body.authenticated .fleet-attention{background:#fff8eb;border-color:#eed9ad}
    body.authenticated .fleet-attention>strong{color:#855313}
    @media(max-width:920px){body.authenticated .fleet-summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
    @media(max-width:540px){body.authenticated .fleet-summary{padding:17px 15px}body.authenticated .fleet-summary-heading{flex-wrap:wrap}body.authenticated .fleet-summary-grid{gap:9px}body.authenticated .fleet-summary-tile{padding:13px 11px}body.authenticated .fleet-summary-tile>strong{font-size:27px}}

    /* Prioritized fleet review: safe, read-only summary. */
    body.authenticated .fleet-priority{display:grid;gap:12px;padding-top:17px;border-top:1px solid #e6edf0}
    body.authenticated .fleet-priority-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
    body.authenticated .fleet-priority-head strong{color:#243c49;font-size:15px}
    body.authenticated .fleet-priority-head p{margin:5px 0 0;color:#627580;font-size:11.5px;line-height:1.5}
    body.authenticated .fleet-priority-count{flex-shrink:0;padding:6px 10px;border-radius:999px;background:#edf4f5;color:#285b64;font-size:11px;font-weight:750}
    body.authenticated .fleet-priority-list{display:grid;gap:7px}
    body.authenticated .fleet-priority-list>p{margin:0;padding:11px 13px;border-radius:9px;background:#f4f8f9;color:#526b78;font-size:12px;line-height:1.5}
    body.authenticated .fleet-priority-row{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:11px 13px;border:1px solid #e5ecef;border-radius:10px;background:#fbfcfd}
    body.authenticated .fleet-priority-row>div{display:grid;gap:4px;min-width:0}
    body.authenticated .fleet-priority-row strong{font-size:12.5px;color:#283f4e;overflow-wrap:anywhere}
    body.authenticated .fleet-priority-row span{font-size:11px;color:#617582}
    body.authenticated .fleet-priority-tag{flex-shrink:0;padding:6px 9px;border-radius:999px;font-weight:750!important}
    body.authenticated .fleet-priority-tag.critical{background:#fff0ef;color:#922d29}
    body.authenticated .fleet-priority-tag.warning{background:#fff5df;color:#835411}
    @media(max-width:540px){body.authenticated .fleet-priority-head{flex-wrap:wrap}body.authenticated .fleet-priority-row{align-items:flex-start}body.authenticated .fleet-priority-tag{max-width:120px;text-align:center}}

    body.authenticated .fleet-priority-open{flex-shrink:0;min-height:34px;padding:7px 11px;border:1px solid #b6d3d2;border-radius:8px;background:#eff9f8;color:#12686c;font-size:11px;font-weight:750;cursor:pointer}
    body.authenticated .fleet-priority-open:hover{background:#def2f0;border-color:#7fb7b5}
    body.authenticated .fleet-priority-open:focus-visible{outline:3px solid #14858d;outline-offset:3px}
    @media(max-width:680px){body.authenticated .fleet-priority-row{flex-wrap:wrap}body.authenticated .fleet-priority-row>div{flex:1 1 100%}body.authenticated .fleet-priority-open{margin-left:auto}}

    /* Read-only diagnostic guidance; no controls modify GPS devices. */
    #device-detail-modal .diag-guidance{display:grid;gap:11px;padding:15px 17px;border:1px solid #d9e7e8;border-radius:12px;background:#f4f9fa}
    #device-detail-modal .diag-guidance-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
    #device-detail-modal .diag-guidance-head>strong{font-size:14px;color:#25434d}
    #device-detail-modal .diag-severity{padding:6px 10px;border-radius:999px;font-size:11px;font-weight:800}
    #device-detail-modal .diag-severity.critical{background:#ffe8e6;color:#982c29}
    #device-detail-modal .diag-severity.warning{background:#fff0d0;color:#81530b}
    #device-detail-modal .diag-severity.observe{background:#e8f2fb;color:#285e8a}
    #device-detail-modal .diag-severity.normal{background:#e5f5ec;color:#176245}
    #device-detail-modal .diag-guidance ol{display:grid;gap:8px;margin:0;padding-left:21px;color:#324f5c;font-size:12px;line-height:1.6}
    #device-detail-modal .diag-guidance li{padding-left:3px}
    #device-detail-modal .diag-guidance>p{margin:0;padding-top:10px;border-top:1px solid #dce9ea;color:#5e727c;font-size:11px;line-height:1.55}

    body.authenticated .fleet-summary-actions{display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:10px}
    body.authenticated #fleet-last-updated{font-size:11px;color:#58727c;font-variant-numeric:tabular-nums}
    body.authenticated .fleet-refresh{min-height:34px;padding:7px 11px;border:1px solid #bed7da;border-radius:8px;background:#f1f9fa;color:#17636c;font-size:11px;font-weight:750;cursor:pointer}
    body.authenticated .fleet-refresh:hover{background:#e0f3f4}
    body.authenticated .fleet-refresh:disabled{opacity:.65;cursor:wait}
    body.authenticated .fleet-refresh:focus-visible{outline:3px solid #14858d;outline-offset:3px}
    @media(max-width:680px){body.authenticated .fleet-summary-actions{justify-content:flex-start}}

    body.authenticated .fleet-freshness{padding:6px 9px;border-radius:999px;font-size:11px;font-weight:800;white-space:normal}
    body.authenticated .fleet-freshness.fresh{background:#e7f5ed;color:#176544}
    body.authenticated .fleet-freshness.stale{background:#fff0d5;color:#80510c}
    body.authenticated .fleet-freshness.unknown{background:#eef2f4;color:#5c707b}

    body.authenticated .fleet-priority-context{margin:0 0 10px;padding:10px 12px;border-radius:9px;font-size:12px;line-height:1.5}
    body.authenticated .fleet-priority-context.fresh{background:#eff7f8;color:#3e6570;border:1px solid #dcecef}
    body.authenticated .fleet-priority-context.stale{background:#fff4df;color:#7c4e11;border:1px solid #f1d7a5}
    body.authenticated .fleet-priority-context.unavailable{background:#f2f4f6;color:#586c79;border:1px solid #dce4e8}

    body.authenticated .fleet-priority-actions{display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:9px}
    @media(max-width:540px){body.authenticated .fleet-priority-actions{justify-content:flex-start}}

    body.authenticated .fleet-priority-severity{padding:6px 9px;border-radius:999px;font-size:11px;font-weight:800;white-space:nowrap}
    body.authenticated .fleet-priority-severity.critical{background:#fff0ef;color:#922d29}
    body.authenticated .fleet-priority-severity.preventive{background:#fff5df;color:#835411}

    body.authenticated .fleet-priority-filters{display:flex;gap:7px;flex-wrap:wrap;margin:0 0 12px}
    body.authenticated .fleet-priority-filter{padding:7px 13px;border-radius:999px;border:1px solid #c9d9df;background:#fff;color:#4c6774;font-size:12px;font-weight:750;cursor:pointer}
    body.authenticated .fleet-priority-filter.active{background:#176b74;color:#fff;border-color:#176b74}
    body.authenticated .fleet-priority-filter:focus-visible{outline:3px solid #14858d;outline-offset:2px}

    body.authenticated .fleet-priority-search{display:grid;gap:6px;margin:0 0 12px;max-width:420px}
    body.authenticated .fleet-priority-search label{font-size:11.5px;font-weight:750;color:#45616e}
    body.authenticated .fleet-priority-search input{width:100%;min-height:39px;padding:8px 12px;border:1px solid #c6d8df;border-radius:9px;background:#fff;color:#243c49;font:inherit;font-size:13px}
    body.authenticated .fleet-priority-search input:focus-visible{outline:3px solid #14858d;outline-offset:2px}

    body.authenticated .fleet-priority-search-controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
    body.authenticated .fleet-priority-search-controls input{flex:1 1 170px;min-width:0}
    body.authenticated .fleet-priority-clear{min-height:39px;padding:8px 12px;border:1px solid #bfd5d8;border-radius:9px;background:#edf7f7;color:#176b74;font-size:12px;font-weight:750;cursor:pointer}
    body.authenticated .fleet-priority-clear:disabled{opacity:.5;cursor:not-allowed}
    body.authenticated .fleet-priority-clear:focus-visible{outline:3px solid #14858d;outline-offset:2px}

    body.authenticated .fleet-priority-visible-count{margin:0 0 10px;color:#4b6571;font-size:12px;font-weight:650;line-height:1.45}

    body.authenticated .fleet-priority-more{justify-self:start;margin-top:5px;padding:9px 15px;border:1px solid #b7d5da;border-radius:9px;background:#eaf5f6;color:#176b74;font-size:12px;font-weight:800;cursor:pointer}
    body.authenticated .fleet-priority-more:hover{background:#d9edef}
    body.authenticated .fleet-priority-more:focus-visible{outline:3px solid #14858d;outline-offset:2px}

    body.authenticated .fleet-priority-less{justify-self:start;margin-top:5px;padding:9px 15px;border:1px solid #ccd9df;border-radius:9px;background:#fff;color:#3c6572;font-size:12px;font-weight:800;cursor:pointer}
    body.authenticated .fleet-priority-less:hover{background:#f2f7f8}
    body.authenticated .fleet-priority-less:focus-visible{outline:3px solid #14858d;outline-offset:2px}

    body.authenticated .fleet-priority-export{min-height:39px;padding:8px 12px;border:1px solid #176b74;border-radius:9px;background:#176b74;color:#fff;font-size:12px;font-weight:750;cursor:pointer}
    body.authenticated .fleet-priority-export:disabled{opacity:.5;cursor:not-allowed}
    body.authenticated .fleet-priority-export:focus-visible{outline:3px solid #14858d;outline-offset:2px}

    body.authenticated .fleet-priority-export-warning{font-size:12px;font-weight:750;color:#9a4e19;line-height:1.4}
    body.authenticated .fleet-priority-export-warning[hidden]{display:none}
</style>
  <script src="/manager/app.js" defer></script>
</head>
<body>
  <main>
    <header class="brand"><div class="mark"><svg class="brand-symbol" viewBox="0 0 64 64" aria-hidden="true"><path d="M32 5C20.4 5 11 14.4 11 26c0 15.8 21 33 21 33s21-17.2 21-33C53 14.4 43.6 5 32 5Z" fill="none" stroke="currentColor" stroke-width="4"/><circle cx="32" cy="25" r="7" fill="none" stroke="currentColor" stroke-width="4"/></svg></div><div class="brand-copy"><p class="brand-name"><span>Geocontrol</span><b>GPS</b></p><p class="brand-slogan">Traccar Manager</p></div></header>
    <div id="phase-banner" hidden></div>
    <div id="boot-status" class="boot-clean boot-spinner" role="status" aria-label="Cargando"><span></span></div>
    <section id="login-panel" class="login-shell" aria-labelledby="login-title" hidden>

      <div class="login-card"><div class="login-card-head"><div class="login-lock" aria-hidden="true"><svg width="23" height="23" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/><circle cx="12" cy="15" r="1"/></svg></div><div><h2 id="login-title">Iniciar sesión</h2><p class="muted">Accede a tu cuenta administrativa</p></div></div>
      <form id="login-form" action="/manager/api/auth/login" method="post" autocomplete="on">
        <label for="username">Usuario</label><input id="username" name="username" autocomplete="username" maxlength="64" required>
        <label for="password">Contraseña</label><input id="password" name="password" type="password" autocomplete="current-password" maxlength="1024" required>
        <button id="login-button" type="submit">Acceder al Manager</button>
      </form><p id="login-error" class="error" role="alert" hidden></p></div>
    </section>
    <div id="session-bar" class="toolbar" hidden>
      <p class="muted">Sesión autenticada</p>
      <button id="logout-button" class="secondary" type="button">Cerrar sesión</button>
    </div>
    <section id="access-panel" class="notice" aria-live="polite" hidden>
      No tienes permiso para acceder al dashboard.
    </section>
    <section id="dashboard-panel" aria-labelledby="dashboard-title" hidden>
      <div class="dashboard-heading"><div><p class="eyebrow">RESUMEN OPERATIVO</p><h2 id="dashboard-title">Dashboard</h2></div><span class="dashboard-live">● Supervisión activa</span></div>
      <div class="manager-shell"><button id="sidebar-overlay" class="sidebar-overlay" type="button" aria-label="Cerrar menú"></button><aside class="manager-sidebar" aria-label="Navegación principal"><div class="sidebar-brand"><span>GC</span><strong><b>Geocontrol</b><em>GPS</em></strong></div><nav class="manager-nav"><button type="button" class="nav-item active" data-section="summary"><b><svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  class="ui-icon"
>
  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
  <path d="M5 4h4a1 1 0 0 1 1 1v6a1 1 0 0 1 -1 1h-4a1 1 0 0 1 -1 -1v-6a1 1 0 0 1 1 -1" />
  <path d="M5 16h4a1 1 0 0 1 1 1v2a1 1 0 0 1 -1 1h-4a1 1 0 0 1 -1 -1v-2a1 1 0 0 1 1 -1" />
  <path d="M15 12h4a1 1 0 0 1 1 1v6a1 1 0 0 1 -1 1h-4a1 1 0 0 1 -1 -1v-6a1 1 0 0 1 1 -1" />
  <path d="M15 4h4a1 1 0 0 1 1 1v2a1 1 0 0 1 -1 1h-4a1 1 0 0 1 -1 -1v-2a1 1 0 0 1 1 -1" />
</svg></b><span>Dashboard</span></button><button type="button" class="nav-item" data-section="server"><b><svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  class="ui-icon"
>
  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
  <path d="M3 7a3 3 0 0 1 3 -3h12a3 3 0 0 1 3 3v2a3 3 0 0 1 -3 3h-12a3 3 0 0 1 -3 -3v-2" />
  <path d="M3 15a3 3 0 0 1 3 -3h12a3 3 0 0 1 3 3v2a3 3 0 0 1 -3 3h-12a3 3 0 0 1 -3 -3l0 -2" />
  <path d="M7 8l0 .01" />
  <path d="M7 16l0 .01" />
</svg></b><span>Servidor</span></button><button type="button" class="nav-item" data-section="database"><b><svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  class="ui-icon"
>
  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
  <path d="M4 6a8 3 0 1 0 16 0a8 3 0 1 0 -16 0" />
  <path d="M4 6v6a8 3 0 0 0 16 0v-6" />
  <path d="M4 12v6a8 3 0 0 0 16 0v-6" />
</svg></b><span>Base de datos</span></button><button type="button" class="nav-item" data-section="devices"><b>◉</b><span>Dispositivos</span></button><button type="button" class="nav-item" data-section="maintenance"><b><svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  class="ui-icon"
>
  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
  <path d="M10.325 4.317c.426 -1.756 2.924 -1.756 3.35 0a1.724 1.724 0 0 0 2.573 1.066c1.543 -.94 3.31 .826 2.37 2.37a1.724 1.724 0 0 0 1.065 2.572c1.756 .426 1.756 2.924 0 3.35a1.724 1.724 0 0 0 -1.066 2.573c.94 1.543 -.826 3.31 -2.37 2.37a1.724 1.724 0 0 0 -2.572 1.065c-.426 1.756 -2.924 1.756 -3.35 0a1.724 1.724 0 0 0 -2.573 -1.066c-1.543 .94 -3.31 -.826 -2.37 -2.37a1.724 1.724 0 0 0 -1.065 -2.572c-1.756 -.426 -1.756 -2.924 0 -3.35a1.724 1.724 0 0 0 1.066 -2.573c-.94 -1.543 .826 -3.31 2.37 -2.37c1 .608 2.296 .07 2.572 -1.065" />
  <path d="M9 12a3 3 0 1 0 6 0a3 3 0 0 0 -6 0" />
</svg></b><span>Mantenimiento</span></button><button type="button" class="nav-item" data-section="alerts"><b><svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  class="ui-icon"
>
  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
  <path d="M12 9v4" />
  <path d="M10.363 3.591l-8.106 13.534a1.914 1.914 0 0 0 1.636 2.871h16.214a1.914 1.914 0 0 0 1.636 -2.87l-8.106 -13.536a1.914 1.914 0 0 0 -3.274 0" />
  <path d="M12 16h.01" />
</svg></b><span>Centro de alertas</span></button><button type="button" class="nav-item" data-section="audit"><b><svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  class="ui-icon"
>
  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
  <path d="M11.46 20.846a12 12 0 0 1 -7.96 -14.846a12 12 0 0 0 8.5 -3a12 12 0 0 0 8.5 3a12 12 0 0 1 -.09 7.06" />
  <path d="M15 19l2 2l4 -4" />
</svg></b><span>Auditoría</span></button></nav></aside><div class="manager-content"><div class="manager-topbar"><button id="sidebar-toggle" class="icon-button" type="button" aria-label="Alternar menú"><svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  class="ui-icon"
>
  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
  <path d="M4 6l16 0" />
  <path d="M4 12l16 0" />
  <path d="M4 18l16 0" />
</svg></button><div class="topbar-spacer"></div><button id="notification-button" class="notification-button" type="button" aria-label="Abrir alertas"><svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  class="ui-icon"
>
  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
  <path d="M10 5a2 2 0 1 1 4 0a7 7 0 0 1 4 6v3a4 4 0 0 0 2 3h-16a4 4 0 0 0 2 -3v-3a7 7 0 0 1 4 -6" />
  <path d="M9 17v1a3 3 0 0 0 6 0v-1" />
</svg><span id="notification-count" hidden>0</span></button><button type="button" id="account-button" class="account-chip"><span><svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  class="ui-icon"
>
  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
  <path d="M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0" />
  <path d="M9 10a3 3 0 1 0 6 0a3 3 0 1 0 -6 0" />
  <path d="M6.168 18.849a4 4 0 0 1 3.832 -2.849h4a4 4 0 0 1 3.834 2.855" />
</svg></span> Cuenta</button></div><div id="notification-drawer" class="notification-drawer" hidden><div><strong>Alertas</strong><button id="notification-close" type="button" aria-label="Cerrar">×</button></div><div id="notification-list"><p class="muted">Verificando alertas…</p></div><button type="button" class="secondary" data-go-section="alerts">Ver todas las alertas</button></div><div id="account-drawer" class="notification-drawer account-drawer" hidden><div><strong>Mi cuenta</strong><button id="account-drawer-close" type="button" aria-label="Cerrar">×</button></div><div class="account-drawer-profile"><div class="account-drawer-avatar"><img id="account-drawer-avatar-img" hidden alt=""><span id="account-drawer-initial">A</span></div><div><strong id="account-drawer-name">Administrador</strong><span id="account-drawer-email">Cuenta administrativa</span></div></div><button type="button" class="account-drawer-action" data-account-open="profile">Perfil</button><button type="button" class="account-drawer-action" data-account-open="security">Seguridad</button><div id="account-modal-content"></div><div class="account-drawer-footer"><button id="account-logout-button" class="danger-logout" type="button">Cerrar sesión</button></div></div>
      <section id="executive-kpis" class="executive-kpis" data-view="summary"><article><span class="kpi-icon"><svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  class="ui-icon"
>
  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
  <path d="M3 12h4l3 8l4 -16l3 8h4" />
</svg></span><div><small>Traccar</small><strong id="kpi-traccar">Verificando</strong><em>Servicio principal</em></div></article><article><span class="kpi-icon"><svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  class="ui-icon"
>
  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
  <path d="M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0" />
  <path d="M11 12a1 1 0 1 0 2 0a1 1 0 1 0 -2 0" />
  <path d="M7 12a5 5 0 0 1 5 -5" />
  <path d="M12 17a5 5 0 0 0 5 -5" />
</svg></span><div><small>Disco</small><strong id="kpi-disk">—</strong><em id="kpi-disk-detail">Capacidad del servidor</em></div></article><article><span class="kpi-icon"><svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  class="ui-icon"
>
  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
  <path d="M4 6a8 3 0 1 0 16 0a8 3 0 1 0 -16 0" />
  <path d="M4 6v6a8 3 0 0 0 16 0v-6" />
  <path d="M4 12v6a8 3 0 0 0 16 0v-6" />
</svg></span><div><small>Base de datos</small><strong id="kpi-database">—</strong><em>Plataforma MySQL</em></div></article><article><span class="kpi-icon"><svg
  xmlns="http://www.w3.org/2000/svg"
  width="24"
  height="24"
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="2"
  stroke-linecap="round"
  stroke-linejoin="round"
  class="ui-icon"
>
  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
  <path d="M12 9v4" />
  <path d="M10.363 3.591l-8.106 13.534a1.914 1.914 0 0 0 1.636 2.871h16.214a1.914 1.914 0 0 0 1.636 -2.87l-8.106 -13.536a1.914 1.914 0 0 0 -3.274 0" />
  <path d="M12 16h.01" />
</svg></span><div><small>Alertas</small><strong id="kpi-alerts">Verificando</strong><em>Centro administrativo</em></div></article></section>
      <section id="operational-health-summary" class="operational-health-summary" data-view="summary"><div><small>SALUD OPERACIONAL</small><strong id="operational-health-state">Verificando…</strong><span id="operational-health-cause">Consolidando controles del servidor.</span></div><div id="operational-health-factors" class="operational-health-factors"></div></section>
      <section id="fleet-summary" class="fleet-summary" data-view="summary" aria-labelledby="fleet-summary-title"><div class="fleet-summary-heading"><div><p class="eyebrow">VISIÓN GENERAL DE DISPOSITIVOS</p><h3 id="fleet-summary-title">Estado de la flota</h3><p id="fleet-summary-note">Consultando el inventario protegido…</p></div><div class="fleet-summary-actions"><span id="fleet-freshness" class="fleet-freshness" role="status" aria-live="polite">Pendiente de actualización</span><span id="fleet-last-updated" role="status" aria-live="polite">Sin actualización confirmada</span><button type="button" id="fleet-refresh" class="fleet-refresh" aria-label="Actualizar datos del inventario">↻ Actualizar</button><button type="button" class="text-action" data-go-section="devices">Ver inventario</button></div></div><div class="fleet-summary-grid" aria-label="Resumen de dispositivos"><div class="fleet-summary-tile"><span>Total</span><strong id="fleet-summary-total">—</strong><small>Dispositivos registrados</small></div><div class="fleet-summary-tile fleet-online"><span>En línea</span><strong id="fleet-online">—</strong><small>Conectados</small></div><div class="fleet-summary-tile fleet-attention"><span>Requieren atención</span><strong id="fleet-attention">—</strong><small>Inactivos o sin reporte +24 h</small></div><div class="fleet-summary-tile"><span>Otros estados</span><strong id="fleet-other">—</strong><small>Recientes o deshabilitados</small></div></div><div class="fleet-priority" aria-labelledby="fleet-priority-title"><div class="fleet-priority-head"><div><strong id="fleet-priority-title">Prioridades de revisión</strong><p>Solo estado administrativo y nombre del dispositivo; sin ubicación ni identificadores técnicos.</p></div><div class="fleet-priority-actions"><span id="fleet-priority-count" class="fleet-priority-count">Verificando…</span><span id="fleet-priority-critical" class="fleet-priority-severity critical" aria-label="Prioridades críticas">Críticas: —</span><span id="fleet-priority-preventive" class="fleet-priority-severity preventive" aria-label="Prioridades preventivas">Preventivas: —</span><button type="button" id="fleet-priority-refresh" class="fleet-refresh" aria-label="Actualizar prioridades de revisión">↻ Actualizar prioridades</button></div></div><p id="fleet-priority-context" class="fleet-priority-context" role="status" aria-live="polite">Pendiente de datos confirmados.</p><div class="fleet-priority-filters" role="group" aria-label="Filtrar prioridades"><button type="button" class="fleet-priority-filter active" data-priority-filter="all" aria-pressed="true">Todas</button><button type="button" class="fleet-priority-filter" data-priority-filter="critical" aria-pressed="false">Críticas</button><button type="button" class="fleet-priority-filter" data-priority-filter="preventive" aria-pressed="false">Preventivas</button></div><div class="fleet-priority-search"><label for="fleet-priority-search-input">Buscar dispositivo por nombre</label><div class="fleet-priority-search-controls"><input type="search" id="fleet-priority-search-input" placeholder="Nombre del dispositivo" autocomplete="off" aria-controls="fleet-priority-list"><button type="button" id="fleet-priority-clear" class="fleet-priority-clear" disabled>Limpiar filtros</button><button type="button" id="fleet-priority-export" class="fleet-priority-export" disabled>Exportar prioridades (CSV)</button><span id="fleet-priority-export-warning" class="fleet-priority-export-warning" role="status" aria-live="polite" hidden>Datos desactualizados (+15 min). Actualiza antes de exportar.</span></div></div><p id="fleet-priority-visible-count" class="fleet-priority-visible-count" role="status" aria-live="polite">Esperando inventario…</p><div id="fleet-priority-list" class="fleet-priority-list" role="status"><p>Consultando dispositivos que necesitan atención…</p></div></div></section>
      <section id="dashboard-overview" class="dashboard-overview" data-view="summary"><article class="overview-chart"><div class="overview-head"><div><small>RECURSOS DEL SERVIDOR</small><h3>Salud y capacidad</h3></div><button type="button" class="text-action" data-go-section="server">Ver detalles</button></div><div class="overview-meters"><div class="overview-ring-metric"><span>Disco</span><div class="overview-ring" id="overview-disk-ring"><strong id="overview-disk">—</strong></div></div><div class="overview-ring-metric"><span>Memoria</span><div class="overview-ring" id="overview-memory-ring"><strong id="overview-memory">—</strong></div></div></div><p id="overview-resource-detail">Cargando métricas verificadas…</p></article><article class="overview-services"><div class="overview-head"><div><small>SERVICIOS</small><h3>Estado operativo</h3></div><button type="button" class="text-action" data-go-section="server">Ver todos</button></div><div id="overview-services-list" class="overview-services-list"><span>Verificando componentes…</span></div></article></section>
<section id="administrative-attention" class="administrative-attention" data-view="summary"><div class="overview-head"><div><small>ATENCIÓN ADMINISTRATIVA</small><h3>Intervenciones</h3></div><button type="button" class="text-action" id="admin-attention-all">Ver Auditoría</button></div><div id="admin-attention-state" class="admin-attention-state normal"><div><small>ESTADO CONSOLIDADO</small><strong id="admin-attention-state-label">Normal</strong></div><span id="admin-attention-state-cause">Sin intervenciones administrativas que requieran seguimiento.</span></div><div id="admin-attention-index" class="admin-attention-index optimal"><div class="admin-index-score"><small>ÍNDICE ADMINISTRATIVO</small><strong id="admin-index-score">100</strong><span id="admin-index-label">Óptimo</span></div><div id="admin-index-factors" class="admin-index-factors"><span>Sin penalizaciones activas.</span></div></div><div class="admin-index-history"><div class="admin-history-head"><small>EVOLUCIÓN DEL ÍNDICE</small><span id="admin-index-history-count">0 cambios</span></div><div id="admin-index-history-list" class="admin-index-history-list"><span class="muted">Cargando evolución…</span></div></div><div id="admin-attention-trend" class="admin-attention-trend collecting"><div><small>TENDENCIA ADMINISTRATIVA</small><strong id="admin-attention-trend-label">Recopilando línea base</strong></div><span id="admin-attention-trend-detail">Se requieren 6 horas observadas para establecer dirección.</span></div><div class="admin-attention-metrics"><div><small>ÚLTIMAS 24 H</small><strong id="admin-metric-24">Recopilando…</strong><span id="admin-metric-24-detail">Cobertura observada</span></div><div><small>ÚLTIMOS 7 DÍAS</small><strong id="admin-metric-7d">Recopilando…</strong><span id="admin-metric-7d-detail">Cobertura observada</span></div></div><div class="admin-attention-history"><div class="admin-history-head"><small>HISTORIAL DE ESTADO</small><span id="admin-history-count">0 transiciones</span></div><div id="admin-attention-history-list" class="admin-history-list"><span class="muted">Cargando historial…</span></div></div><div class="admin-attention-grid"><button type="button" data-admin-attention="progress"><small>EN CURSO</small><strong id="admin-attention-progress">0</strong><span>Preparadas o autorizadas</span></button><button type="button" data-admin-attention="stalled"><small>ESTANCADAS</small><strong id="admin-attention-stalled">0</strong><span>Requieren revisión</span></button><button type="button" data-admin-attention="failed"><small>FALLIDAS</small><strong id="admin-attention-failed">0</strong><span>Finalizadas con error</span></button></div></section>
      <section id="alerts-panel" class="alerts-panel" data-view="summary" aria-labelledby="alerts-title"><div class="alerts-head"><div><p class="eyebrow">ALERTAS ADMINISTRATIVAS</p><h3 id="alerts-title">Estado consolidado</h3></div><span id="alerts-badge" class="alerts-badge">Verificando…</span></div><div id="alerts-list" class="alerts-list"><div class="alert-item neutral"><strong>Evaluando controles</strong><span>Esperando métricas verificadas del servidor.</span></div></div></section>
      <div id="capacity-card" class="capacity-card" data-view="summary"><div><span>PROYECCIÓN DE CAPACIDAD</span><strong id="capacity-state">Recopilando datos…</strong></div><p id="capacity-detail">La estimación se habilita con al menos 12 muestras y una hora de observación.</p></div>
      <div class="health-strip" data-view="audit" aria-label="Resumen de salud"><div><span>Traccar</span><strong id="health-traccar">Verificando…</strong></div><div><span>Servidor</span><strong id="health-server">Verificando…</strong></div><div><span>Base de datos</span><strong id="health-database">Verificando…</strong></div><div><span>Protecciones</span><strong id="health-protections">Verificando…</strong></div></div>
<div class="audit-panel" data-view="audit"><div class="audit-panel-head"><div><h3>Intervenciones vinculadas</h3><p class="muted">Vista global de intervenciones con incidente explícito · solo lectura</p></div><strong id="global-intervention-count">0 intervenciones</strong></div><div class="intervention-kpis"><div><small>TOTAL</small><strong id="intervention-kpi-total">0</strong></div><div class="executed"><small>EJECUTADAS</small><strong id="intervention-kpi-executed">0</strong></div><div class="progress"><small>EN CURSO</small><strong id="intervention-kpi-progress">0</strong></div><div class="failed"><small>FALLIDAS</small><strong id="intervention-kpi-failed">0</strong></div><div class="stalled"><small>ESTANCADAS</small><strong id="intervention-kpi-stalled">0</strong></div></div><div class="intervention-filters"><label>Buscar<input id="intervention-search" type="search" placeholder="Incidente u operación" autocomplete="off"></label><label>Resultado<select id="intervention-result"><option value="">Todos</option><option value="EXECUTED">Ejecutada</option><option value="AUTHORIZED">Autorizada</option><option value="PREPARED">Preparada</option><option value="FAILED">Fallida</option><option value="NONE">Sin intervención</option></select></label><label>Período<select id="intervention-period"><option value="0">Todo</option><option value="24">24 horas</option><option value="168">7 días</option><option value="720">30 días</option></select></label><button id="intervention-clear" type="button" class="secondary">Limpiar</button></div><div id="global-interventions" class="global-interventions"><p class="muted">Cargando intervenciones…</p></div></div>
      <div class="audit-panel" data-view="audit"><div class="audit-panel-head"><div><h3>Actividad administrativa reciente</h3><p class="muted">Eventos sanitizados de esta instancia · sin credenciales, cookies, IP ni payloads</p></div><strong id="audit-count">0 eventos</strong></div><div id="audit-events" class="audit-events"><p class="muted">Cargando actividad…</p></div></div>
      <div class="dashboard-grid">
      <article class="card data-provider" data-view="server" aria-labelledby="traccar-title">
        <h3 id="traccar-title">Traccar</h3>
        <p id="traccar-state" class="status">Proveedor pendiente</p>
        <p id="traccar-detail" class="muted">El estado real del servicio no se consulta en esta fase.</p>
      </article>
      <article id="capacity-center" class="card capacity-center" data-view="server" aria-labelledby="capacity-center-title"><div class="capacity-center-head"><div><h3 id="capacity-center-title">Centro de capacidad</h3><p class="muted">Distribución verificable del almacenamiento del servidor</p></div><strong id="capacity-free">— libres</strong></div><div id="capacity-breakdown" class="capacity-breakdown"><p class="muted">Cargando distribución…</p></div><p id="capacity-accounting" class="muted">Los componentes se miden desde el auditor de solo lectura.</p><div id="growth-diagnosis" class="growth-diagnosis"><div><strong id="growth-state">Recopilando línea base…</strong><span id="growth-detail">Se requiere al menos una hora de métricas por componente.</span></div><p id="growth-recommendation" class="growth-recommendation" hidden></p></div></article>
      <article id="diagnostic-center" class="card diagnostic-center" data-view="server" aria-labelledby="diagnostic-title"><div class="diagnostic-head"><div><p class="eyebrow">DIAGNÓSTICO OPERATIVO</p><h3 id="diagnostic-title">Análisis preventivo</h3><p class="muted">Interpretación de tendencias verificadas · recomendaciones de solo lectura</p></div><span id="diagnostic-risk" class="diagnostic-risk">Recopilando</span></div><div class="diagnostic-grid"><div><small>CAUSA PRINCIPAL</small><strong id="diagnostic-cause">—</strong><span id="diagnostic-cause-detail">Esperando línea base suficiente.</span></div><div><small>RITMO ESTIMADO</small><strong id="diagnostic-rate">—</strong><span id="diagnostic-share">Regresión sobre la ventana observada.</span></div><div class="diagnostic-action"><small>ACCIÓN RECOMENDADA</small><strong id="diagnostic-action-title">Observación segura</strong><span id="diagnostic-action-detail">No se ejecutan acciones destructivas desde este diagnóstico.</span></div></div><p class="diagnostic-safety">Solo lectura · sin limpieza automática · cualquier mantenimiento destructivo permanece aislado tras las protecciones del Manager.</p></article><article id="capacity-forecast" class="card capacity-forecast" data-view="server" aria-labelledby="forecast-title"><div class="forecast-head"><div><p class="eyebrow">PREVENCIÓN DE CAPACIDAD</p><h3 id="forecast-title">Horizonte operativo</h3><p class="muted">Proyección preventiva basada en la tendencia reciente del filesystem.</p></div><span id="forecast-priority" class="diagnostic-risk">Recopilando</span></div><div class="forecast-grid"><div><small>USO ACTUAL</small><strong id="forecast-current">—</strong><span>Filesystem principal</span></div><div><small>UMBRAL DE AVISO · 80%</small><strong id="forecast-warning">—</strong><span id="forecast-warning-detail">Calculando horizonte</span></div><div><small>UMBRAL CRÍTICO · 90%</small><strong id="forecast-critical">—</strong><span id="forecast-critical-detail">Calculando horizonte</span></div></div><p id="forecast-guidance" class="diagnostic-safety">La proyección es orientativa y no autoriza mantenimiento automático.</p></article>
      <article id="operational-availability" class="card operational-availability" data-view="server" aria-labelledby="availability-title"><div class="incident-head"><div><p class="eyebrow">SLO INTERNO</p><h3 id="availability-title">Disponibilidad operacional</h3><p class="muted">Tiempo estable frente a estados de Atención/Crítico · incluye cobertura real del histórico.</p></div><strong>Estabilidad medida</strong></div><div class="availability-grid"><div class="availability-window"><span>ÚLTIMAS 24 HORAS</span><strong id="availability-24">—</strong><small id="availability-24-detail">Calculando…</small><div class="availability-meter"><i id="availability-24-bar"></i></div><em id="availability-24-coverage">Cobertura —</em></div><div class="availability-window"><span>ÚLTIMOS 7 DÍAS</span><strong id="availability-7d">—</strong><small id="availability-7d-detail">Calculando…</small><div class="availability-meter"><i id="availability-7d-bar"></i></div><em id="availability-7d-coverage">Cobertura —</em></div></div><div class="slo-budget"><div><small>OBJETIVO SLO</small><strong>99.9%</strong><span>Estabilidad operacional</span></div><div><small>PRESUPUESTO 24 H</small><strong id="budget-24">1.44 min</strong><span id="budget-24-state">Provisional</span></div><div><small>PRESUPUESTO 7 DÍAS</small><strong id="budget-7d">10.08 min</strong><span id="budget-7d-state">Provisional</span></div></div><div class="slo-forecast"><div><small>TENDENCIA 24 H</small><strong id="forecast-slo-24">Recopilando línea base</strong><span id="forecast-slo-24-detail">Se requieren datos suficientes antes de proyectar.</span></div><div><small>TENDENCIA 7 DÍAS</small><strong id="forecast-slo-7d">Recopilando línea base</strong><span id="forecast-slo-7d-detail">Se requieren datos suficientes antes de proyectar.</span></div></div><p class="diagnostic-safety">“Estable” agrupa Saludable + Observación. Atención y Crítico consumen presupuesto de error. Las proyecciones solo se activan con una línea base temporal suficiente.</p></article>
      <article id="operational-health-history" class="card operational-health-history" data-view="server" aria-labelledby="health-history-title"><div class="incident-head"><div><p class="eyebrow">ESTABILIDAD DEL SISTEMA</p><h3 id="health-history-title">Historial de salud operacional</h3><p class="muted">Transiciones persistentes del estado consolidado del servidor.</p></div><strong id="health-history-count">0 transiciones</strong></div><div id="health-history-timeline" class="health-history-timeline"><p class="muted">Cargando línea temporal…</p></div></article>
      <article id="preventive-diagnostics" class="card preventive-diagnostics" data-view="server" aria-labelledby="preventive-diagnostics-title"><div class="incident-head"><div><p class="eyebrow">DIAGNÓSTICO PREVENTIVO</p><h3 id="preventive-diagnostics-title">Centro de diagnóstico</h3><p class="muted">Causa probable, evidencia y recomendación segura para incidentes activos.</p></div><strong id="diagnostic-count">0 activos</strong></div><div id="diagnostic-list" class="diagnostic-list"><p class="muted">Cargando diagnósticos…</p></div><p class="diagnostic-safety">Modo recomendación: esta sección no ejecuta mantenimiento ni modifica Traccar, MySQL o datos GPS.</p></article>
      <div id="intervention-detail-modal" class="casefile-modal" aria-hidden="true"><div class="casefile-shell" role="dialog" aria-modal="true" aria-labelledby="intervention-detail-title"><div class="casefile-head"><div><p class="eyebrow">TRAZABILIDAD AUDITADA</p><h3 id="intervention-detail-title">Intervención</h3></div><button id="intervention-detail-close" type="button" aria-label="Cerrar">×</button></div><div id="intervention-detail-body" class="casefile-body"></div></div></div>
<div id="casefile-modal" class="casefile-modal" aria-hidden="true"><div class="casefile-shell" role="dialog" aria-modal="true" aria-labelledby="casefile-title"><div class="casefile-head"><div><p class="eyebrow">EXPEDIENTE OPERACIONAL</p><h3 id="casefile-title">Incidente</h3></div><button id="casefile-close" type="button" aria-label="Cerrar">×</button></div><div id="casefile-body" class="casefile-body"></div></div></div>
      <article id="incident-history" class="card incident-history" data-view="server" aria-labelledby="incident-title"><div class="incident-head"><div><p class="eyebrow">HISTORIAL OPERATIVO</p><h3 id="incident-title">Incidentes preventivos</h3><p class="muted">Cambios persistentes de riesgo detectados por el auditor.</p></div><strong id="incident-count">0 incidentes</strong></div><div id="incident-list" class="incident-list"><p class="muted">Cargando historial…</p></div></article>
      <article id="trends-card" class="card trends-card" data-view="server" aria-labelledby="trends-title"><div class="trends-head"><div><h3 id="trends-title">Tendencias de salud</h3><p class="muted">Histórico persistente · retención máxima 7 días</p></div><div class="trend-tabs"><button type="button" class="trend-tab active" data-hours="24">24 h</button><button type="button" class="trend-tab" data-hours="168">7 días</button></div></div><div class="trend-legend"><span>Disco</span><span>Memoria</span><span>Logs</span><span>Base de datos</span></div><div id="trend-chart" class="trend-chart" aria-label="Gráfico de tendencias"><svg viewBox="0 0 600 150" preserveAspectRatio="none"></svg></div><p id="trend-detail" class="muted">Recopilando primeras muestras…</p></article>
      <article id="services-card" class="card" data-view="server" aria-labelledby="services-title"><h3 id="services-title">Servicios</h3><p id="services-state" class="status">Verificando componentes…</p><div id="services-grid" class="services-grid"></div><p id="services-observed" class="muted">Snapshot de solo lectura.</p></article>
      <article id="server-card" class="card" data-view="server audit" aria-labelledby="server-title">
        <h3 id="server-title">Servidor</h3>
        <p id="server-state" class="status">Cargando estado…</p>
        <div class="metric-charts" aria-label="Uso de recursos">
          <div class="metric-chart"><div class="metric-chart-head"><span>Disco</span><strong id="server-disk">—</strong></div><div id="disk-meter" class="meter"><span></span></div><div class="metric-foot"><span id="server-free">— libres</span><span>80% aviso · 90% crítico</span></div></div>
          <div class="metric-chart"><div class="metric-chart-head"><span>Memoria</span><strong id="memory-percent">—</strong></div><div id="memory-meter" class="meter"><span></span></div><div class="metric-foot"><span id="server-memory">—</span><span>uso actual</span></div></div>
        </div>
        <div class="maintenance-summary"><div><span>Logs Traccar</span><strong id="server-logs">—</strong></div><div><span>Históricos</span><strong id="server-history-count">—</strong></div></div>
        <div id="storage-protection" class="boundary-card" style="margin-top:13px">
          <strong>Protecciones de almacenamiento</strong>
          <span id="storage-protection-state">Comprobando políticas…</span>
          <span id="journal-protection">Journal: verificando…</span>
          <span id="binlog-protection">Binlogs MySQL: verificando…</span>
          <div class="protection-bars"><div class="protection-row"><span>Journal</span><div id="journal-meter" class="meter"><span></span></div><strong id="journal-meter-value">—</strong></div><div class="protection-row"><span>Binlogs</span><div id="binlog-meter" class="meter"><span></span></div><strong id="binlog-meter-value">—</strong></div></div>
          <span id="storage-protection-time">Última verificación: —</span>
        </div>
        <p id="server-detail" class="muted">Solo lectura · sin shell · sin MySQL desde la web</p>
      </article>
      <article id="database-card" class="card" data-view="database" aria-labelledby="database-title">
        <h3 id="database-title">Base de datos</h3>
        <p id="database-state" class="status">Cargando metadatos…</p>
        <div class="metric-charts"><div class="metric-chart"><div class="metric-chart-head"><span>Plataforma</span><strong id="database-total">—</strong></div><div id="database-index-meter" class="meter" aria-label="Proporción de índices"><span></span></div><div class="metric-foot"><span id="database-data">— datos</span><span id="database-index">— índices</span></div></div><div class="metric-chart"><div class="metric-chart-head"><span>tc_positions</span><strong id="positions-total">—</strong></div><div id="positions-meter" class="meter"><span></span></div><div class="metric-foot"><span id="positions-rows">— filas estimadas</span><span id="positions-share">— del esquema</span></div></div></div>
        <div class="maintenance-summary"><div><span>Tablas</span><strong id="database-tables">—</strong></div><div><span>Dispositivos</span><strong id="devices-total">—</strong></div><div><span>Habilitados</span><strong id="devices-enabled">—</strong></div><div><span>Deshabilitados</span><strong id="devices-disabled">—</strong></div></div>
        <p id="database-detail" class="muted">Metadatos y conteos agregados verificados · solo lectura · sin IDs, nombres ni coordenadas</p>
      </article>
      <section id="devices-overview" class="card full-card" data-view="devices" aria-labelledby="devices-title"><div class="section-intro"><div><p class="eyebrow">FLOTA TRACCAR</p><h3 id="devices-title">Dispositivos</h3><p class="muted">Estado agregado de la flota · lectura operacional segura · sin identificadores ni coordenadas</p></div><strong id="devices-observed">Verificando…</strong></div><div class="maintenance-summary"><div><span>Total</span><strong id="fleet-total">—</strong></div><div><span>Habilitados</span><strong id="fleet-enabled">—</strong></div><div><span>Deshabilitados</span><strong id="fleet-disabled">—</strong></div><div><span>Sin reporte +24 h</span><strong id="fleet-stale">—</strong></div></div><div class="metric-charts"><div class="metric-chart"><div class="metric-chart-head"><span>Actividad reciente</span><strong id="fleet-live-percent">—</strong></div><div id="fleet-live-meter" class="meter"><span></span></div><div class="metric-foot"><span id="fleet-live">— en últimos 15 min</span><span id="fleet-enabled-base">— habilitados</span></div></div><div class="metric-chart"><div class="metric-chart-head"><span>Actividad últimas 24 h</span><strong id="fleet-active-24">—</strong></div><div id="fleet-active-meter" class="meter"><span></span></div><div class="metric-foot"><span id="fleet-recent">— entre 15–60 min</span><span id="fleet-day">— entre 1–24 h</span></div></div></div><div id="fleet-health-card" class="capacity-card" style="margin-top:13px"><div><span>SALUD DE FLOTA</span><strong id="fleet-health">Calculando…</strong></div><p id="fleet-health-detail">Evaluando actividad de dispositivos habilitados.</p></div><div class="maintenance-summary"><div><span>Online · ≤15 min</span><strong id="fleet-state-online">—</strong></div><div><span>Reciente · 15–60 min</span><strong id="fleet-state-recent">—</strong></div><div><span>Inactivo · 1–24 h</span><strong id="fleet-state-day">—</strong></div><div><span>Sin reporte · +24 h</span><strong id="fleet-state-stale">—</strong></div></div><div class="inventory-card"><div class="section-intro"><div><strong>Inventario administrativo</strong><p class="muted">Dispositivos que requieren atención primero.</p></div><div class="inventory-actions"><span id="inventory-count" role="status" aria-live="polite">Cargando…</span><button type="button" id="inventory-refresh" class="fleet-refresh" aria-label="Actualizar inventario de dispositivos">↻ Actualizar inventario</button></div></div><div class="inventory-toolbar"><label class="inventory-search"><span aria-hidden="true">⌕</span><input id="inventory-search" type="search" autocomplete="off" placeholder="Buscar por nombre o empresa" aria-label="Buscar por nombre de dispositivo o empresa"></label><div class="inventory-filter-wrap"><span>Mostrar</span><select id="inventory-filter" aria-label="Filtrar inventario"><option value="ATTENTION">Requieren atención</option><option value="ALL">Todos los dispositivos</option><option value="ONLINE">Online</option><option value="RECENT">Recientes</option><option value="INACTIVE">Inactivos</option><option value="STALE">Sin reporte +24 h</option><option value="DISABLED">Deshabilitados</option></select></div></div><div id="device-inventory-list" class="device-inventory-list"><p class="muted">Cargando inventario seguro…</p></div></div><div id="device-detail-modal" class="casefile-modal" aria-hidden="true"><div class="casefile-shell" role="dialog" aria-modal="true" aria-labelledby="device-detail-title"><div class="casefile-head"><div><p class="eyebrow">FICHA ADMINISTRATIVA</p><h3 id="device-detail-title">Dispositivo</h3></div><button id="device-detail-close" type="button" aria-label="Cerrar">×</button></div><div id="device-detail-body" class="casefile-body"></div></div></div><div class="boundary-card" style="margin-top:13px"><strong>Privacidad operacional</strong><span>Los conteos se calculan en el auditor del servidor. La interfaz no recibe ID, uniqueId, nombre, teléfono, posición ni coordenadas.</span><span>Esta fase es solo lectura: no habilita, deshabilita ni modifica dispositivos.</span></div></section>
      <article id="maintenance-card" class="card" data-view="maintenance" aria-labelledby="maintenance-title">
        <h3 id="maintenance-title">Centro de mantenimiento</h3>
        <p class="muted">Flujo de mantenimiento con controles progresivos. La eliminación productiva solo se autoriza tras respaldo, reverificación, vínculo SHA-256, confirmación y autorización one-shot.</p><p class="status">Evidencia reverificada · prevalidación completa antes de mutar · log activo protegido · fsync durable ante fallo</p><p class="status">Fase 5 productiva · UDS + HMAC + SHA-256 + anti-replay habilitados · eliminación solo con preparación y confirmación válidas</p><div class="safety-flow" aria-label="Flujo de seguridad"><span class="done">1 · Detectar</span><span class="done">2 · Previsualizar</span><span class="done">3 · Clasificar</span><span class="done">4 · Confirmar</span><span id="backup-step" class="pending">5 · Respaldar evidencia</span><span class="pending">6 · Eliminar · protegido</span><span id="verify-step" class="pending">7 · Verificar evidencia</span><span class="done">Frontera UDS canaria + HMAC + anti-replay aprobados</span><span class="done">Producción habilitada · 0 candidatos &gt;90 días · sin eliminación</span></div><div class="boundary-card"><strong>Frontera destructiva aislada</strong><span id="boundary-health">Comprobando frontera de seguridad…</span><span>Sin red · sin shell · autorización one-shot · anti-replay · revalidación · log activo protegido</span></div>
        <label for="retention-days">Retención de logs (días)</label>
        <input id="retention-days" type="number" min="30" max="3650" value="90">
        <button id="preview-logs-button" type="button">Analizar logs</button>
        <button id="prepare-logs-button" class="secondary" type="button" hidden>Preparar limpieza</button>
        <button id="execute-logs-button" class="secondary" type="button" disabled>Validar EXECUTE</button>
        <p id="execute-note" class="muted">Disponible después de preparar un plan con candidatos. EXECUTE exige autorización, evidencia SHA-256, consumo único, anti-replay y revalidación antes de cualquier eliminación.</p>
        <p id="maintenance-preparation" class="muted" hidden></p><p id="backup-evidence" class="muted" hidden></p><p id="verification-evidence" class="muted" hidden></p><p id="maintenance-readiness" class="status" hidden></p>
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
      <article id="alerts-center" class="card full-card" data-view="alerts"><div class="section-intro"><div><p class="eyebrow">CENTRO DE ALERTAS</p><h3>Incidencias y avisos</h3><p class="muted">Estado consolidado del servidor, servicios, almacenamiento y protecciones.</p></div><span id="alerts-center-badge" class="alerts-badge">Verificando…</span></div><div id="alerts-center-list" class="alerts-list"><p class="muted">Cargando alertas…</p></div></article>
      <article id="account-card" class="card full-card account-v2" hidden><div class="section-intro"><div><p class="eyebrow">CUENTA</p><h3 id="profile-display-name">Perfil administrativo</h3><p class="muted">Identidad y seguridad del Manager de Geocontrol GPS.</p></div><label class="profile-avatar" title="Cambiar foto" aria-label="Cambiar foto de perfil" role="button" tabindex="0"><img id="profile-avatar-img" hidden alt="Avatar"><span id="profile-avatar-letter">A</span><input id="profile-avatar-file" type="file" accept="image/png,image/jpeg,image/webp" hidden></label></div><nav class="account-subnav" aria-label="Configuración de cuenta"><button type="button" class="active" data-account-tab="profile">Perfil</button><button type="button" data-account-tab="security">Seguridad</button><button type="button" data-account-tab="session">Sesión</button></nav><div class="account-tab-panels"><section data-account-panel="profile"><h4>Perfil</h4><label for="profile-name">Nombre</label><input id="profile-name" maxlength="80" autocomplete="name" placeholder="Nombre del administrador"><label for="profile-email">Correo electrónico</label><input id="profile-email" type="email" maxlength="254" autocomplete="email" placeholder="correo@empresa.com"><button id="profile-save" type="button">Guardar perfil</button><p id="profile-status" class="muted" role="status" aria-live="polite"></p></section><section data-account-panel="security" hidden><h4>Seguridad</h4><label for="password-current">Contraseña actual</label><input id="password-current" type="password" autocomplete="current-password"><label for="password-new">Nueva contraseña</label><input id="password-new" type="password" minlength="10" autocomplete="new-password"><label for="password-confirm">Confirmar nueva contraseña</label><input id="password-confirm" type="password" minlength="10" autocomplete="new-password"><button id="password-save" type="button">Cambiar contraseña</button><p id="password-status" class="muted" role="status" aria-live="polite">Mínimo 10 caracteres. El cambio queda auditado.</p></section><section data-account-panel="session" hidden><h4>Sesión</h4><div class="account-grid"><div><span>Estado</span><strong>Autenticada</strong></div><div><span>Seguridad</span><strong>Sesión de 15 minutos</strong></div><div><span>Acceso</span><strong>Auditado</strong></div><div><span>Entorno</span><strong>Producción</strong></div></div><div class="logout-zone"><p class="muted">Finaliza de forma segura la sesión administrativa actual.</p><button class="secondary" type="button">Cerrar sesión</button></div></section></div></article>
      </div>
      <p id="dashboard-error" class="error" role="alert" hidden></p></div></div>
    </section>
    <noscript>Activa JavaScript para iniciar sesión y consultar el dashboard.</noscript>
  </main>
</body>
</html>
""".encode("utf-8")



PAGE = PAGE.replace(b'</nav></aside>', '<a href="/manager/progress" style="display:block;padding:13px 10px;color:#54d7e8;text-decoration:none;font-weight:700">☑ Desarrollo y Progreso</a></nav></aside>'.encode('utf-8'), 1)
APP_JS = r"""(() => {
  "use strict";
  const path = window.location.pathname.endsWith("/")
    ? window.location.pathname : window.location.pathname + "/";
  const api = (name) => path + "api/" + name;
  const byId = (name) => document.getElementById(name);
  const boot = byId("boot-status");
  const phaseBanner = byId("phase-banner");
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
  const prepareLogsButton=byId("prepare-logs-button"); const executeLogsButton=byId("execute-logs-button"); const executeNote=byId("execute-note"); const maintenancePreparation=byId("maintenance-preparation"); const maintenanceReadiness=byId("maintenance-readiness"); const maintenanceSecurity=byId("maintenance-security"); let lastPreview=null; let lastPreparation=null; let interventionContext=null;
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
  const serverState=byId("server-state"),serverDisk=byId("server-disk"),serverFree=byId("server-free"),serverMemory=byId("server-memory"),serverLogs=byId("server-logs"),serverDetail=byId("server-detail");
  const diskMeter=byId("disk-meter"),memoryMeter=byId("memory-meter"),memoryPercent=byId("memory-percent"),serverHistoryCount=byId("server-history-count");
  const storageProtectionState=byId("storage-protection-state"),journalProtection=byId("journal-protection"),binlogProtection=byId("binlog-protection"),storageProtectionTime=byId("storage-protection-time");

  const journalMeter=byId("journal-meter"),binlogMeter=byId("binlog-meter"),journalMeterValue=byId("journal-meter-value"),binlogMeterValue=byId("binlog-meter-value");

  const databaseState=byId("database-state"),databaseTotal=byId("database-total"),databaseData=byId("database-data"),databaseIndex=byId("database-index"),databaseIndexMeter=byId("database-index-meter"),databaseTables=byId("database-tables");
  const positionsTotal=byId("positions-total"),positionsMeter=byId("positions-meter"),positionsRows=byId("positions-rows"),positionsShare=byId("positions-share");
  const devicesTotal=byId("devices-total"),devicesEnabled=byId("devices-enabled"),devicesDisabled=byId("devices-disabled");
  const fleetTotal=byId("fleet-total"),fleetEnabled=byId("fleet-enabled"),fleetDisabled=byId("fleet-disabled"),fleetStale=byId("fleet-stale"),fleetLive=byId("fleet-live"),fleetRecent=byId("fleet-recent"),fleetDay=byId("fleet-day"),fleetLivePercent=byId("fleet-live-percent"),fleetActive24=byId("fleet-active-24"),fleetLiveMeter=byId("fleet-live-meter"),fleetActiveMeter=byId("fleet-active-meter"),fleetEnabledBase=byId("fleet-enabled-base"),devicesObserved=byId("devices-observed"),fleetHealth=byId("fleet-health"),fleetHealthDetail=byId("fleet-health-detail"),fleetHealthCard=byId("fleet-health-card"),fleetStateOnline=byId("fleet-state-online"),fleetStateRecent=byId("fleet-state-recent"),fleetStateDay=byId("fleet-state-day"),fleetStateStale=byId("fleet-state-stale");
  const healthTraccar=byId("health-traccar"),healthServer=byId("health-server"),healthDatabase=byId("health-database"),healthProtections=byId("health-protections");
  const auditEvents=byId("audit-events"),auditCount=byId("audit-count");
  const servicesState=byId("services-state"),servicesGrid=byId("services-grid"),servicesObserved=byId("services-observed");
  const alertsBadge=byId("alerts-badge"),alertsList=byId("alerts-list");
  const trendChart=byId("trend-chart"),trendDetail=byId("trend-detail"),capacityState=byId("capacity-state"),capacityDetail=byId("capacity-detail");
  const capacityBreakdown=byId("capacity-breakdown"),capacityFree=byId("capacity-free"),capacityAccounting=byId("capacity-accounting"),growthState=byId("growth-state"),growthDetail=byId("growth-detail");

  function setManagerSection(section) {
    const allowed=["summary","server","database","devices","maintenance","alerts","audit"];
    if(!allowed.includes(section)) section="summary";
    document.querySelectorAll(".manager-nav .nav-item").forEach((button)=>{
      const active=button.dataset.section===section;
      button.classList.toggle("active",active);
      button.setAttribute("aria-current",active?"page":"false");
    });
    document.querySelectorAll("[data-view]").forEach((element)=>{
      const views=(element.dataset.view||"").split(/\s+/);
      element.hidden=!views.includes(section);
    });
    const labels={summary:["RESUMEN OPERATIVO","Dashboard"],server:["INFRAESTRUCTURA","Servidor"],database:["DATOS","Base de datos"],devices:["FLOTA TRACCAR","Dispositivos"],maintenance:["OPERACIONES PROTEGIDAS","Mantenimiento"],alerts:["SUPERVISIÓN","Centro de alertas"],audit:["CONTROL Y EVIDENCIA","Auditoría"]};
    const heading=document.querySelector(".dashboard-heading .eyebrow"),title=byId("dashboard-title");
    if(heading) heading.textContent=labels[section][0];
    if(title) title.textContent=labels[section][1];
  }

  document.querySelectorAll(".manager-nav .nav-item").forEach((button)=>{
    button.addEventListener("click",()=>{setManagerSection(button.dataset.section);document.body.classList.remove("sidebar-open");if(button.dataset.section==="audit")loadAuditHistory();if(button.dataset.section==="server"){loadHealthHistory(24);loadIncidentHistory();loadPreventiveDiagnostics();loadOperationalHealthHistory();loadOperationalAvailability();}});
  });
  document.querySelectorAll("[data-go-section]").forEach(b=>b.addEventListener("click",()=>{if(b.dataset.goSection==="alerts")markAlertsSeen();setManagerSection(b.dataset.goSection);byId("notification-drawer").hidden=true;}));
  byId("sidebar-toggle").addEventListener("click",()=>{if(matchMedia("(max-width:720px)").matches)document.body.classList.toggle("sidebar-open");else document.body.classList.toggle("sidebar-collapsed");});
  document.querySelector(".profile-avatar").addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();byId("profile-avatar-file").click();}});
  async function loadAccountProfile(){try{const r=await fetch(api("account/profile"),{credentials:"same-origin"});if(!r.ok)return;const d=await r.json(),p=d.profile||{};byId("profile-name").value=p.name||"";byId("profile-email").value=p.email||"";byId("profile-display-name").textContent=p.name||"Perfil administrativo";byId("account-drawer-name").textContent=p.name||"Administrador";byId("account-drawer-email").textContent=p.email||"Cuenta administrativa";byId("account-drawer-initial").textContent=(p.name||"A").trim().charAt(0).toUpperCase()||"A";byId("profile-avatar-letter").textContent=(p.name||"A").trim().charAt(0).toUpperCase()||"A";const im=byId("profile-avatar-img");if(p.has_avatar){im.onload=()=>{im.hidden=false;byId("profile-avatar-letter").hidden=true};im.onerror=()=>{im.hidden=true;byId("profile-avatar-letter").hidden=false};im.src=api("account/avatar")+"?v="+Date.now();const di=byId("account-drawer-avatar-img");di.onload=()=>{di.hidden=false;byId("account-drawer-initial").hidden=true};di.onerror=()=>{di.hidden=true;byId("account-drawer-initial").hidden=false};di.src=im.src;}else{im.onload=null;im.onerror=null;im.hidden=true;byId("profile-avatar-letter").hidden=false;const di=byId("account-drawer-avatar-img");di.onload=null;di.onerror=null;di.hidden=true;byId("account-drawer-initial").hidden=false;}}catch(_){}}
  document.querySelectorAll("[data-account-tab]").forEach(b=>b.addEventListener("click",()=>{document.querySelectorAll("[data-account-tab]").forEach(x=>x.classList.toggle("active",x===b));document.querySelectorAll("[data-account-panel]").forEach(p=>p.hidden=p.dataset.accountPanel!==b.dataset.accountTab);}));
  byId("profile-save").addEventListener("click",async()=>{const st=byId("profile-status"),name=byId("profile-name").value.trim(),email=byId("profile-email").value.trim();if(!name||!email||!byId("profile-email").checkValidity()){st.textContent="Introduce un nombre y un correo electrónico válido.";return;}st.textContent="Guardando…";try{const r=await fetch(api("account/profile"),{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,email})});if(!r.ok){st.textContent=r.status>=500?"El servidor no pudo guardar el perfil. Inténtalo nuevamente.":"Revisa el nombre y correo.";return;}await loadAccountProfile();st.textContent="Perfil actualizado.";}catch(_){st.textContent="No se pudo conectar para guardar el perfil. Inténtalo nuevamente.";}});
  byId("profile-avatar-file").addEventListener("change",async e=>{const f=e.target.files&&e.target.files[0];if(!f)return;if(!["image/png","image/jpeg","image/webp"].includes(f.type)){byId("profile-status").textContent="Selecciona una imagen PNG, JPG o WebP.";return}if(f.size>2097152){byId("profile-status").textContent="La imagen debe pesar máximo 2 MiB.";return}const im=byId("profile-avatar-img"),preview=URL.createObjectURL(f);let previewReleased=false;const releasePreview=()=>{if(!previewReleased){previewReleased=true;URL.revokeObjectURL(preview)}};im.onload=()=>{im.hidden=false;byId("profile-avatar-letter").hidden=true;releasePreview()};im.onerror=()=>{releasePreview();im.hidden=true;byId("profile-avatar-letter").hidden=false;byId("profile-status").textContent="No se pudo mostrar la vista previa de la imagen."};im.src=preview;try{const b64=await new Promise((ok,no)=>{const r=new FileReader();r.onload=()=>ok(String(r.result).split(",")[1]);r.onerror=no;r.readAsDataURL(f)});const r=await fetch(api("account/avatar"),{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({data:b64})});if(!r.ok){releasePreview();byId("profile-status").textContent="Usa PNG, JPG o WebP de máximo 2 MiB.";await loadAccountProfile();return;}releasePreview();await loadAccountProfile();byId("profile-status").textContent="Foto actualizada.";}catch(_){releasePreview();byId("profile-status").textContent="No se pudo actualizar la foto. Comprueba la conexión e inténtalo nuevamente.";try{await loadAccountProfile();}catch(_){}}});
  byId("password-save").addEventListener("click",async()=>{const st=byId("password-status"),cur=byId("password-current").value,nw=byId("password-new").value,cf=byId("password-confirm").value;if(nw!==cf){st.textContent="Las contraseñas nuevas no coinciden.";return}if(nw.length<10){st.textContent="La nueva contraseña debe tener al menos 10 caracteres.";return}st.textContent="Actualizando…";try{const r=await fetch(api("account/password"),{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({current_password:cur,new_password:nw})});if(r.ok){alert("Contraseña actualizada. Inicia sesión nuevamente.");location.reload();}else{st.textContent=r.status===401?"La contraseña actual no es correcta.":"No se pudo cambiar la contraseña.";}}catch(_){st.textContent="No se pudo conectar para cambiar la contraseña. Inténtalo nuevamente.";}});
  loadAccountProfile();
  byId("sidebar-overlay").addEventListener("click",()=>document.body.classList.remove("sidebar-open"));
  byId("account-button").addEventListener("click",()=>{const d=byId("account-drawer");d.hidden=!d.hidden;byId("notification-drawer").hidden=true;if(!d.hidden)openAccountPanel("profile");});
  byId("account-drawer-close").addEventListener("click",()=>byId("account-drawer").hidden=true);
  function openAccountPanel(key){const host=byId("account-modal-content");const panel=document.querySelector("[data-account-panel=\""+key+"\"]");if(!panel)return;document.querySelectorAll("[data-account-open]").forEach(x=>x.classList.toggle("active",x.dataset.accountOpen===key));host.querySelectorAll("[data-account-panel]").forEach(x=>x.hidden=true);if(panel.parentElement!==host)host.appendChild(panel);panel.hidden=false;}document.querySelectorAll("[data-account-open]").forEach(b=>b.addEventListener("click",()=>openAccountPanel(b.dataset.accountOpen)));
  async function syncAlertIndicator(key){try{const r=await fetchApi("account/alert-state",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key:key||"",mark_seen:false})});if(!r.ok)return;const d=await r.json(),n=byId("notification-count");n.textContent=d.unread?"1":"0";n.hidden=!d.unread;}catch(_){}}async function markAlertsSeen(){if(window.__activeAlertKey===undefined)return;const n=byId("notification-count");n.hidden=true;n.textContent="0";try{await fetchApi("account/alert-state",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key:window.__activeAlertKey||"",mark_seen:true})});}catch(_){}}byId("notification-button").addEventListener("click",()=>{const d=byId("notification-drawer");d.hidden=!d.hidden;if(!d.hidden)markAlertsSeen();});
  byId("notification-close").addEventListener("click",()=>byId("notification-drawer").hidden=true);
  setManagerSection("summary");
  // Capacity projection belongs to the summary and uses the same authenticated history endpoint.
  // It is loaded after session validation together with server metrics.

  function showLogin(message) {
    boot.hidden = true;
    phaseBanner.hidden = true;
    loginPanel.hidden = false;
    sessionBar.hidden = true;
    accessPanel.hidden = true;
    dashboardPanel.hidden = true;
    document.body.classList.remove("authenticated","sidebar-open","sidebar-collapsed");
    passwordInput.value = "";
    loginError.textContent = message || "";
    loginError.hidden = !message;
  }

  function showAccessDenied() {
    boot.hidden = true;
    phaseBanner.hidden = false;
    loginPanel.hidden = true;
    sessionBar.hidden = false;
    accessPanel.hidden = false;
    dashboardPanel.hidden = true;
  }

  function showAuthenticatedLoading() {
    phaseBanner.hidden = false;
    loginPanel.hidden = true;
    sessionBar.hidden = false;
    accessPanel.hidden = true;
    dashboardPanel.hidden = true;
    boot.replaceChildren(document.createElement("span"));
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

  function renderCapacityForecast(pr){
    const badge=byId("forecast-priority"),current=byId("forecast-current"),warning=byId("forecast-warning"),critical=byId("forecast-critical"),wd=byId("forecast-warning-detail"),cd=byId("forecast-critical-detail"),guide=byId("forecast-guidance");
    badge.className="diagnostic-risk";
    if(!pr||pr.status==="COLLECTING"){badge.textContent="Recopilando";current.textContent="—";warning.textContent="—";critical.textContent="—";wd.textContent="Línea base insuficiente";cd.textContent="Línea base insuficiente";guide.textContent="Se requieren al menos 12 muestras y una hora de observación.";return;}
    current.textContent=(pr.current_percent||0).toFixed(1)+"%";
    if(pr.status==="STABLE"){badge.textContent="Estable";badge.classList.add("ok");warning.textContent="Sin horizonte";critical.textContent="Sin horizonte";wd.textContent="No hay crecimiento sostenido";cd.textContent="No hay crecimiento sostenido";guide.textContent="Mantener las políticas actuales y la observación periódica.";return;}
    const cr=pr.capacity_risk||{},priority=cr.priority||"LOW",d80=pr.days_to_80,d90=pr.days_to_90;warning.textContent=d80+" días";critical.textContent=d90+" días";wd.textContent="Si continúa "+pr.growth_percent_per_day+" pp/día";cd.textContent="Si continúa "+pr.growth_percent_per_day+" pp/día";
    if(priority==="CRITICAL"){badge.textContent="Prioridad crítica";badge.classList.add("bad");guide.textContent="Revisión operativa inmediata recomendada; cualquier mantenimiento continúa sujeto a las protecciones del Manager.";}else if(priority==="HIGH"){badge.textContent="Prioridad alta";badge.classList.add("warn");guide.textContent="Planificar revisión prioritaria de capacidad y del componente dominante.";}else if(priority==="MEDIUM"){badge.textContent="Prioridad media";badge.classList.add("warn");guide.textContent="Programar revisión preventiva antes de alcanzar el umbral de aviso.";}else{badge.textContent="Prioridad baja";badge.classList.add("ok");guide.textContent="Capacidad suficiente en el horizonte actual; continuar observación.";}
  }

  function renderOperationalDiagnostic(cg){
    const risk=byId("diagnostic-risk"),cause=byId("diagnostic-cause"),detail=byId("diagnostic-cause-detail"),rate=byId("diagnostic-rate"),share=byId("diagnostic-share"),action=byId("diagnostic-action-detail");
    const names={mysql:"MySQL",traccar_logs:"Logs Traccar",journal:"Journal systemd",binlogs:"Binlogs MySQL",manager_history:"Histórico Manager",other:"Otros / no atribuido"};
    risk.className="diagnostic-risk";
    if(!cg||cg.status==="COLLECTING"){risk.textContent="Recopilando";cause.textContent="Línea base insuficiente";detail.textContent=(cg&&cg.sample_count||0)+" de 12 muestras mínimas.";rate.textContent="—";share.textContent="Se requiere al menos una hora de observación.";action.textContent="Continuar recopilando métricas; no se requiere intervención.";return;}
    if(cg.status==="STABLE"||!cg.dominant_component){risk.textContent="Estable";risk.classList.add("ok");cause.textContent="Sin crecimiento neto";detail.textContent="La regresión no detecta presión sostenida sobre el disco.";rate.textContent=formatBytes(Math.abs(Math.round(cg.growth_bytes_per_day||0)))+"/día";share.textContent="Variación estimada del filesystem completo.";action.textContent="Mantener observación y políticas actuales.";return;}
    const d=cg.diagnostic||{},name=names[cg.dominant_component]||cg.dominant_component;cause.textContent=name;detail.textContent="Componente dominante en "+cg.window_hours+" h de observación.";rate.textContent=formatBytes(Math.max(0,Math.round(d.rate_bytes_per_day||0)))+"/día";share.textContent=(d.share_of_positive_growth_percent||0).toFixed(1)+"% del crecimiento positivo estimado.";
    if(cg.severity==="CRITICAL"){risk.textContent="Riesgo crítico";risk.classList.add("bad");}else if(cg.severity==="WARNING"){risk.textContent="Requiere atención";risk.classList.add("warn");}else{risk.textContent="En observación";}
    action.textContent=cg.recommendation||"Mantener observación antes de intervenir.";
  }

  async function loadHealthHistory(hours=24){
    try{
      const r=await fetchApi("health/history?hours="+hours);if(!r.ok)throw new Error();const d=await r.json(),samples=d.samples||[],svg=trendChart.querySelector("svg");svg.replaceChildren();
      const cg=d.component_growth||{status:"COLLECTING"};renderOperationalDiagnostic(cg);const names={mysql:"MySQL",traccar_logs:"logs Traccar",journal:"Journal",binlogs:"binlogs",manager_history:"histórico Manager",other:"otros"};if(cg.status==="COLLECTING"){growthState.textContent="Recopilando línea base";growthDetail.textContent=(cg.sample_count||0)+" de 12 muestras por componente · mínimo una hora.";}else if(cg.status==="STABLE"){growthState.textContent="Sin crecimiento neto";growthDetail.textContent="Ventana "+cg.window_hours+" h · variación total "+formatBytes(Math.abs(cg.disk_delta_bytes||0))+".";}else{const dom=names[cg.dominant_component]||"sin atribuir",delta=(cg.component_deltas||{})[cg.dominant_component]||0;growthState.textContent="Principal crecimiento: "+dom;const rate=(cg.component_rates_per_day||{})[cg.dominant_component]||0;growthDetail.textContent="Ritmo estimado "+formatBytes(Math.max(0,Math.round(rate)))+"/día · ventana "+cg.window_hours+" h · variación observada "+(cg.disk_delta_bytes>=0?"+":"−")+formatBytes(Math.abs(cg.disk_delta_bytes))+".";}
      const gr=byId("growth-recommendation");if(gr){gr.hidden=!cg.recommendation;gr.textContent=cg.recommendation||"";}const pr=d.projection||{status:"COLLECTING"};renderCapacityForecast(pr);capacityState.className="";if(pr.status==="COLLECTING"){capacityState.textContent="Recopilando datos";capacityDetail.textContent=(pr.sample_count||0)+" de 12 muestras mínimas · se requiere al menos una hora de observación.";}else if(pr.status==="STABLE"){capacityState.textContent="Capacidad estable";capacityDetail.textContent="Tendencia "+pr.growth_percent_per_day+" puntos porcentuales/día · sin proyección de saturación.";}else{const d80=pr.days_to_80,d90=pr.days_to_90;capacityState.textContent="Crecimiento "+pr.growth_percent_per_day+" pp/día";capacityDetail.textContent="80% en "+d80+" días · 90% en "+d90+" días, si la tendencia continúa.";if(d90<=7)capacityState.className="bad";else if(d80<=14)capacityState.className="warn";}
      if(samples.length<2){trendDetail.textContent=samples.length+" muestra disponible · el gráfico aparecerá al completar al menos dos ciclos de 5 minutos.";return;}
      const series=[["trend-disk",s=>s.disk_used_percent],["trend-memory",s=>s.memory_total_bytes?100*s.memory_used_bytes/s.memory_total_bytes:0],["trend-logs",s=>s.logs_bytes],["trend-db",s=>s.database_total_bytes]];
      series.forEach(([cls,get])=>{const vals=samples.map(get),min=Math.min(...vals),max=Math.max(...vals),span=Math.max(max-min,Math.max(Math.abs(max),1)*.02);const pts=vals.map((v,i)=>{const x=i*600/(vals.length-1),y=140-(v-min)*125/span;return x.toFixed(1)+","+Math.max(8,Math.min(140,y)).toFixed(1)}).join(" ");const line=document.createElementNS("http://www.w3.org/2000/svg","polyline");line.setAttribute("points",pts);line.setAttribute("class","trend-line "+cls);svg.appendChild(line);});
      const first=samples[0],last=samples[samples.length-1];trendDetail.textContent=samples.length+" muestras · "+first.observed_at_utc+" → "+last.observed_at_utc+" · histórico persistente y de solo lectura";
    }catch(_e){trendDetail.textContent="Histórico no disponible.";}
  }
  document.querySelectorAll(".trend-tab").forEach(b=>b.addEventListener("click",()=>{document.querySelectorAll(".trend-tab").forEach(x=>x.classList.toggle("active",x===b));loadHealthHistory(Number(b.dataset.hours));}));

  async function loadOperationalAvailability(){
    try{const r=await fetchApi("health/operational-availability");if(!r.ok)throw new Error();const d=await r.json();[["24h","24"],["7d","7d"]].forEach(([key,id])=>{const w=d.windows&&d.windows[key],value=byId("availability-"+id),detail=byId("availability-"+id+"-detail"),coverage=byId("availability-"+id+"-coverage"),bar=byId("availability-"+id+"-bar");if(!w||!value)return;value.textContent=w.stable_percent===null?"Sin datos":w.stable_percent.toFixed(2)+"% estable";detail.textContent=w.degraded_percent===null?"Esperando histórico":"Degradado "+w.degraded_percent.toFixed(2)+"% · "+w.covered_hours.toFixed(2)+" h medidas";coverage.textContent="Cobertura "+w.coverage_percent.toFixed(1)+"%"+(w.complete_window?" · ventana completa":" · histórico parcial");bar.style.width=Math.max(0,Math.min(100,w.stable_percent||0))+"%";value.closest(".availability-window").classList.toggle("incomplete",!w.complete_window);const budget=byId("budget-"+id),bs=byId("budget-"+id+"-state");if(budget){budget.textContent=w.error_budget_remaining_minutes.toFixed(2)+" min restantes";const labels={PROVISIONAL:"Provisional · "+w.error_budget_consumed_minutes.toFixed(2)+" min consumidos",WITHIN_BUDGET:"Dentro del presupuesto · "+w.error_budget_consumed_minutes.toFixed(2)+" min consumidos",EXHAUSTED:"Presupuesto agotado · "+w.error_budget_consumed_minutes.toFixed(2)+" min consumidos"};bs.textContent=labels[w.error_budget_status]||w.error_budget_status;bs.className=w.error_budget_status==="EXHAUSTED"?"budget-bad":(w.error_budget_status==="WITHIN_BUDGET"?"budget-ok":"budget-provisional");}const fs=byId("forecast-slo-"+id),fd=byId("forecast-slo-"+id+"-detail");if(fs){const labels={COLLECTING:"Recopilando línea base",STABLE:"Sin consumo degradado",ON_TRACK:"Proyección dentro del presupuesto",AT_RISK:"Riesgo de agotar presupuesto"};fs.textContent=labels[w.forecast_status]||w.forecast_status;fs.className=w.forecast_status==="AT_RISK"?"risk":(w.forecast_status==="STABLE"||w.forecast_status==="ON_TRACK"?"track":"collecting");if(w.forecast_status==="COLLECTING")fd.textContent="Base mínima "+w.forecast_minimum_baseline_hours.toFixed(1)+" h · actual "+w.covered_hours.toFixed(2)+" h";else if(w.forecast_status==="STABLE")fd.textContent="Ritmo de consumo 0× · sin degradación observada";else fd.textContent="Burn rate "+w.burn_rate.toFixed(2)+"× · proyectado "+w.projected_consumed_minutes.toFixed(2)+" min"+(w.hours_to_budget_exhaustion===null?"":" · agotamiento ~"+w.hours_to_budget_exhaustion.toFixed(1)+" h");}});}catch(_){}
  }

  async function loadOperationalHealthHistory(){
    const list=byId("health-history-timeline"),count=byId("health-history-count");if(!list||!count)return;
    try{const r=await fetchApi("health/operational-history");if(!r.ok)throw new Error();const d=await r.json(),events=Array.isArray(d.events)?d.events:[];count.textContent=events.length+" transición"+(events.length===1?"":"es");list.replaceChildren();
      if(!events.length){const p=document.createElement("p");p.className="muted";p.textContent="Aún no hay transiciones registradas.";list.appendChild(p);return;}
      const fmt=(v)=>{if(!v)return "Actual";const x=new Date(v);return Number.isNaN(x.getTime())?v:x.toLocaleString("es-PE",{dateStyle:"short",timeStyle:"short"});};const dur=(a,b)=>{const x=new Date(a).getTime(),y=b?new Date(b).getTime():Date.now();const m=Math.max(0,Math.floor((y-x)/60000)),dd=Math.floor(m/1440),hh=Math.floor((m%1440)/60);return dd?dd+" d "+hh+" h":hh?hh+" h "+m%60+" min":m+" min";};
      events.forEach(e=>{const row=document.createElement("div");row.className="health-history-row "+String(e.state||"").toLowerCase();const node=document.createElement("div");node.className="health-history-node";node.appendChild(document.createElement("i"));const st=document.createElement("div");st.className="health-history-state";const strong=document.createElement("strong");strong.textContent=String(e.label||e.state||"—").toUpperCase();const dates=document.createElement("span");dates.textContent=fmt(e.started_at_utc)+" → "+fmt(e.ended_at_utc);st.append(strong,dates);const cause=document.createElement("div");cause.className="health-history-cause";const cs=document.createElement("strong");cs.textContent=e.cause_label||"Sin incidencias";const cc=document.createElement("span");cc.textContent=e.ended_at_utc?"Estado finalizado":"Estado actual en observación";cause.append(cs,cc);const duration=document.createElement("span");duration.className="health-history-duration"+(e.ended_at_utc?"":" health-history-current");duration.textContent=(e.ended_at_utc?"Duración ":"Actual · ")+dur(e.started_at_utc,e.ended_at_utc);row.append(node,st,cause,duration);list.appendChild(row);});
    }catch(_){list.replaceChildren();const p=document.createElement("p");p.className="muted";p.textContent="Historial operacional no disponible.";list.appendChild(p);}
  }

  async function loadPreventiveDiagnostics(){
    const list=byId("diagnostic-list"),count=byId("diagnostic-count");if(!list||!count)return;
    try{const r=await fetchApi("health/diagnostics");if(!r.ok)throw new Error();const d=await r.json(),rows=d.diagnostics||[];count.textContent=rows.length+" activo"+(rows.length===1?"":"s");list.replaceChildren();if(!rows.length){const p=document.createElement("p");p.className="muted";p.textContent="Sin diagnósticos preventivos activos.";list.appendChild(p);return;}
      rows.forEach(x=>{const item=document.createElement("div");item.className="diagnostic-item";const top=document.createElement("div");top.className="diagnostic-top";const title=document.createElement("strong");title.textContent=x.component_label||"Diagnóstico preventivo";const mode=document.createElement("span");mode.className="diagnostic-mode";mode.textContent="SOLO RECOMENDACIÓN";top.append(title,mode);const fields=document.createElement("div");fields.className="diagnostic-fields";[["CAUSA PROBABLE",x.probable_cause,""],["EVIDENCIA",x.evidence,""],["IMPACTO",x.impact,""],["ACCIÓN RECOMENDADA",x.recommendation,"recommendation"]].forEach(([a,b,c])=>{const box=document.createElement("div");if(c)box.className=c;const sm=document.createElement("small");sm.textContent=a;const sp=document.createElement("span");sp.textContent=b;box.append(sm,sp);fields.appendChild(box);});const actions=document.createElement("div");actions.className="diagnostic-actions";const refresh=document.createElement("button");refresh.type="button";refresh.className="primary";refresh.textContent="Actualizar diagnóstico";refresh.addEventListener("click",()=>loadPreventiveDiagnostics());const evidence=document.createElement("button");evidence.type="button";evidence.textContent="Ver evidencia";const verify=document.createElement("button");verify.type="button";verify.textContent="Verificar protecciones";const panel=document.createElement("div");panel.className="diagnostic-evidence-panel";panel.textContent=x.evidence||"Sin evidencia adicional.";evidence.addEventListener("click",()=>{panel.classList.toggle("open");evidence.textContent=panel.classList.contains("open")?"Ocultar evidencia":"Ver evidencia";});const check=document.createElement("div");check.className="protection-check";verify.addEventListener("click",async()=>{verify.disabled=true;check.className="protection-check";check.textContent="Verificando snapshot protegido…";try{const sr=await fetchApi("server/status");if(!sr.ok)throw new Error();const sd=await sr.json(),p=sd.storage_protection;if(!p)throw new Error();const services=Object.values(p.services||{}),servicesOk=services.every(v=>v.active_state==="active"&&(v.sub_state==="running"||v.sub_state==="waiting"));const ok=p.journal&&p.journal.status==="PROTECTED"&&p.binlogs&&p.binlogs.status==="PROTECTED"&&p.database&&p.database.status==="HEALTHY"&&servicesOk;check.className="protection-check "+(ok?"ok":"bad");check.textContent=ok?"Protecciones verificadas · journal, binlogs, base de datos y servicios saludables":"Revisión requerida · una o más protecciones no están confirmadas";}catch(_){check.className="protection-check bad";check.textContent="No fue posible verificar el snapshot de protecciones.";}finally{verify.disabled=false;}});actions.append(refresh,evidence,verify);const runbook=document.createElement("div");runbook.className="diagnostic-runbook";const rbTitle=document.createElement("small");rbTitle.textContent="RUNBOOK ASISTIDO";const steps=document.createElement("div");steps.className="runbook-steps";(x.runbook||[]).forEach((r,i)=>{const row=document.createElement("div");row.className="runbook-step"+(r.mode==="ADMIN_AUTHORIZATION"?" auth":"");const dot=document.createElement("i");const name=document.createElement("strong");name.textContent=(i+1)+". "+r.step;const desc=document.createElement("span");desc.textContent=r.description;const modeTag=document.createElement("em");const statusLabels={VERIFIED:"VERIFICADO",OBSERVING:"EN OBSERVACIÓN",PENDING:"PENDIENTE",ATTENTION:"REQUIERE ATENCIÓN",AUTH_REQUIRED:"REQUIERE AUTORIZACIÓN"};modeTag.textContent=statusLabels[r.live_status]||(r.mode==="ADMIN_AUTHORIZATION"?"REQUIERE AUTORIZACIÓN":"PENDIENTE");row.classList.add("status-"+String(r.live_status||"pending").toLowerCase());if(r.live_detail)desc.textContent=r.description+" · "+r.live_detail;row.append(dot,name,desc,modeTag);steps.appendChild(row);});runbook.append(rbTitle,steps);item.append(top,fields,runbook,actions,panel,check);list.appendChild(item);});
    }catch(_){list.replaceChildren();const p=document.createElement("p");p.className="muted";p.textContent="Diagnóstico preventivo no disponible.";list.appendChild(p);}
  }

  function formatAuditDuration(seconds){const n=Number(seconds);if(!Number.isFinite(n)||n<0)return "Pendiente";if(n<60)return Math.round(n)+" s";if(n<3600)return Math.round(n/60)+" min";return (n/3600).toFixed(n<36000?1:0)+" h";}
  function closeCasefile(){const m=byId("casefile-modal");if(m){m.classList.remove("open");m.setAttribute("aria-hidden","true");}}
  async function openCasefile(id){
    const modal=byId("casefile-modal"),body=byId("casefile-body"),title=byId("casefile-title");if(!modal||!body)return;modal.classList.add("open");modal.setAttribute("aria-hidden","false");body.textContent="Cargando expediente…";
    try{const r=await fetchApi("health/incidents/"+encodeURIComponent(id)+"/casefile");if(!r.ok)throw new Error();const d=await r.json(),g=d.diagnostic||{};title.textContent=d.summary||"Incidente";body.replaceChildren();
      const timeline=document.createElement("div");timeline.className="casefile-block";const tl=document.createElement("small");tl.textContent="LÍNEA TEMPORAL";const rows=document.createElement("div");rows.className="casefile-timeline";(d.timeline||[]).forEach(e=>{const x=document.createElement("div");x.className="casefile-event";const dot=document.createElement("i"),lab=document.createElement("strong"),at=document.createElement("span");lab.textContent=e.label;at.textContent=new Date(e.at_utc).toLocaleString("es-PE");x.append(dot,lab,at);rows.appendChild(x);});timeline.append(tl,rows);
      const evidence=document.createElement("div");evidence.className="casefile-block";const es=document.createElement("small");es.textContent="EVIDENCIA Y DIAGNÓSTICO";const ep=document.createElement("p");ep.textContent=g.evidence||"";const cp=document.createElement("p");cp.textContent="Causa probable · "+(g.probable_cause||"");const rp=document.createElement("p");rp.textContent="Recomendación · "+(g.recommendation||"");evidence.append(es,ep,cp,rp);
      const checks=document.createElement("div");checks.className="casefile-block";const cs=document.createElement("small");cs.textContent="VERIFICACIONES DEL RUNBOOK";checks.appendChild(cs);(g.runbook||[]).forEach(x=>{const p=document.createElement("p");p.textContent=x.step+" · "+(x.live_status||x.status)+" · "+(x.live_detail||"");checks.appendChild(p);});const action=document.createElement("div");action.className="casefile-block";const as=document.createElement("small");as.textContent="INTERVENCIÓN ASISTIDA";const ab=document.createElement("button");ab.type="button";ab.className="primary";ab.textContent="Iniciar intervención vinculada";ab.addEventListener("click",()=>{interventionContext={incident_id:d.incident_id,summary:d.summary||"Incidente"};const box=byId("incident-intervention-context");byId("incident-intervention-title").textContent=interventionContext.summary;byId("incident-intervention-id").textContent=interventionContext.incident_id;box.hidden=false;closeCasefile();showView("maintenance");});const an=document.createElement("p");an.className="muted";an.textContent="Vincula el contexto del incidente. No concede autorización ni ejecuta cambios.";action.append(as,ab,an);const decisions=document.createElement("div");decisions.className="casefile-block";const ds=document.createElement("small");ds.textContent="DECISIONES ADMINISTRATIVAS";decisions.appendChild(ds);const ad=d.administrative_decisions||{},de=ad.events||[],ist=ad.intervention_state||{code:"NONE",label:"Sin intervención"};const state=document.createElement("div");state.className="casefile-intervention-state state-"+String(ist.code).toLowerCase();const sk=document.createElement("span");sk.textContent="ESTADO DE INTERVENCIÓN";const sv=document.createElement("strong");sv.textContent=ist.label;state.append(sk,sv);decisions.appendChild(state);const cycle=document.createElement("div");cycle.className="intervention-cycle";const durations=ad.intervention_durations||{};const durationKeys=["preparation_seconds","authorization_seconds","execution_seconds","audit_seconds"];(ad.intervention_cycle||[]).forEach((x,i)=>{const step=document.createElement("div");step.className="intervention-cycle-step "+String(x.status||"PENDING").toLowerCase();const dot=document.createElement("i");dot.textContent=x.status==="COMPLETED"?"✓":(x.status==="FAILED"?"!":String(i+1));const lab=document.createElement("span");lab.textContent=x.label;const tm=document.createElement("b");const sec=durations[durationKeys[i]];tm.textContent=sec==null?"Pendiente":formatAuditDuration(sec);step.append(dot,lab,tm);cycle.appendChild(step);});decisions.appendChild(cycle);if(de.length){const verified=document.createElement("div");verified.className="casefile-trace-ok";verified.textContent="TRAZABILIDAD AUDITADA · "+de.length+" EVENTO"+(de.length===1?"":"S")+" VINCULADO"+(de.length===1?"":"S");decisions.appendChild(verified);}if(!de.length){const p=document.createElement("p");p.className="muted";p.textContent="Sin decisiones administrativas vinculadas explícitamente a este incidente.";decisions.appendChild(p);}else{const historyTitle=document.createElement("small");historyTitle.textContent="HISTORIAL DE INTERVENCIONES";historyTitle.className="intervention-history-title";decisions.appendChild(historyTitle);const ih=document.createElement("div");ih.className="intervention-history";(ad.interventions||[]).forEach((it,n)=>{const card=document.createElement("div");card.className="intervention-history-card";const head=document.createElement("div");const name=document.createElement("strong");name.textContent="Intervención "+(ad.interventions.length-n);const status=document.createElement("span");status.textContent=(it.state&&it.state.label)||"Sin intervención";head.append(name,status);const sm=it.summary||{};const ec=sm.event_count??it.event_count;const meta=document.createElement("p");meta.textContent=(sm.operation||it.operation||"Operación")+" · "+ec+" evento"+(ec===1?"":"s");const reached=document.createElement("p");reached.textContent="Etapa alcanzada · "+(sm.stage_reached||"Sin iniciar");const total=document.createElement("p");total.className="muted";total.textContent="Duración total · "+formatAuditDuration(sm.total_seconds??(it.durations&&it.durations.total_seconds));card.append(head,meta,reached,total);ih.appendChild(card);});decisions.appendChild(ih);}body.append(timeline,evidence,checks,action,decisions);
    }catch(_){body.textContent="No fue posible cargar el expediente operacional.";}
  }
  byId("incident-intervention-clear")?.addEventListener("click",()=>{interventionContext=null;byId("incident-intervention-context").hidden=true;lastPreview=null;lastPreparation=null;});
  byId("admin-attention-all")?.addEventListener("click",()=>openAdministrativeAttention("all"));document.querySelectorAll("[data-admin-attention]").forEach(b=>b.addEventListener("click",()=>openAdministrativeAttention(b.dataset.adminAttention)));
  byId("intervention-detail-close")?.addEventListener("click",closeInterventionDetail);byId("intervention-detail-modal")?.addEventListener("click",e=>{if(e.target===e.currentTarget)closeInterventionDetail();});
  byId("intervention-search")?.addEventListener("input",()=>{window.__interventionStalledOnly=false;renderGlobalInterventions();});byId("intervention-result")?.addEventListener("change",()=>{window.__interventionStalledOnly=false;renderGlobalInterventions();});byId("intervention-period")?.addEventListener("change",()=>{window.__interventionStalledOnly=false;renderGlobalInterventions();});byId("intervention-clear")?.addEventListener("click",()=>{window.__interventionStalledOnly=false;byId("intervention-search").value="";byId("intervention-result").value="";byId("intervention-period").value="0";renderGlobalInterventions();});
  byId("casefile-close")?.addEventListener("click",closeCasefile);byId("casefile-modal")?.addEventListener("click",e=>{if(e.target===e.currentTarget)closeCasefile();});

  async function loadIncidentHistory(){
    const list=byId("incident-list"),count=byId("incident-count");if(!list||!count)return;
    try{const r=await fetchApi("health/incidents");if(!r.ok)throw new Error();const d=await r.json(),events=Array.isArray(d.events)?d.events:[];count.textContent=events.length+" incidente"+(events.length===1?"":"s");list.replaceChildren();
      if(!events.length){const p=document.createElement("p");p.className="muted";p.textContent="Sin incidentes preventivos registrados.";list.appendChild(p);return;}
      const fmtTime=(v)=>{if(!v)return "—";const dt=new Date(v);return Number.isNaN(dt.getTime())?v:dt.toLocaleString("es-PE",{dateStyle:"short",timeStyle:"short"});};
      const duration=(a,b)=>{const x=new Date(a).getTime(),y=new Date(b||Date.now()).getTime();if(!Number.isFinite(x)||!Number.isFinite(y)||y<x)return "—";const m=Math.floor((y-x)/60000),d=Math.floor(m/1440),h=Math.floor((m%1440)/60),mm=m%60;return d?d+" d "+h+" h":h?h+" h "+mm+" min":mm+" min";};
      events.forEach(e=>{const row=document.createElement("div");row.className="incident-row";const main=document.createElement("div");main.className="incident-main";const sum=document.createElement("span");sum.className="incident-summary";sum.textContent=e.summary||e.kind;const meta=document.createElement("span");meta.className="incident-meta";meta.textContent="Detectado "+fmtTime(e.opened_at_utc)+" · Última observación "+fmtTime(e.updated_at_utc);main.append(sum,meta);const det=document.createElement("span");det.className="incident-detail";det.textContent=e.detail||"";const life=document.createElement("div");life.className="incident-life";const ageMs=Date.now()-new Date(e.opened_at_utc).getTime(),observing=e.status!=="RESOLVED"&&ageMs>=5*60000;const st=document.createElement("span");const priority=e.operational_priority||"OBSERVE";st.className="incident-state "+(e.status==="RESOLVED"?"":((e.severity==="CRITICAL"||priority==="CRITICAL")?"bad":"watch"));const priorityLabel={OBSERVE:"Observación",MEDIUM:"Prioridad media",HIGH:"Prioridad alta",CRITICAL:"Prioridad crítica"}[priority]||"Observación";st.textContent=e.status==="RESOLVED"?"Resuelto":(observing?priorityLabel:"Detectado");const dur=document.createElement("span");dur.className="incident-duration";dur.textContent="Duración · "+duration(e.opened_at_utc,e.resolved_at_utc);const track=document.createElement("span");track.className="incident-track";track.setAttribute("aria-label","Detectado, En observación, Resuelto");for(let i=0;i<3;i++){const dot=document.createElement("i");const current=e.status==="RESOLVED"?2:(observing?1:0);dot.className=i<current?"done":(i===current?"current":"");track.appendChild(dot);if(i<2){const line=document.createElement("b");track.appendChild(line);}}life.append(st,dur,track);row.append(main,det,life);row.tabIndex=0;row.setAttribute("role","button");row.setAttribute("aria-label","Abrir expediente de "+(e.summary||e.kind));row.addEventListener("click",()=>openCasefile(e.id));row.addEventListener("keydown",ev=>{if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();openCasefile(e.id);}});list.appendChild(row);});
    }catch(_){list.replaceChildren();const p=document.createElement("p");p.className="muted";p.textContent="Historial de incidentes no disponible.";list.appendChild(p);}
  }



  function closeInterventionDetail(){const m=byId("intervention-detail-modal");if(m){m.classList.remove("open");m.setAttribute("aria-hidden","true");}}
  function openInterventionDetail(x){
    const modal=byId("intervention-detail-modal"),body=byId("intervention-detail-body"),title=byId("intervention-detail-title");if(!modal||!body||!x)return;
    title.textContent=x.incident_id||"Intervención";body.replaceChildren();
    const summary=document.createElement("div");summary.className="casefile-block intervention-detail-summary state-"+String(x.result_code||"NONE").toLowerCase();const sk=document.createElement("small");sk.textContent="RESUMEN";const sp=document.createElement("p");sp.textContent=(x.operation||"Operación")+" · "+(x.result||"Sin intervención")+" · "+(x.event_count||0)+" evento"+(x.event_count===1?"":"s");const sd=document.createElement("p");sd.className="muted";sd.textContent="Etapa alcanzada · "+(x.stage_reached||"Sin iniciar")+" · Duración total · "+formatAuditDuration(x.total_seconds);summary.append(sk,sp,sd);if(x.stall&&x.stall.stalled){const sw=document.createElement("p");sw.className="stall-warning";sw.textContent="⚠ Advertencia operativa · "+(x.stall.reason||"Intervención sin avance")+" durante "+formatAuditDuration((x.stall.age_hours||0)*3600);summary.appendChild(sw);}body.appendChild(summary);
    const cycle=document.createElement("div");cycle.className="casefile-block";const ck=document.createElement("small");ck.textContent="CICLO DE INTERVENCIÓN";cycle.appendChild(ck);const track=document.createElement("div");track.className="intervention-cycle";(x.cycle||[]).forEach((st,i)=>{const step=document.createElement("div");step.className="intervention-cycle-step "+String(st.status||"PENDING").toLowerCase();const dot=document.createElement("i");dot.textContent=st.status==="COMPLETED"?"✓":(st.status==="FAILED"?"!":String(i+1));const lab=document.createElement("span");lab.textContent=st.label||"Etapa";const keys=["preparation_seconds","authorization_seconds","execution_seconds","audit_seconds"];const tm=document.createElement("b");tm.textContent=formatAuditDuration((x.durations||{})[keys[i]]);step.append(dot,lab,tm);track.appendChild(step);});cycle.appendChild(track);body.appendChild(cycle);
    const events=document.createElement("div");events.className="casefile-block";const ek=document.createElement("small");ek.textContent="EVENTOS DE ESTE INTENTO";events.appendChild(ek);const tl=document.createElement("div");tl.className="casefile-timeline";(x.events||[]).forEach(e=>{const row=document.createElement("div");row.className="casefile-event";const dot=document.createElement("i");const type=document.createElement("strong");type.textContent=e.event_type||"Evento";const meta=document.createElement("span");const dt=e.timestamp?new Date(e.timestamp):null;meta.textContent=(dt&&!Number.isNaN(dt.getTime())?dt.toLocaleString("es-PE"):e.timestamp||"—")+(e.result_code?" · "+e.result_code:"");row.append(dot,type,meta);tl.appendChild(row);});if(!(x.events||[]).length){const empty=document.createElement("p");empty.className="muted";empty.textContent="Sin eventos auditados para este intento.";tl.appendChild(empty);}events.appendChild(tl);body.appendChild(events);
    modal.classList.add("open");modal.setAttribute("aria-hidden","false");
  }

  let globalInterventionItems=[];
  function renderGlobalInterventions(){
    const list=byId("global-interventions"),count=byId("global-intervention-count");if(!list||!count)return;
    const all=globalInterventionItems,total=all.length,executed=all.filter(x=>x.result_code==="EXECUTED").length,failed=all.filter(x=>x.result_code==="FAILED").length,progress=all.filter(x=>x.result_code==="AUTHORIZED"||x.result_code==="PREPARED").length,stalled=all.filter(x=>x.stall&&x.stall.stalled).length;byId("intervention-kpi-total").textContent=total;byId("intervention-kpi-executed").textContent=executed;byId("intervention-kpi-progress").textContent=progress;byId("intervention-kpi-failed").textContent=failed;byId("intervention-kpi-stalled").textContent=stalled;
    const q=String(byId("intervention-search")?.value||"").trim().toLowerCase(),result=String(byId("intervention-result")?.value||""),hours=Number(byId("intervention-period")?.value||0),cutoff=hours?Date.now()-hours*3600000:0;
    const items=globalInterventionItems.filter(x=>{const hay=(String(x.incident_id||"")+" "+String(x.operation||"")).toLowerCase();const t=Date.parse(x.last_event_at||"");return(!window.__interventionStalledOnly||(x.stall&&x.stall.stalled))&&(!q||hay.includes(q))&&(!result||x.result_code===result)&&(!cutoff||(Number.isFinite(t)&&t>=cutoff));});
    count.textContent=items.length+" de "+globalInterventionItems.length+" intervención"+(globalInterventionItems.length===1?"":"es");list.replaceChildren();
    if(!items.length){const p=document.createElement("p");p.className="muted";p.textContent=globalInterventionItems.length?"Sin coincidencias para los filtros seleccionados.":"Sin intervenciones vinculadas explícitamente a incidentes.";list.appendChild(p);return;}
    items.forEach(x=>{const row=document.createElement("div");row.className="global-intervention-row state-"+String(x.result_code||"NONE").toLowerCase();const inc=document.createElement("strong");inc.textContent=x.incident_id||"Incidente";const op=document.createElement("span");op.textContent=x.operation||"Operación";const state=document.createElement("b");state.textContent=x.result||"Sin intervención";const stage=document.createElement("span");stage.textContent="Etapa · "+(x.stage_reached||"Sin iniciar");const duration=document.createElement("span");duration.textContent="Duración · "+formatAuditDuration(x.total_seconds);const events=document.createElement("span");events.textContent=(x.event_count||0)+" evento"+(x.event_count===1?"":"s");row.append(inc,op,state,stage,duration,events);if(x.stall&&x.stall.stalled){row.classList.add("is-stalled");const warn=document.createElement("span");warn.className="stall-warning";warn.textContent="⚠ Estancada · "+(x.stall.reason||"Sin avance")+" · "+formatAuditDuration((x.stall.age_hours||0)*3600);row.appendChild(warn);}row.tabIndex=0;row.setAttribute("role","button");row.setAttribute("aria-label","Abrir detalle auditado de "+(x.incident_id||"intervención"));row.addEventListener("click",()=>openInterventionDetail(x));row.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();openInterventionDetail(x);}});list.appendChild(row);});
  }
  async function loadGlobalInterventions(){
    const list=byId("global-interventions"),count=byId("global-intervention-count");if(!list||!count)return;
    try{const r=await fetchApi("audit/interventions");if(!r.ok)throw new Error();const d=await r.json();globalInterventionItems=Array.isArray(d.interventions)?d.interventions:[];renderGlobalInterventions();
    }catch(_){globalInterventionItems=[];count.textContent="No disponible";list.textContent="No se pudo consultar el historial global de intervenciones.";}
  }

  async function loadAuditHistory(){
    try{
      const r=await fetchApi("audit/recent"); if(!r.ok) throw new Error();
      const d=await r.json(),events=Array.isArray(d&&d.events)?d.events.filter(e=>e&&typeof e==="object"&&!Array.isArray(e)):[];
      auditCount.textContent=events.length+" eventos";
      auditEvents.replaceChildren();
      if(!events.length){const p=document.createElement("p");p.className="muted";p.textContent="Sin actividad registrada desde el último inicio del Manager.";auditEvents.appendChild(p);return;}
      const labels={AUTH_LOGIN:"Inicio de sesión",AUTH_SESSION_CHECK:"Validación de sesión",AUTH_LOGOUT:"Cierre de sesión",AUTH_DASHBOARD_READ:"Lectura del dashboard"};
      events.slice(0,20).forEach((e)=>{
        const row=document.createElement("div");row.className="audit-event";
        const time=document.createElement("time");time.textContent=e.timestamp_utc||"—";
        const ev=document.createElement("span");ev.className="event";ev.textContent=labels[e.event]||e.event||"Evento sin tipo";
        const result=document.createElement("span");result.className="result "+(e.result==="SUCCEEDED"?"ok":(e.result==="DENIED"?"bad":"warn"));result.textContent=e.result||"No verificable";
        const reason=document.createElement("span");reason.className="reason";reason.textContent=e.reason_code||"—";
        row.append(time,ev,result,reason);auditEvents.appendChild(row);
      });
    }catch(_e){auditCount.textContent="No disponible";auditEvents.textContent="No se pudo consultar la actividad reciente.";}
  }

  function renderCapacityCenter(p,d){
    const c=p&&p.capacity;
    const total=c&&c.disk_total_bytes||d&&d.disk_total_bytes;
    if(!c||!Number.isFinite(total)||total<=0){capacityBreakdown.replaceChildren();capacityFree.textContent="No disponible";capacityAccounting.textContent="Capacidad no verificable · sin total de disco válido";return;}
    const used=c.disk_used_bytes||0,mysqlCore=Math.max(0,(c.mysql_files_bytes||0)-(c.binlogs_bytes||0)),known=[
      ["MySQL datos",mysqlCore],["Binlogs",c.binlogs_bytes],["Logs Traccar",c.traccar_logs_bytes],["Journal",c.journal_bytes],["Histórico Manager",c.manager_history_bytes]
    ]; const knownTotal=known.reduce((s,x)=>s+(Number.isSafeInteger(x[1])?x[1]:0),0),other=Math.max(0,used-knownTotal);
    known.push(["Otros",other]);capacityBreakdown.replaceChildren();
    known.forEach(([label,value])=>{const row=document.createElement("div");row.className="capacity-row";const name=document.createElement("span");name.textContent=label;const meter=document.createElement("div");meter.className="meter";const fill=document.createElement("span");fill.style.width=Math.min(100,value*100/total).toFixed(2)+"%";meter.appendChild(fill);const size=document.createElement("strong");size.textContent=formatBytes(value);const pct=document.createElement("em");pct.textContent=(value*100/total).toFixed(value*100/total<1?2:1)+"%";row.append(name,meter,size,pct);capacityBreakdown.appendChild(row);});
    capacityFree.textContent=formatBytes(Math.max(0,total-used))+" libres";capacityAccounting.textContent="Uso total "+formatBytes(used)+" de "+formatBytes(total)+" · componentes sobre filesystem completo";
  }

  function renderOperationalHealth(h){const box=byId("operational-health-summary"),state=byId("operational-health-state"),cause=byId("operational-health-cause"),factors=byId("operational-health-factors");if(!box||!h)return;box.className="operational-health-summary state-"+String(h.state||"").toLowerCase();state.textContent=String(h.label||"Verificando").toUpperCase();cause.textContent=(h.cause&&h.cause.label?h.cause.label:"Estado consolidado")+(h.cause&&h.cause.detail?" · "+h.cause.detail:"");factors.replaceChildren();(h.factors||[]).slice(0,3).forEach(f=>{const x=document.createElement("span");x.textContent=f.label;factors.appendChild(x);});}




  async function loadAdministrativeAttentionHistory(){
    const list=byId("admin-attention-history-list"),count=byId("admin-history-count");if(!list||!count)return;
    try{const [r,mr,ihr]=await Promise.all([fetchApi("health/administrative-attention-history"),fetchApi("health/administrative-attention-metrics"),fetchApi("health/administrative-index-history")]);if(!r.ok||!mr.ok||!ihr.ok)throw new Error();const d=await r.json(),md=await mr.json(),ihd=await ihr.json(),events=Array.isArray(d.events)?d.events:[];const ihlist=byId("admin-index-history-list"),ihcount=byId("admin-index-history-count"),ihevents=Array.isArray(ihd.events)?ihd.events:[];ihcount.textContent=ihevents.length+" cambio"+(ihevents.length===1?"":"s");ihlist.replaceChildren();ihevents.slice(0,5).forEach(e=>{const row=document.createElement("div");row.className="admin-index-history-row";const score=document.createElement("strong");score.textContent=String(e.score)+" · "+String(e.label||"—");const cause=document.createElement("span");cause.textContent=e.cause||"—";const time=document.createElement("small");let dur="—";if(e.started_at_utc){const a=Date.parse(e.started_at_utc),b=e.ended_at_utc?Date.parse(e.ended_at_utc):Date.now();dur=Number.isFinite(a)&&Number.isFinite(b)&&b>=a?formatAuditDuration((b-a)/1000):"—";}time.textContent=(e.ended_at_utc?"Duración ":"En curso · ")+dur;row.append(score,cause,time);ihlist.appendChild(row);});if(!ihevents.length){const x=document.createElement("span");x.className="muted";x.textContent="Sin cambios significativos registrados todavía.";ihlist.appendChild(x);}const idx=md.index||{score:100,label:"Óptimo",factors:[]},idxBox=byId("admin-attention-index");idxBox.className="admin-attention-index "+(idx.score>=90?"optimal":(idx.score>=75?"stable":(idx.score>=50?"attention":"critical")));byId("admin-index-score").textContent=String(idx.score);byId("admin-index-label").textContent=idx.label||"—";const factorBox=byId("admin-index-factors");factorBox.replaceChildren();const penalized=(idx.factors||[]).filter(f=>Number(f.penalty)>0);if(!penalized.length){const x=document.createElement("span");x.textContent="Sin penalizaciones activas"+((idx.factors||[]).some(f=>f.code==="trend"&&f.penalty===0)?" · tendencia sin penalización":"") +".";factorBox.appendChild(x);}else penalized.forEach(f=>{const x=document.createElement("span");x.textContent=f.label+" · −"+f.penalty+" pts";factorBox.appendChild(x);});const trend=md.trend||{},trendBox=byId("admin-attention-trend");trendBox.className="admin-attention-trend "+String(trend.status||"COLLECTING").toLowerCase();byId("admin-attention-trend-label").textContent=trend.label||"Recopilando línea base";byId("admin-attention-trend-detail").textContent=trend.status==="COLLECTING"?(String(trend.observed_hours||0)+" h observadas · mínimo "+String(trend.minimum_baseline_hours||6)+" h"):(String(trend.observed_hours||0)+" h observadas · comparación de las últimas dos ventanas de 3 h");["24h","7d"].forEach((key,i)=>{const x=md.windows&&md.windows[key]?md.windows[key]:null,id=i?"7d":"24";if(!x)return;const sh=x.state_hours||{};byId("admin-metric-"+id).textContent=(x.complete_window?"Ventana completa":"Cobertura parcial")+" · "+x.covered_hours+" h";byId("admin-metric-"+id+"-detail").textContent="Normal "+(sh.NORMAL||0)+" h · Observación "+(sh.OBSERVATION||0)+" h · Atención "+(sh.ATTENTION||0)+" h · "+x.coverage_percent+"% observado";});count.textContent=events.length+" transición"+(events.length===1?"":"es");list.replaceChildren();events.slice(0,5).forEach(e=>{const row=document.createElement("div");row.className="admin-history-row "+String(e.state||"normal").toLowerCase();const st=document.createElement("strong");st.textContent=e.label||e.state;const cause=document.createElement("span");cause.textContent=e.cause||"—";const time=document.createElement("small");let duration="—";if(e.started_at_utc){const a=Date.parse(e.started_at_utc),b=e.ended_at_utc?Date.parse(e.ended_at_utc):Date.now();duration=Number.isFinite(a)&&Number.isFinite(b)&&b>=a?formatAuditDuration((b-a)/1000):"—";}time.textContent=(e.started_at_utc?new Date(e.started_at_utc).toLocaleString("es-PE"):"—")+" · "+(e.ended_at_utc?duration:"En curso · "+duration);row.append(st,cause,time);list.appendChild(row);});if(!events.length){const x=document.createElement("span");x.className="muted";x.textContent="Sin transiciones registradas todavía.";list.appendChild(x);}}
    catch(_){count.textContent="No disponible";list.textContent="No se pudo consultar el historial administrativo.";}
  }

  function renderAdministrativeAttention(items){
    const all=Array.isArray(items)?items:[],progress=all.filter(x=>x.result_code==="AUTHORIZED"||x.result_code==="PREPARED").length,stalled=all.filter(x=>x.stall&&x.stall.stalled).length,failed=all.filter(x=>x.result_code==="FAILED").length;
    byId("admin-attention-progress").textContent=progress;byId("admin-attention-stalled").textContent=stalled;byId("admin-attention-failed").textContent=failed;
    const state=stalled>0||failed>0?"attention":(progress>0?"observation":"normal"),label=state==="attention"?"Atención":(state==="observation"?"Observación":"Normal");let cause="Sin intervenciones administrativas que requieran seguimiento.";if(state==="attention")cause=[stalled?stalled+" estancada"+(stalled===1?"":"s"):"",failed?failed+" fallida"+(failed===1?"":"s"):""].filter(Boolean).join(" · ");else if(state==="observation")cause=progress+" intervención"+(progress===1?"":"es")+" en curso, dentro del seguimiento normal.";const stateBox=byId("admin-attention-state");stateBox.className="admin-attention-state "+state;byId("admin-attention-state-label").textContent=label;byId("admin-attention-state-cause").textContent=cause;
    const box=byId("administrative-attention");if(box)box.classList.toggle("has-attention",state==="attention");
  }
  async function openAdministrativeAttention(kind){
    setManagerSection("audit");await loadGlobalInterventions();const search=byId("intervention-search"),result=byId("intervention-result"),period=byId("intervention-period");if(search)search.value="";if(period)period.value="0";if(result)result.value=kind==="failed"?"FAILED":"";window.__interventionStalledOnly=kind==="stalled";renderGlobalInterventions();
  }

  async function openAlertIntervention(x){
    if(!x||!x.incident_id||!x.intervention_key)return;
    byId("notification-drawer").hidden=true;setManagerSection("audit");
    await loadGlobalInterventions();
    const exact=globalInterventionItems.find(i=>i.incident_id===x.incident_id&&i.intervention_key===x.intervention_key);
    if(!exact)return;
    const search=byId("intervention-search"),result=byId("intervention-result"),period=byId("intervention-period");if(search)search.value=exact.incident_id;if(result)result.value="";if(period)period.value="0";renderGlobalInterventions();openInterventionDetail(exact);
  }

  function renderAlerts(d,administrativeInterventions=[]){
    const alerts=[],p=d.storage_protection,memoryPct=d.memory_total_bytes>0?d.memory_used_bytes*100/d.memory_total_bytes:0;
    const add=(level,title,detail)=>alerts.push({level,title,detail});
    if(d.disk_used_percent>=90)add("bad","Disco crítico",d.disk_used_percent.toFixed(1)+"% utilizado · liberar espacio de forma controlada");
    else if(d.disk_used_percent>=80)add("warn","Disco en atención",d.disk_used_percent.toFixed(1)+"% utilizado · vigilar crecimiento");
    if(memoryPct>=95)add("bad","Memoria crítica",memoryPct.toFixed(1)+"% utilizada");
    else if(memoryPct>=85)add("warn","Memoria elevada",memoryPct.toFixed(1)+"% utilizada");
    const cg=d.component_growth,names={mysql:"MySQL",traccar_logs:"logs Traccar",journal:"Journal",binlogs:"binlogs",manager_history:"histórico Manager",other:"otros"},incidents=Array.isArray(d.preventive_incidents)?d.preventive_incidents:[];
    const growthIncident=incidents.find(e=>e.kind==="component_growth");
    if(growthIncident){const op=growthIncident.operational_priority||"OBSERVE",level=(growthIncident.severity==="CRITICAL"||op==="CRITICAL")?"bad":"warn",opLabel={MEDIUM:"Prioridad media · ",HIGH:"Prioridad alta · ",CRITICAL:"Prioridad crítica · "}[op]||"";add(level,opLabel+"Incidente preventivo · "+(names[growthIncident.component]||growthIncident.component),growthIncident.detail||"Condición preventiva activa");alerts[alerts.length-1].incident_id=growthIncident.id;alerts[alerts.length-1].severity=growthIncident.severity;alerts[alerts.length-1].operational_priority=op;}
    else if(cg&&(cg.severity==="WARNING"||cg.severity==="CRITICAL")){const level=cg.severity==="CRITICAL"?"bad":"warn",cause=names[cg.dominant_component]||"almacenamiento",delta=(cg.component_deltas||{})[cg.dominant_component]||0;add(level,"Crecimiento anormal · "+cause,"+"+formatBytes(delta)+" en "+cg.window_hours+" h · ritmo "+cg.growth_percent_per_day.toFixed(2)+"% del disco/día");}
    incidents.filter(e=>e.kind!=="component_growth").forEach(e=>{const op=e.operational_priority||"OBSERVE",level=(e.severity==="CRITICAL"||op==="CRITICAL")?"bad":"warn",opLabel={MEDIUM:"Prioridad media · ",HIGH:"Prioridad alta · ",CRITICAL:"Prioridad crítica · "}[op]||"";add(level,opLabel+(e.summary||"Incidente preventivo"),e.detail||"Condición preventiva activa");alerts[alerts.length-1].incident_id=e.id;alerts[alerts.length-1].severity=e.severity;alerts[alerts.length-1].operational_priority=op;});
    if(!p)add("bad","Auditoría no disponible","No existe un snapshot reciente de protecciones");
    else{
      if(!p.journal||p.journal.status!=="PROTECTED")add("bad","Journal sin protección verificada","Evidencia ausente o configuración desviada · revisar límite y retención");
      else if(Number.isFinite(p.journal.used_bytes)&&Number.isFinite(p.journal.max_use_bytes)&&p.journal.max_use_bytes>0&&p.journal.used_bytes>p.journal.max_use_bytes*1.25)add("warn","Journal sobre referencia",formatBytes(p.journal.used_bytes)+" usados frente a límite configurado "+formatBytes(p.journal.max_use_bytes));
      if(!p.binlogs||p.binlogs.status!=="PROTECTED")add("bad","Binlogs sin protección verificada","Evidencia ausente o configuración desviada · revisar retención o replicación");
      if(!p.database||p.database.status!=="HEALTHY")add("bad","Base de datos no verificable","Metadatos MySQL no disponibles");
      const fd=p.database&&p.database.devices,fa=fd&&fd.activity;if(fd&&fa&&fd.enabled>0&&fa.stale_24h>0){const stalePct=100*fa.stale_24h/fd.enabled;add(stalePct>=25?"bad":"warn","Flota con dispositivos sin reporte",fa.stale_24h+" de "+fd.enabled+" habilitados llevan más de 24 h sin reportar · "+stalePct.toFixed(1)+"% de la flota habilitada");}
      if(p.services&&typeof p.services==="object"){Object.entries(p.services).forEach(([name,s])=>{const state=s&&s.active_state||"sin evidencia",substate=s&&s.sub_state||"sin evidencia",ok=state==="active"&&(substate==="running"||substate==="waiting");if(!ok)add("bad","Servicio requiere atención",name+" · "+state+" / "+substate);});}
    }
    (administrativeInterventions||[]).filter(x=>x&&x.stall&&x.stall.stalled).forEach(x=>{add("warn","Intervención administrativa estancada",String(x.incident_id||"Incidente")+" · "+String(x.stall.reason||"Sin avance")+" · "+formatAuditDuration((x.stall.age_hours||0)*3600));const a=alerts[alerts.length-1];a.alert_key=["stalled-intervention",x.incident_id||"",x.intervention_key||""].join(":");a.operational_priority="OBSERVE";a.intervention=x;});
    const opRank={CRITICAL:4,HIGH:3,MEDIUM:2,OBSERVE:1};alerts.sort((a,b)=>((b.level==="bad"?10:0)+(opRank[b.operational_priority]||0))-((a.level==="bad"?10:0)+(opRank[a.operational_priority]||0)));
    alertsList.replaceChildren();
    if(!alerts.length)add("ok","Sin incidencias activas","Disco, memoria, servicios, base de datos y protecciones dentro de parámetros");
    const center=byId("alerts-center-list"),drawer=byId("notification-list");center.replaceChildren();drawer.replaceChildren();
    const makeRow=(a)=>{const row=document.createElement("div");row.className="alert-item "+a.level;const title=document.createElement("strong");title.textContent=(a.level==="bad"?"Crítico · ":(a.level==="warn"?"Atención · ":""))+a.title;const detail=document.createElement("span");detail.textContent=a.detail;row.append(title,detail);if(a.intervention){const go=document.createElement("button");go.type="button";go.className="alert-intervention-link";go.textContent="Ver intervención";go.addEventListener("click",()=>openAlertIntervention(a.intervention));row.appendChild(go);}return row;};
    alerts.forEach((a)=>{alertsList.appendChild(makeRow(a));center.appendChild(makeRow(a));if(a.level!=="ok")drawer.appendChild(makeRow(a));});
    const critical=alerts.filter(a=>a.level==="bad").length,warnings=alerts.filter(a=>a.level==="warn").length,count=critical+warnings;if(!count){const p=document.createElement("p");p.className="muted";p.textContent="Sin alertas activas.";drawer.appendChild(p);}const nc=byId("notification-count");const alertKey=alerts.filter(a=>a.level==="bad"||a.level==="warn").map(a=>a.alert_key|| (a.incident_id?["incident",a.incident_id,a.severity||a.level,a.operational_priority||"OBSERVE"].join(":"):[a.level,a.title||a.name||"",a.detail||a.message||""].join(":"))).sort().join("|");window.__activeAlertKey=alertKey;nc.textContent="0";nc.hidden=true;if(count)syncAlertIndicator(alertKey);byId("kpi-alerts").textContent=count?String(count)+" activa"+(count===1?"":"s"):"Sin alertas";
    alertsBadge.className="alerts-badge "+(critical?"bad":(warnings?"warn":"ok"));alertsBadge.textContent=critical?critical+" crítico"+(critical===1?"":"s"):(warnings?warnings+" aviso"+(warnings===1?"":"s"):"Todo operativo");const cb=byId("alerts-center-badge");cb.className=alertsBadge.className;cb.textContent=alertsBadge.textContent;
  }

  let deviceInventory=[];
  function formatDeviceAge(seconds){if(seconds===null)return "Sin reporte registrado";if(seconds<60)return "Hace menos de 1 min";if(seconds<3600)return "Hace "+Math.floor(seconds/60)+" min";if(seconds<86400)return "Hace "+Math.floor(seconds/3600)+" h";return "Hace "+Math.floor(seconds/86400)+" días";}
  const VEHICLE_ICON_VERSION="3d-phase2-20261007-2246";
  const VEHICLE_ICON_NAMES=new Set(["automobile","taxi","suv","van","minibus","bus","truck","dumptruck","trailer","tractor","construction","forklift","motorcycle","scooter","scooter-kick","mototaxi","bicycle","atv","boat","sailboat","jetski","helicopter","airplane","train","tram","camper","farm-tractor","agricultural","person","default"]);
  function vehicleAsset(category){const aliases={car:"automobile",semi:"trailer",crane:"construction",quad:"atv"};let key=String(category||"default").toLowerCase();key=aliases[key]||key;if(!VEHICLE_ICON_NAMES.has(key))key="default";return "/manager/assets/vehicle-icons-webp/"+key+".webp?v="+VEHICLE_ICON_VERSION;}
  let deviceDetailReturnFocus=null,deviceDetailReturnSection=null;
  function openDeviceDetail(x){if(lastInventorySuccessAt===null||Date.now()-lastInventorySuccessAt>=FLEET_STALE_AFTER_MS){updateFleetFreshness();return;}const modal=byId("device-detail-modal"),body=byId("device-detail-body"),labels={ONLINE:"Online",RECENT:"Reciente",INACTIVE:"Inactivo",STALE:"Sin reporte +24 h",DISABLED:"Deshabilitado"};const title=byId("device-detail-title");title.replaceChildren();const titleIcon=document.createElement("img");titleIcon.className="vehicle-type-image detail-vehicle-icon";titleIcon.setAttribute("aria-hidden","true");titleIcon.alt="";titleIcon.src=vehicleAsset(x.category);titleIcon.onerror=()=>{titleIcon.onerror=null;titleIcon.src=vehicleAsset("default")};const titleText=document.createElement("span");titleText.textContent=x.name;title.append(titleIcon,titleText);body.replaceChildren();const wrap=document.createElement("div");wrap.className="device-diagnostic";const hero=document.createElement("div");hero.className="diag-hero";const state=document.createElement("strong");state.textContent=labels[x.state]||x.state;const diagnosis=document.createElement("span");const messages={ONLINE:"Operación normal. Reporte reciente dentro de la ventana esperada.",RECENT:"Conectividad reciente. Mantener observación si la frecuencia habitual es menor a 15 minutos.",INACTIVE:"Atención preventiva. El equipo lleva más de una hora sin reportar.",STALE:"Atención prioritaria. El equipo habilitado lleva más de 24 horas sin reportar.",DISABLED:"Dispositivo fuera de operación por configuración administrativa."};diagnosis.textContent=messages[x.state]||"Estado disponible.";hero.append(state,diagnosis);const grid=document.createElement("div");grid.className="diag-grid";[["IDENTIFICADOR","Protegido por privacidad"],["CONTACTO","Protegido por privacidad"],["CADUCIDAD",x.expiration||"Sin caducidad"],["DESHABILITADO",x.enabled?"OFF":"ON"],["EMPRESA",x.company||"Sin empresa asignada"],["ESTADO",labels[x.state]||x.state],["ÚLTIMO REPORTE",x.enabled?formatDeviceAge(x.last_report_age_seconds):"No aplica"],["PRIVACIDAD","Sin ubicación ni coordenadas"]].forEach(([a,b])=>{const box=document.createElement("div"),sm=document.createElement("small"),st=document.createElement("strong");sm.textContent=a;st.textContent=b;box.append(sm,st);grid.appendChild(box);});const tl=document.createElement("div");tl.className="device-timeline";const t=document.createElement("strong");t.textContent="Línea temporal operacional";tl.appendChild(t);const labels2={ONLINE:"Online",RECENT:"Reciente",INACTIVE:"Inactivo",STALE:"Sin reporte +24 h",DISABLED:"Deshabilitado"},h=x.history;if(h&&Array.isArray(h.recent)&&h.recent.length){const meta=document.createElement("span");meta.textContent=h.observations+" observaciones · "+h.transitions+" transiciones registradas";tl.appendChild(meta);h.recent.slice().reverse().forEach(e=>{const sp=document.createElement("span");sp.textContent=(labels2[e.state]||e.state)+" · "+e.at.replace("T"," ").replace("Z"," UTC");tl.appendChild(sp);});}else{const sp=document.createElement("span");sp.textContent="Historial incremental iniciándose; se registrarán cambios en cada snapshot.";tl.appendChild(sp);}const guidance=document.createElement("section");guidance.className="diag-guidance";guidance.setAttribute("aria-label","Orientación de revisión segura");const guidanceHead=document.createElement("div");guidanceHead.className="diag-guidance-head";const guidanceTitle=document.createElement("strong");guidanceTitle.textContent="Guía de revisión";const severity=document.createElement("span");severity.className="diag-severity "+(x.state==="STALE"?"critical":x.state==="INACTIVE"?"warning":x.state==="RECENT"?"observe":"normal");severity.textContent=x.state==="STALE"?"Prioridad alta":x.state==="INACTIVE"?"Atención preventiva":x.state==="RECENT"?"Observación":"Informativo";guidanceHead.append(guidanceTitle,severity);const steps={STALE:["Confirma la antigüedad del último reporte y revisa el historial operacional disponible.","Comprueba por los canales autorizados si el equipo dispone de energía y conectividad.","Si persiste la falta de reporte, escala el caso al responsable técnico sin alterar la configuración desde esta ficha."],INACTIVE:["Revisa cuándo se recibió el último reporte y si el retraso coincide con el comportamiento habitual.","Comprueba de forma autorizada alimentación y conectividad antes de escalar el caso.","Si el retraso continúa, solicita una revisión técnica y registra el seguimiento fuera de esta vista."],RECENT:["Compara la antigüedad del reporte con la frecuencia esperada para este dispositivo.","Mantén observación si el intervalo de comunicación es irregular."],ONLINE:["Confirma que la recepción de reportes se mantiene estable.","No se requieren acciones correctivas basadas únicamente en este estado."],DISABLED:["Verifica con el administrador responsable si la deshabilitación es intencional.","No habilites ni cambies configuraciones sin autorización y un procedimiento aprobado."]};const listSteps=document.createElement("ol");(steps[x.state]||["Consulta los datos operacionales disponibles antes de tomar decisiones."]).forEach(message=>{const li=document.createElement("li");li.textContent=message;listSteps.appendChild(li);});const disclaimer=document.createElement("p");disclaimer.textContent="Orientación informativa basada en el estado reportado; no confirma la causa raíz ni ejecuta acciones sobre el dispositivo.";guidance.append(guidanceHead,listSteps,disclaimer);wrap.append(hero,guidance,grid,tl);body.appendChild(wrap);if(!deviceDetailReturnFocus)deviceDetailReturnFocus=document.activeElement;modal.classList.add("open");modal.setAttribute("aria-hidden","false");byId("device-detail-close").focus();}
  function closeDeviceDetail(){const m=byId("device-detail-modal");m.classList.remove("open");m.setAttribute("aria-hidden","true");if(deviceDetailReturnSection){setManagerSection(deviceDetailReturnSection);deviceDetailReturnSection=null;}if(deviceDetailReturnFocus&&deviceDetailReturnFocus.isConnected)deviceDetailReturnFocus.focus();deviceDetailReturnFocus=null;}
  byId("device-detail-modal").addEventListener("keydown",e=>{if(e.key==="Escape"){e.preventDefault();closeDeviceDetail();}else if(e.key==="Tab"){const close=byId("device-detail-close");e.preventDefault();close.focus();}});
  byId("device-detail-close").addEventListener("click",closeDeviceDetail);byId("device-detail-modal").addEventListener("click",e=>{if(e.target===byId("device-detail-modal"))closeDeviceDetail();});
  let fleetPriorityVisibleLimit=5;
  let fleetPrioritySearch="";
  byId("fleet-priority-search-input").addEventListener("input",e=>{fleetPrioritySearch=e.target.value.trim().toLocaleLowerCase("es");fleetPriorityVisibleLimit=5;renderFleetPriorities(lastInventorySuccessAt!==null);});
  let fleetPriorityFilter="all";
  document.querySelectorAll("[data-priority-filter]").forEach(button=>button.addEventListener("click",()=>{fleetPriorityFilter=button.dataset.priorityFilter;fleetPriorityVisibleLimit=5;document.querySelectorAll("[data-priority-filter]").forEach(b=>{const active=b===button;b.classList.toggle("active",active);b.setAttribute("aria-pressed",String(active));});renderFleetPriorities(lastInventorySuccessAt!==null);}));
  function syncFleetPriorityClear(){byId("fleet-priority-clear").disabled=fleetPriorityFilter==="all"&&!fleetPrioritySearch;}
  byId("fleet-priority-clear").addEventListener("click",()=>{fleetPrioritySearch="";byId("fleet-priority-search-input").value="";fleetPriorityFilter="all";fleetPriorityVisibleLimit=5;document.querySelectorAll("[data-priority-filter]").forEach(b=>{const active=b.dataset.priorityFilter==="all";b.classList.toggle("active",active);b.setAttribute("aria-pressed",String(active));});renderFleetPriorities(lastInventorySuccessAt!==null);byId("fleet-priority-search-input").focus();});
  let fleetPriorityInventoryAvailable=false;
  function filteredFleetPriorityDevices(){return deviceInventory.filter(x=>(x.state==="STALE"||x.state==="INACTIVE")&&(fleetPriorityFilter==="all"||(fleetPriorityFilter==="critical"?x.state==="STALE":x.state==="INACTIVE"))&&String(x.name||"").toLocaleLowerCase("es").includes(fleetPrioritySearch)).sort((a,b)=>(a.state==="STALE"?0:1)-(b.state==="STALE"?0:1)||String(a.name||"").localeCompare(String(b.name||"")));}
  function csvPriorityCell(value){let text=String(value??"");if(/^[\s]*[=+@-]/.test(text))text="'"+text;return '"'+text.replace(/"/g,'""')+'"';}
  byId("fleet-priority-export").addEventListener("click",()=>{if(!fleetPriorityInventoryAvailable||lastInventorySuccessAt===null||Date.now()-lastInventorySuccessAt>=FLEET_STALE_AFTER_MS)return;const rows=filteredFleetPriorityDevices();if(!rows.length)return;const inventoryUpdatedAt=lastInventorySuccessAt===null?"Sin consulta confirmada":new Intl.DateTimeFormat("es-PE",{dateStyle:"short",timeStyle:"short",timeZone:"America/Lima"}).format(new Date(lastInventorySuccessAt))+" (Lima)";const inventoryFreshness=lastInventorySuccessAt===null?"Sin consulta confirmada":Date.now()-lastInventorySuccessAt>=FLEET_STALE_AFTER_MS?"Datos desactualizados (+15 min)":"Datos recientes";const lines=[["Dispositivo","Prioridad","Estado","Último reporte","Inventario consultado","Vigencia del inventario"],...rows.map(x=>[x.name||"Dispositivo sin nombre",x.state==="STALE"?"Crítica":"Preventiva",x.state==="STALE"?"Sin reporte +24 h":"Inactivo",x.enabled?formatDeviceAge(x.last_report_age_seconds):"No aplica",inventoryUpdatedAt,inventoryFreshness])];const csv="\uFEFF"+lines.map(row=>row.map(csvPriorityCell).join(",")).join("\r\n")+"\r\n";const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));const link=document.createElement("a");link.href=url;link.download="prioridades-flota.csv";document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  function renderFleetPriorities(available){fleetPriorityInventoryAvailable=available;syncFleetPriorityClear();const list=byId("fleet-priority-list"),counter=byId("fleet-priority-count"),visibleCount=byId("fleet-priority-visible-count");list.replaceChildren();const critical=byId("fleet-priority-critical"),preventive=byId("fleet-priority-preventive");if(!available){byId("fleet-priority-export").disabled=true;visibleCount.textContent="No hay resultados confirmados para mostrar.";critical.textContent="Críticas: —";preventive.textContent="Preventivas: —";counter.textContent="No disponible";const p=document.createElement("p");p.textContent="No se pueden determinar las prioridades hasta recuperar el inventario.";list.appendChild(p);return;}const candidates=deviceInventory.filter(x=>x.state==="STALE"||x.state==="INACTIVE").sort((a,b)=>{const rank={STALE:0,INACTIVE:1};return rank[a.state]-rank[b.state]||String(a.name||"").localeCompare(String(b.name||""));});critical.textContent="Críticas: "+candidates.filter(x=>x.state==="STALE").length;preventive.textContent="Preventivas: "+candidates.filter(x=>x.state==="INACTIVE").length;const filtered=candidates.filter(x=>(fleetPriorityFilter==="all"||(fleetPriorityFilter==="critical"?x.state==="STALE":x.state==="INACTIVE"))&&String(x.name||"").toLocaleLowerCase("es").includes(fleetPrioritySearch));byId("fleet-priority-export").disabled=!filtered.length||lastInventorySuccessAt===null||Date.now()-lastInventorySuccessAt>=FLEET_STALE_AFTER_MS;counter.textContent=filtered.length+" por revisar";visibleCount.textContent="Mostrando "+Math.min(filtered.length,fleetPriorityVisibleLimit)+" de "+candidates.length+" dispositivos pendientes"+(filtered.length!==candidates.length?" · "+filtered.length+" coinciden con los filtros":"")+".";if(!candidates.length){const p=document.createElement("p");p.textContent="Sin dispositivos inactivos ni con reporte atrasado en el inventario disponible.";list.appendChild(p);return;}if(!filtered.length){const p=document.createElement("p");p.textContent=fleetPrioritySearch?"No hay dispositivos que coincidan con la búsqueda en este filtro.":fleetPriorityFilter==="critical"?"No hay prioridades críticas en el inventario disponible.":"No hay prioridades preventivas en el inventario disponible.";list.appendChild(p);return;}filtered.slice(0,fleetPriorityVisibleLimit).forEach(x=>{const row=document.createElement("div");row.className="fleet-priority-row";const text=document.createElement("div");const name=document.createElement("strong");name.textContent=x.name||"Dispositivo sin nombre";const detail=document.createElement("span");detail.textContent=x.state==="STALE"?"Sin reporte por más de 24 horas":"Dispositivo inactivo";text.append(name,detail);const tag=document.createElement("span");tag.className="fleet-priority-tag "+(x.state==="STALE"?"critical":"warning");tag.textContent=x.state==="STALE"?"Revisar reporte":"Revisar estado";const action=document.createElement("button");action.type="button";action.className="fleet-priority-open";action.disabled=lastInventorySuccessAt===null||Date.now()-lastInventorySuccessAt>=FLEET_STALE_AFTER_MS;action.textContent="Ver diagnóstico";action.setAttribute("aria-label","Ver diagnóstico administrativo de "+(x.name||"dispositivo"));action.addEventListener("click",()=>{if(!fleetPriorityInventoryAvailable||lastInventorySuccessAt===null||Date.now()-lastInventorySuccessAt>=FLEET_STALE_AFTER_MS){updateFleetFreshness();return;}deviceDetailReturnSection="summary";deviceDetailReturnFocus=action;setManagerSection("devices");const matching=[...byId("device-inventory-list").querySelectorAll(".device-row")].find(el=>el.querySelector("strong")?.textContent===x.name);if(matching)matching.focus();openDeviceDetail(x);});row.append(text,tag,action);list.appendChild(row);});if(filtered.length>fleetPriorityVisibleLimit){const more=document.createElement("button");more.type="button";more.className="fleet-priority-more";more.textContent="Ver más prioridades ("+(filtered.length-fleetPriorityVisibleLimit)+" restantes)";more.addEventListener("click",()=>{fleetPriorityVisibleLimit+=5;renderFleetPriorities(true);});list.appendChild(more);}if(fleetPriorityVisibleLimit>5&&filtered.length>5){const less=document.createElement("button");less.type="button";less.className="fleet-priority-less";less.textContent="Mostrar menos";less.addEventListener("click",()=>{fleetPriorityVisibleLimit=5;renderFleetPriorities(true);byId("fleet-priority-search-input").focus();});list.appendChild(less);}}
  function updateFleetSummary(available){renderFleetPriorities(available);const ids=["fleet-summary-total","fleet-online","fleet-attention","fleet-other"];if(!available){ids.forEach(id=>byId(id).textContent="—");byId("fleet-summary-note").textContent="Inventario temporalmente no disponible. Consulta la sección Dispositivos para reintentar.";return;}const total=deviceInventory.length,online=deviceInventory.filter(x=>x.state==="ONLINE").length,attention=deviceInventory.filter(x=>x.state==="INACTIVE"||x.state==="STALE").length;byId("fleet-summary-total").textContent=String(total);byId("fleet-online").textContent=String(online);byId("fleet-attention").textContent=String(attention);byId("fleet-other").textContent=String(total-online-attention);byId("fleet-summary-note").textContent=attention?"Hay dispositivos que requieren revisión administrativa.":"No hay dispositivos inactivos ni sin reporte prolongado en el inventario disponible.";}
  function renderDeviceInventory(){if(lastInventorySuccessAt===null)return;const list=byId("device-inventory-list"),filter=byId("inventory-filter").value,labels={ONLINE:"Online",RECENT:"Reciente",INACTIVE:"Inactivo",STALE:"Sin reporte +24 h",DISABLED:"Deshabilitado"},levels={ONLINE:"ok",RECENT:"",INACTIVE:"warn",STALE:"bad",DISABLED:""};const query=byId("inventory-search").value.trim().toLocaleLowerCase();let rows=deviceInventory;if(filter==="ATTENTION")rows=rows.filter(x=>x.state==="INACTIVE"||x.state==="STALE");else if(filter!=="ALL")rows=rows.filter(x=>x.state===filter);if(query)rows=rows.filter(x=>[x.name,x.company].some(v=>String(v||"").toLocaleLowerCase().includes(query)));list.replaceChildren();byId("inventory-count").textContent=rows.length+" de "+deviceInventory.length;if(!rows.length){const empty=document.createElement("div");empty.className="inventory-empty";empty.setAttribute("role","status");const symbol=document.createElement("span");symbol.className="inventory-empty-icon";symbol.setAttribute("aria-hidden","true");symbol.textContent=query?"⌕":"✓";const title=document.createElement("strong");title.textContent=query?"Sin coincidencias":filter==="ATTENTION"?"Sin dispositivos que requieran atención":"Sin dispositivos en esta categoría";const detail=document.createElement("p");detail.textContent=query?"Prueba otro nombre o empresa, o cambia el filtro de estado.":filter==="ATTENTION"?"No hay dispositivos inactivos ni sin reporte prolongado en el inventario disponible.":"Selecciona otro estado para consultar el inventario.";empty.append(symbol,title,detail);list.appendChild(empty);return;}rows.forEach(x=>{const row=document.createElement("div");row.className="device-row";const name=document.createElement("strong");const vehicleIcon=document.createElement("img");vehicleIcon.className="vehicle-type-image";vehicleIcon.setAttribute("aria-hidden","true");vehicleIcon.alt="";vehicleIcon.src=vehicleAsset(x.category);vehicleIcon.onerror=()=>{vehicleIcon.onerror=null;vehicleIcon.src=vehicleAsset("default")};name.append(vehicleIcon,document.createTextNode(x.name));const state=document.createElement("b");state.className="device-state "+(levels[x.state]||"");state.textContent=labels[x.state]||x.state;const age=document.createElement("span");age.textContent=x.enabled?formatDeviceAge(x.last_report_age_seconds):"Fuera de operación";const privacy=document.createElement("span");privacy.textContent="Sin ubicación ni identificadores";row.append(name,state,age,privacy);row.tabIndex=0;row.setAttribute("role","button");row.setAttribute("aria-label","Abrir ficha administrativa de "+x.name);row.setAttribute("aria-disabled",Date.now()-lastInventorySuccessAt>=FLEET_STALE_AFTER_MS?"true":"false");row.addEventListener("click",()=>openDeviceDetail(x));row.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();openDeviceDetail(x);}});list.appendChild(row);});}
  let inventoryRefreshPending=false,lastInventorySuccessAt=null;
  const FLEET_STALE_AFTER_MS=15*60*1000;
  function updateFleetFreshness(){const context=byId("fleet-priority-context"),badge=byId("fleet-freshness");const warning=byId("fleet-priority-export-warning");warning.hidden=lastInventorySuccessAt===null||Date.now()-lastInventorySuccessAt<FLEET_STALE_AFTER_MS;byId("fleet-priority-export").disabled=!fleetPriorityInventoryAvailable||!filteredFleetPriorityDevices().length||lastInventorySuccessAt===null||Date.now()-lastInventorySuccessAt>=FLEET_STALE_AFTER_MS;if(lastInventorySuccessAt===null){badge.className="fleet-freshness unknown";badge.textContent="Sin datos confirmados";context.className="fleet-priority-context unavailable";context.textContent="No hay inventario confirmado. No interpretes estas prioridades como el estado actual de la flota.";return;}const age=Math.max(0,Date.now()-lastInventorySuccessAt);document.querySelectorAll(".fleet-priority-open").forEach(button=>{button.disabled=age>=FLEET_STALE_AFTER_MS;});document.querySelectorAll(".device-row").forEach(row=>{row.setAttribute("aria-disabled",age>=FLEET_STALE_AFTER_MS?"true":"false");});if(age>=FLEET_STALE_AFTER_MS){badge.className="fleet-freshness stale";badge.textContent="Datos desactualizados · actualizar";context.className="fleet-priority-context stale";context.textContent="Atención: estas prioridades provienen de una consulta de hace 15 minutos o más. Actualiza el inventario antes de tomar decisiones.";}else{badge.className="fleet-freshness fresh";badge.textContent="Datos recientes";context.className="fleet-priority-context fresh";context.textContent="Prioridades según la última consulta del inventario. No representan seguimiento GPS en tiempo real.";}}
  setInterval(updateFleetFreshness,60000);
  async function loadDeviceInventory(){if(inventoryRefreshPending)return;inventoryRefreshPending=true;const refresh=byId("fleet-refresh");refresh.disabled=true;refresh.textContent="Actualizando…";const priorityRefresh=byId("fleet-priority-refresh");priorityRefresh.disabled=true;priorityRefresh.textContent="Actualizando…";const inventoryRefresh=byId("inventory-refresh");inventoryRefresh.disabled=true;inventoryRefresh.textContent="Actualizando…";byId("fleet-last-updated").textContent="Consultando inventario…";try{const r=await fetchApi("devices/inventory");if(!r.ok)throw new Error();const d=await r.json();if(!d.privacy||d.privacy.unique_id_exposed||d.privacy.phone_exposed||d.privacy.position_exposed||d.privacy.coordinates_exposed||!Array.isArray(d.devices))throw new Error();deviceInventory=d.devices;lastInventorySuccessAt=Date.now();updateFleetFreshness();updateFleetSummary(true);renderDeviceInventory();byId("fleet-last-updated").textContent="Actualizado: "+new Intl.DateTimeFormat("es-PE",{dateStyle:"short",timeStyle:"short"}).format(new Date(lastInventorySuccessAt));}catch(_){lastInventorySuccessAt=null;deviceInventory=[];updateFleetFreshness();updateFleetSummary(false);byId("fleet-last-updated").textContent="Error al actualizar · datos no disponibles";byId("inventory-count").textContent="No disponible";const list=byId("device-inventory-list");list.replaceChildren();const empty=document.createElement("div");empty.className="inventory-empty inventory-unavailable";empty.setAttribute("role","status");const title=document.createElement("strong");title.textContent="No se pudo cargar el inventario";const detail=document.createElement("p");detail.textContent="Los indicadores agregados siguen disponibles. Pulsa Reintentar carga o Actualizar inventario para volver a consultar.";const retry=document.createElement("button");retry.type="button";retry.className="inventory-retry";retry.textContent="Reintentar carga";retry.addEventListener("click",()=>loadDeviceInventory());empty.append(title,detail,retry);list.appendChild(empty);}finally{inventoryRefreshPending=false;refresh.disabled=false;refresh.textContent="↻ Actualizar";priorityRefresh.disabled=false;priorityRefresh.textContent="↻ Actualizar prioridades";inventoryRefresh.disabled=false;inventoryRefresh.textContent="↻ Actualizar inventario";}}
  byId("fleet-refresh").addEventListener("click",()=>loadDeviceInventory());
  byId("fleet-priority-refresh").addEventListener("click",()=>loadDeviceInventory());
  byId("inventory-refresh").addEventListener("click",()=>loadDeviceInventory());
  byId("inventory-filter").addEventListener("change",renderDeviceInventory);byId("inventory-search").addEventListener("input",renderDeviceInventory);

  function clearFleetSnapshot(){
    [devicesTotal,devicesEnabled,devicesDisabled,fleetTotal,fleetEnabled,fleetDisabled,fleetStale,fleetStateOnline,fleetStateRecent,fleetStateDay,fleetStateStale].forEach(el=>{el.textContent="—";});
    fleetLive.textContent="— en últimos 15 min";fleetRecent.textContent="— entre 15–60 min";fleetDay.textContent="— entre 1–24 h";
    fleetEnabledBase.textContent="— habilitados";fleetLivePercent.textContent="—";fleetActive24.textContent="—";
    fleetLiveMeter.firstElementChild.style.width="0%";fleetActiveMeter.firstElementChild.style.width="0%";
    fleetHealth.textContent="No verificable";fleetHealthDetail.textContent="Sin lectura confirmada de actividad";fleetHealth.className="bad";fleetHealthCard.className="capacity-card fleet-warning";
    devicesObserved.textContent="Datos no verificables";
  }
  async function loadServerStatus(){
    try {
      const [r,air]=await Promise.all([fetchApi("server/status"),fetchApi("audit/interventions")]); if(!r.ok) throw new Error(); const d=await r.json();let administrativeInterventions=[];if(air.ok){const aidata=await air.json();administrativeInterventions=Array.isArray(aidata.interventions)?aidata.interventions:[];}
      if(!d||d.read_only!==true) throw new Error();
      renderOperationalHealth(d.operational_health);
      if(!["NORMAL","WARNING","CRITICAL"].includes(d.disk_level)||!["HEALTHY","WARNING","CRITICAL"].includes(d.storage_health)) throw new Error();
      byId("kpi-disk").textContent=d.disk_used_percent.toFixed(1)+"%";byId("kpi-disk-detail").textContent=formatBytes(d.disk_free_bytes)+" libres";const mp=d.memory_total_bytes>0?Math.min(100,d.memory_used_bytes*100/d.memory_total_bytes):0;byId("overview-disk").textContent=d.disk_used_percent.toFixed(1)+"%";byId("overview-memory").textContent=mp.toFixed(1)+"%";byId("overview-disk-ring").style.setProperty("--progress",Math.min(100,d.disk_used_percent));byId("overview-memory-ring").style.setProperty("--progress",mp);byId("overview-resource-detail").textContent=formatBytes(d.disk_free_bytes)+" libres · "+formatBytes(d.memory_used_bytes)+" de memoria en uso";
      serverState.textContent=d.storage_health==="CRITICAL"?"Almacenamiento crítico · disco "+d.disk_used_percent.toFixed(1)+"%":(d.storage_health==="WARNING"?"Almacenamiento requiere atención · disco "+d.disk_used_percent.toFixed(1)+"%":"Almacenamiento saludable · disco "+d.disk_used_percent.toFixed(1)+"%");
      healthServer.textContent=d.storage_health==="HEALTHY"?"Saludable · "+d.disk_used_percent.toFixed(1)+"% disco":(d.storage_health==="WARNING"?"Atención · "+d.disk_used_percent.toFixed(1)+"% disco":"Crítico · "+d.disk_used_percent.toFixed(1)+"% disco"); healthServer.className=d.storage_health==="HEALTHY"?"ok":(d.storage_health==="WARNING"?"warn":"bad");
      const memoryUsedPercent=d.memory_total_bytes>0?Math.min(100,d.memory_used_bytes*100/d.memory_total_bytes):0;
      serverDisk.textContent=d.disk_used_percent.toFixed(1)+"%"; serverFree.textContent=formatBytes(d.disk_free_bytes)+" libres";
      diskMeter.firstElementChild.style.width=Math.min(100,d.disk_used_percent)+"%";
      diskMeter.className="meter "+(d.disk_level==="CRITICAL"?"critical":(d.disk_level==="WARNING"?"warning":""));
      memoryPercent.textContent=memoryUsedPercent.toFixed(1)+"%"; memoryMeter.firstElementChild.style.width=memoryUsedPercent+"%";
      serverMemory.textContent=formatBytes(d.memory_used_bytes)+" / "+formatBytes(d.memory_total_bytes); serverLogs.textContent=formatBytes(d.logs_bytes); serverHistoryCount.textContent=String(d.historical_log_count);
      serverDetail.textContent=d.historical_log_count+" históricos · solo lectura · sin shell · sin MySQL desde la web";
      const hr=await fetchApi("health/history?hours=24");if(hr.ok){const hd=await hr.json();d.component_growth=hd.component_growth||null;}
      const ir=await fetchApi("health/incidents");if(ir.ok){const idata=await ir.json();d.preventive_incidents=(idata.events||[]).filter(e=>e.status==="OPEN");}
      renderAlerts(d,administrativeInterventions);renderAdministrativeAttention(administrativeInterventions);loadAdministrativeAttentionHistory();
      const p=d.storage_protection;
      renderCapacityCenter(p,d);
      if(p&&p.services&&typeof p.services==="object"){
        const labels={traccar:"Traccar",manager:"Manager Web",worker:"Worker",retention:"Retention",storage_audit:"Auditor almacenamiento"}; servicesGrid.replaceChildren(); let allOk=true;
        Object.entries(labels).forEach(([key,label])=>{const s=p.services[key];const ok=!!s&&s.active_state==="active"&&(s.sub_state==="running"||s.sub_state==="waiting");allOk=allOk&&ok;const row=document.createElement("div");row.className="service-row";const n=document.createElement("span");n.className="service-name";n.textContent=label;const st=document.createElement("span");st.className="service-status"+(ok?"":" bad");st.textContent=s?(s.active_state||"sin evidencia")+" / "+(s.sub_state||"sin evidencia"):"Sin evidencia";const enabled=document.createElement("span");enabled.className="service-meta";enabled.textContent=s&&s.unit_file_state||"—";const since=document.createElement("span");since.className="service-meta";since.textContent=s&&s.active_since||"—";row.append(n,st,enabled,since);servicesGrid.appendChild(row);});
        servicesState.textContent=allOk?"Todos los componentes operativos":"⚠ Uno o más componentes requieren atención";servicesState.style.color=allOk?"var(--ui-green)":"var(--ui-amber)";servicesObserved.textContent="Última comprobación: "+(p.observed_at_utc||"—")+" · solo lectura";const ol=byId("overview-services-list");ol.replaceChildren();Object.entries(labels).slice(0,4).forEach(([key,label])=>{const s=p.services[key];const ok=!!s&&s.active_state==="active"&&(s.sub_state==="running"||s.sub_state==="waiting");const row=document.createElement("div");row.className="overview-service";const n=document.createElement("span");n.textContent=label;const st=document.createElement("b");st.textContent=ok?"● Operativo":"● Atención";if(!ok)st.style.color="var(--ui-red)";row.append(n,st);ol.appendChild(row);});
      } else {servicesGrid.replaceChildren();byId("overview-services-list").replaceChildren();servicesState.textContent="⚠ Servicios sin evidencia verificable";servicesState.style.color="var(--ui-amber)";servicesObserved.textContent="Última comprobación: sin evidencia confirmada";}
      if(p&&p.journal&&p.binlogs){
        const ok=p.journal.status==="PROTECTED"&&p.binlogs.status==="PROTECTED";
        storageProtectionState.textContent=ok?"Protecciones verificadas":"⚠ Configuración desviada"; healthProtections.textContent=ok?"Journal + binlogs protegidos":"Revisar políticas"; healthProtections.className=ok?"ok":"warn";
        journalProtection.textContent=(p.journal.status==="PROTECTED"?"":"Atención · ")+"Journal systemd · límite "+formatBytes(p.journal.max_use_bytes)+" · "+p.journal.retention_days+" días · uso "+formatBytes(p.journal.used_bytes);
        binlogProtection.textContent=(p.binlogs.status==="PROTECTED"?"":"Atención · ")+"Binlogs MySQL · "+p.binlogs.retention_days+" días · "+p.binlogs.count+" archivos · "+formatBytes(p.binlogs.used_bytes);
        const journalPct=p.journal.max_use_bytes>0?Math.min(100,p.journal.used_bytes*100/p.journal.max_use_bytes):0;
        journalMeter.firstElementChild.style.width=journalPct+"%"; journalMeter.className="meter "+(journalPct>=100?"warning":""); journalMeterValue.textContent=journalPct.toFixed(0)+"%";
        const binlogReference=7*1073741824,binlogPct=Math.min(100,p.binlogs.used_bytes*100/binlogReference);
        binlogMeter.firstElementChild.style.width=binlogPct+"%"; binlogMeterValue.textContent=formatBytes(p.binlogs.used_bytes);
        storageProtectionTime.textContent="Última verificación UTC · "+p.observed_at_utc;
        const db=p.database,pos=db&&db.positions;
        if(!db||db.status!=="HEALTHY"||!pos||db.total_bytes<=0) throw new Error();
        const indexPct=Math.min(100,db.index_bytes*100/db.total_bytes),positionPct=Math.min(100,pos.total_bytes*100/db.total_bytes);
        databaseState.textContent="MySQL saludable · metadatos verificados"; healthDatabase.textContent="Saludable · "+db.table_count+" tablas"; healthDatabase.className="ok"; databaseTotal.textContent=formatBytes(db.total_bytes);byId("kpi-database").textContent=formatBytes(db.total_bytes); databaseData.textContent=formatBytes(db.data_bytes)+" datos"; databaseIndex.textContent=formatBytes(db.index_bytes)+" índices"; databaseIndexMeter.firstElementChild.style.width=indexPct+"%"; databaseTables.textContent=String(db.table_count);
        positionsTotal.textContent=formatBytes(pos.total_bytes); positionsMeter.firstElementChild.style.width=positionPct+"%"; positionsRows.textContent=Number(pos.estimated_rows).toLocaleString("es-PE")+" filas estimadas"; positionsShare.textContent=positionPct.toFixed(1)+"% del esquema";
        const dev=db.devices,a=dev&&dev.activity; if(dev&&a&&Number.isInteger(dev.total)&&Number.isInteger(dev.enabled)&&Number.isInteger(dev.disabled)&&[a.live_15m,a.recent_1h,a.day_24h,a.stale_24h].every(Number.isInteger)&&dev.total>=0&&dev.enabled>=0&&dev.disabled>=0&&dev.enabled+dev.disabled===dev.total&&a.live_15m+a.recent_1h+a.day_24h+a.stale_24h===dev.enabled){const n=x=>Number(x).toLocaleString("es-PE"),livePct=dev.enabled?100*a.live_15m/dev.enabled:0,active24=a.live_15m+a.recent_1h+a.day_24h,activePct=dev.enabled?100*active24/dev.enabled:0;devicesTotal.textContent=n(dev.total);devicesEnabled.textContent=n(dev.enabled);devicesDisabled.textContent=n(dev.disabled);fleetTotal.textContent=n(dev.total);fleetEnabled.textContent=n(dev.enabled);fleetDisabled.textContent=n(dev.disabled);fleetStale.textContent=n(a.stale_24h);fleetLive.textContent=n(a.live_15m)+" en últimos 15 min";fleetRecent.textContent=n(a.recent_1h)+" entre 15–60 min";fleetDay.textContent=n(a.day_24h)+" entre 1–24 h";fleetEnabledBase.textContent=n(dev.enabled)+" habilitados";fleetLivePercent.textContent=livePct.toFixed(1)+"%";fleetActive24.textContent=n(active24)+" / "+n(dev.enabled);fleetLiveMeter.firstElementChild.style.width=Math.min(100,livePct)+"%";fleetActiveMeter.firstElementChild.style.width=Math.min(100,activePct)+"%";fleetStateOnline.textContent=n(a.live_15m);fleetStateRecent.textContent=n(a.recent_1h);fleetStateDay.textContent=n(a.day_24h);fleetStateStale.textContent=n(a.stale_24h);const stalePct=dev.enabled?100*a.stale_24h/dev.enabled:0,healthScore=Math.max(0,100-stalePct);fleetHealth.textContent=healthScore.toFixed(1)+"% saludable";fleetHealthDetail.textContent=a.stale_24h? n(a.stale_24h)+" habilitado"+(a.stale_24h===1?"":"s")+" sin reporte por más de 24 h · requiere seguimiento":"Todos los dispositivos habilitados reportaron dentro de 24 h";fleetHealth.className=a.stale_24h===0?"":(stalePct>=25?"bad":"warn");fleetHealthCard.className="capacity-card"+(stalePct>=25?" fleet-critical":(a.stale_24h?" fleet-warning":""));devicesObserved.textContent="Snapshot UTC · "+p.observed_at_utc;}else{clearFleetSnapshot();}
      } else { storageProtectionState.textContent="✕ Protecciones no verificables"; journalProtection.textContent="Journal: sin evidencia reciente"; binlogProtection.textContent="Binlogs MySQL: sin evidencia reciente"; healthProtections.textContent="No verificables"; healthProtections.className="bad"; journalMeter.firstElementChild.style.width="0%";binlogMeter.firstElementChild.style.width="0%";journalMeterValue.textContent="—";binlogMeterValue.textContent="—";storageProtectionTime.textContent="Última verificación: sin evidencia confirmada"; }
    } catch(_e) { serverState.textContent="Métricas no disponibles"; serverDetail.textContent="Sin privilegios adicionales concedidos."; storageProtectionState.textContent="✕ Protecciones no verificables"; healthServer.textContent="No disponible"; healthServer.className="bad"; healthDatabase.textContent="No disponible"; healthDatabase.className="bad"; healthProtections.textContent="No verificables"; healthProtections.className="bad";
      servicesGrid.replaceChildren();byId("overview-services-list").replaceChildren();servicesState.textContent="⚠ Servicios sin lectura confirmada";servicesState.style.color="var(--ui-amber)";servicesObserved.textContent="Última comprobación: sin evidencia confirmada";
      journalProtection.textContent="Journal: sin evidencia reciente";binlogProtection.textContent="Binlogs MySQL: sin evidencia reciente";journalMeter.firstElementChild.style.width="0%";binlogMeter.firstElementChild.style.width="0%";journalMeterValue.textContent="—";binlogMeterValue.textContent="—";storageProtectionTime.textContent="Última verificación: sin evidencia confirmada";
      clearFleetSnapshot();
      databaseState.textContent="Metadatos no disponibles · sin lectura confirmada";
      databaseTotal.textContent="—"; databaseData.textContent="— datos"; databaseIndex.textContent="— índices"; databaseTables.textContent="—"; byId("kpi-database").textContent="—";
      databaseIndexMeter.firstElementChild.style.width="0%"; positionsTotal.textContent="—"; positionsRows.textContent="— filas estimadas"; positionsShare.textContent="— del esquema"; positionsMeter.firstElementChild.style.width="0%";
    }
  }

  async function loadBoundaryHealth(){ try { const requestId=newRequestId(); const r=await fetchApi("maintenance/boundary/health?request_id="+encodeURIComponent(requestId)); if(!r.ok)throw new Error(); const d=await r.json(),b=d.boundary; if(!b||b.status!=="healthy"||!(["DENY_PRODUCTION","PRODUCTION_DELETE_ENABLED"].includes(b.mode))||b.destructive_action_performed!==false)throw new Error(); boundaryHealth.textContent=b.mode==="PRODUCTION_DELETE_ENABLED"?"ALERTA · gate productivo habilitado; no ejecutar hasta completar respaldo y verificación":"Frontera segura · DENY_PRODUCTION activo · eliminación bloqueada"; }catch(_e){ boundaryHealth.textContent="Frontera no disponible · operación bloqueada"; }}

  async function previewLogs() {
    // A new analysis invalidates previous preparation, even if validation or the API fails.
    lastPreview=null; lastPreparation=null; prepareLogsButton.hidden=true; executeLogsButton.disabled=true;
    maintenancePreparation.hidden=true; maintenanceSecurity.hidden=true; maintenanceReadiness.hidden=true;
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
      maintenanceSummary.hidden=false; lastPreview=p.candidate_count>0?{previewId:data.preview_id,days:days}:null; lastPreparation=null; executeLogsButton.disabled=true; executeNote.textContent="Disponible después de preparar un plan con candidatos. EXECUTE exige autorización, evidencia SHA-256, consumo único, anti-replay y revalidación antes de cualquier eliminación."; prepareLogsButton.hidden=p.candidate_count===0; maintenancePreparation.hidden=true; maintenanceSecurity.hidden=true;
      if(p.candidate_count===0){ maintenanceReadiness.textContent="Sin candidatos · Prepare y Execute deshabilitados · no hay nada que eliminar"; maintenanceReadiness.hidden=false; } else { maintenanceReadiness.hidden=true; }
      maintenanceRange.textContent=p.candidate_count ? "Rango candidato: "+p.oldest_candidate_utc+" → "+p.newest_candidate_utc : "No existen archivos fuera de la retención seleccionada. El flujo termina de forma segura sin Prepare ni Execute.";
      maintenanceRange.hidden=false;
      p.candidates.forEach((item)=>{ const li=document.createElement("li"); li.textContent=item.name+" — "+formatBytes(item.size_bytes)+" — "+item.mtime_utc; maintenanceCandidates.appendChild(li); });
    } catch (_error) { maintenanceState.textContent="Vista previa no disponible"; maintenanceDetail.textContent="No se realizó ninguna acción destructiva."; maintenanceError.textContent="No se pudo analizar los logs."; maintenanceError.hidden=false; }
    finally { previewLogsButton.disabled=false; }
  }


  async function prepareLogs(){ if(!lastPreview)return; prepareLogsButton.disabled=true; maintenanceError.hidden=true; try { const requestId=newRequestId(); const response=await fetchApi("maintenance/logs/prepare",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(Object.assign({request_id:requestId,preview_id:lastPreview.previewId,retention_days:lastPreview.days},interventionContext?{incident_id:interventionContext.incident_id}:{}))}); if(response.status===401){showLogin("La sesión expiró. Inicia sesión de nuevo.");return;} if(response.status===403){maintenancePreparation.textContent="Sin permiso maintenance.logs.prepare.";maintenancePreparation.hidden=false;return;} if(!response.ok)throw new Error(); const data=await response.json(),q=data.preparation,b=data.backup_evidence,v=data.evidence_verification; if(!q||q.destructive_action_performed!==false||q.revalidated!==true||data.preparation_stored!==true||data.execution_readiness!=="READY_BLOCKED"||data.boundary_execute_probe!=="DENIED_BY_PRODUCTION_GATE"||data.boundary_candidate_count!==q.candidate_count||!b||b.status!=="EVIDENCE_BACKUP_VERIFIED"||b.destructive_action_performed!==false||b.file_count!==q.candidate_count||!v||v.status!=="EVIDENCE_REVERIFIED"||v.identity_match!==true||v.content_hash_match!==true||v.destructive_action_performed!==false||v.manifest_sha256!==b.manifest_sha256)throw new Error(); const backupEvidence=document.getElementById("backup-evidence"),backupStep=document.getElementById("backup-step"); backupEvidence.textContent="Evidencia criptográfica verificada · "+b.file_count+" archivos · "+formatBytes(b.total_bytes)+" · manifiesto SHA-256 "+b.manifest_sha256.slice(0,16)+"… · sin duplicar contenido"; backupEvidence.hidden=false; backupStep.textContent="5 · Evidencia respaldada"; backupStep.className="done"; const verificationEvidence=document.getElementById("verification-evidence"),verifyStep=document.getElementById("verify-step"); verificationEvidence.textContent="Reverificación completada · identidad coincide · SHA-256 coincide · "+v.file_count+" archivos sin cambios"; verificationEvidence.hidden=false; verifyStep.textContent="7 · Evidencia verificada"; verifyStep.className="done"; maintenancePreparation.textContent="Preparación auditada y registro durable confirmados por Worker. Expira: "+q.expires_at_utc+" · lista para ejecución real autorizada; se volverá a validar antes de eliminar."+(interventionContext?" · Contexto: "+interventionContext.summary:"");maintenancePreparation.hidden=false; maintenanceReadiness.textContent="Plan real revalidado · "+data.boundary_candidate_count+" candidatos · validado por frontera; pendiente de confirmación"; maintenanceReadiness.hidden=false; maintenanceSecurity.hidden=false; prepareLogsButton.hidden=true; lastPreparation=q; executeLogsButton.disabled=false; executeNote.textContent="Plan preparado. Validar EXECUTE comprobará autorización, consumo único y anti-replay; la eliminación real sigue deshabilitada."; }catch(e){maintenanceError.textContent="No se pudo preparar la limpieza. Vuelve a analizar los logs.";maintenanceError.hidden=false;}finally{prepareLogsButton.disabled=false;} }

  async function executeLogs(){ if(!lastPreparation)return; executeLogsButton.disabled=true; maintenanceError.hidden=true; try { const requestId=newRequestId(); const response=await fetchApi("maintenance/logs/execute",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(Object.assign({request_id:requestId,preparation:lastPreparation,confirmation:"CONFIRMAR LIMPIEZA",nonce:lastPreparation.one_time_nonce},interventionContext?{incident_id:interventionContext.incident_id}:{}))}); if(response.status===401){showLogin("La sesión expiró. Inicia sesión de nuevo.");return;} if(response.status===403){maintenanceError.textContent="Sin permiso maintenance.logs.execute.";maintenanceError.hidden=false;return;} if(!response.ok)throw new Error(); const data=await response.json(),e=data.execution; if(!e||e.outcome!=="BLOCKED_BY_FEATURE_GATE"||e.destructive_action_performed!==false)throw new Error(); maintenanceReadiness.textContent="EXECUTE validado · autorización one-shot consumida · eliminación bloqueada por seguridad"; maintenanceReadiness.hidden=false; executeNote.textContent="Autorización one-shot consumida. No se eliminó ningún archivo. Para otra validación debes analizar y preparar un nuevo plan."; lastPreparation=null; }catch(_e){maintenanceError.textContent="EXECUTE no pudo completarse. Revisa el estado y vuelve a generar un PREVIEW antes de reintentar.";maintenanceError.hidden=false;} finally { executeLogsButton.disabled=true; }}

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
          const traccarOk=service.state.value==="active"&&service.substate.value==="running"; healthTraccar.textContent=traccarOk?"Activo · running":service.state.value+" · "+service.substate.value; healthTraccar.className=traccarOk?"ok":"warn";
          traccarDetail.textContent = "LoadState: " + service.load_state.value
            + " · UnitFileState: " + service.unit_file_state.value
            + " · Result: " + service.result.value + " · Observed UTC: " + observed;
        } else {
          traccarState.textContent = "Estado no disponible";
          traccarDetail.textContent = "No se muestran datos de estado en esta versión.";
        }
      }
      dashboardPanel.hidden = false;
      document.body.classList.add("authenticated");
      byId("kpi-traccar").textContent=traccarState.textContent;
      loadAccountProfile();
      loadBoundaryHealth();
      loadServerStatus();
      loadDeviceInventory();
      loadHealthHistory(24);
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

  const logout=async () => {
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
  };
  byId("logout-button").addEventListener("click",logout);
  byId("account-logout-button").addEventListener("click",logout);

  previewLogsButton.addEventListener("click", previewLogs);
  prepareLogsButton.addEventListener("click",prepareLogs);
  executeLogsButton.addEventListener("click",executeLogs);

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
        progress_init()
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
                         "form-action 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'")
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

    def _account_principal(self):
        token=self._cookie_token(); return token, self.server.session_store.get(token) if token is not None else None

    def _read_json_object(self, limit=3000000):
        if self.headers.get("Transfer-Encoding") is not None: return None
        try:
            if self.headers.get("Content-Type","").split(";",1)[0].strip().lower()!="application/json": return None
            n=int(self.headers.get("Content-Length","0"))
            if not 1<=n<=limit: return None
            d=json.loads(self.rfile.read(n).decode("utf-8")); return d if isinstance(d,dict) else None
        except Exception: return None

    def _handle_account_profile_get(self):
        _,p=self._account_principal()
        if p is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        self._json(HTTPStatus.OK,{"profile":read_profile()})

    def _handle_account_profile_save(self):
        _,p=self._account_principal(); d=self._read_json_object()
        if p is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if d is None or set(d)!={"name","email"}: self._json(HTTPStatus.BAD_REQUEST,{"error":"invalid_request"}); return
        try: profile=save_profile(d["name"],d["email"])
        except Exception: self._json(HTTPStatus.BAD_REQUEST,{"error":"invalid_profile"}); return
        self._audit("ACCOUNT_PROFILE_UPDATE","SUCCEEDED","PROFILE_UPDATED"); self._json(HTTPStatus.OK,{"profile":profile})

    def _handle_account_alert_state(self):
        _,p=self._account_principal(); d=self._read_json_object(limit=12000)
        if p is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if d is None or set(d)!={"key","mark_seen"} or not isinstance(d.get("key"),str) or not isinstance(d.get("mark_seen"),bool): self._json(HTTPStatus.BAD_REQUEST,{"error":"invalid_request"}); return
        try:
            if d["mark_seen"]: mark_alert_seen(d["key"]); unread=False
            else: unread=alert_unread(d["key"])
        except Exception: self._json(HTTPStatus.BAD_REQUEST,{"error":"invalid_alert_state"}); return
        self._json(HTTPStatus.OK,{"unread":unread})

    def _handle_account_avatar(self):
        _,p=self._account_principal()
        if p is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        item=read_avatar()
        if item is None: self._respond(HTTPStatus.NOT_FOUND,b"Not Found\n","text/plain; charset=utf-8"); return
        self._respond(HTTPStatus.OK,item[0],item[1])

    def _handle_account_avatar_save(self):
        _,p=self._account_principal(); d=self._read_json_object()
        if p is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        try:
            if d is None or set(d)!={"data"} or not isinstance(d["data"],str): raise ValueError()
            import base64
            raw=base64.b64decode(d["data"],validate=True); save_avatar(raw)
        except Exception: self._json(HTTPStatus.BAD_REQUEST,{"error":"invalid_avatar"}); return
        self._audit("ACCOUNT_AVATAR_UPDATE","SUCCEEDED","AVATAR_UPDATED"); self._json(HTTPStatus.OK,{"saved":True})

    def _handle_account_password_save(self):
        token,p=self._account_principal(); d=self._read_json_object()
        if p is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if d is None or set(d)!={"current_password","new_password"}: self._json(HTTPStatus.BAD_REQUEST,{"error":"invalid_request"}); return
        try: valid=self.server.auth_store.authenticate(p.username,d["current_password"])
        except Exception: valid=None
        if valid is None: self._audit("ACCOUNT_PASSWORD_CHANGE","DENIED","CURRENT_PASSWORD_INVALID"); self._json(HTTPStatus.UNAUTHORIZED,{"error":"current_password_invalid"}); return
        try: save_password(d["new_password"])
        except Exception: self._json(HTTPStatus.BAD_REQUEST,{"error":"password_policy"}); return
        self._audit("ACCOUNT_PASSWORD_CHANGE","SUCCEEDED","PASSWORD_CHANGED"); self.server.session_store.revoke(token)
        headers=(("Set-Cookie",f"{SESSION_COOKIE}=; Path={COOKIE_PATH}; Max-Age=0; Secure; HttpOnly; SameSite=Strict"),)
        self._json(HTTPStatus.OK,{"changed":True},headers)

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

    def _handle_server_status(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "dashboard.read" not in principal.roles: self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        try:
            data=read_server_status()
            incidents=read_incidents(100).get("events",[])
            data["operational_health"]=operational_health(data,incidents)
        except (OSError,ValueError,json.JSONDecodeError): self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"server_status_unavailable"}); return
        self._json(HTTPStatus.OK,data)

    def _handle_device_inventory(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "dashboard.read" not in principal.roles: self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        try: data=read_device_inventory()
        except (OSError,ValueError,TypeError): self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"device_inventory_unavailable"}); return
        self._json(HTTPStatus.OK,data)

    def _handle_health_history(self, query: dict[str, list[str]]) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "dashboard.read" not in principal.roles: self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        raw=(query.get("hours") or ["24"])[0]; hours=168 if raw=="168" else 24
        try: self._json(HTTPStatus.OK,read_health_history(hours))
        except (OSError,ValueError,json.JSONDecodeError): self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"health_history_unavailable"})


    def _handle_global_interventions(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "dashboard.read" not in principal.roles: self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        try: self._json(HTTPStatus.OK,read_global_interventions())
        except (OSError,ValueError,json.JSONDecodeError): self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"interventions_unavailable"})

    def _handle_operational_availability(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "dashboard.read" not in principal.roles: self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        try: self._json(HTTPStatus.OK,read_operational_availability())
        except (OSError,ValueError,json.JSONDecodeError): self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"operational_availability_unavailable"})


    def _handle_administrative_attention_metrics(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None:self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"});return
        if "dashboard.read" not in principal.roles:self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"});return
        try:self._json(HTTPStatus.OK,read_administrative_attention_metrics())
        except (OSError,ValueError,json.JSONDecodeError):self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"administrative_attention_metrics_unavailable"})

    def _handle_administrative_index_history(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None:self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"});return
        if "dashboard.read" not in principal.roles:self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"});return
        try:self._json(HTTPStatus.OK,read_administrative_index_history(40))
        except (OSError,ValueError,json.JSONDecodeError):self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"administrative_index_history_unavailable"})

    def _handle_administrative_attention_history(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None:self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"});return
        if "dashboard.read" not in principal.roles:self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"});return
        try:self._json(HTTPStatus.OK,read_administrative_attention_history(40))
        except (OSError,ValueError,json.JSONDecodeError):self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"administrative_attention_history_unavailable"})

    def _handle_operational_health_history(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "dashboard.read" not in principal.roles: self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        try: self._json(HTTPStatus.OK,read_operational_health_history(40))
        except (OSError,ValueError,json.JSONDecodeError): self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"operational_health_history_unavailable"})

    def _handle_preventive_diagnostics(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "dashboard.read" not in principal.roles: self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        try:
            events=read_incidents(100).get("events",[])
            server=read_server_status()
            self._json(HTTPStatus.OK,diagnostic_center(events,server))
        except (OSError,ValueError,json.JSONDecodeError):
            self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"preventive_diagnostics_unavailable"})

    def _handle_incident_casefile(self, incident_id: str) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "dashboard.read" not in principal.roles: self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        try:
            events=read_incidents(100).get("events",[])
            event=next((e for e in events if e.get("id")==incident_id),None)
            if event is None: self._json(HTTPStatus.NOT_FOUND,{"error":"incident_not_found"}); return
            casefile=incident_casefile(event,read_server_status())
            casefile["administrative_decisions"]=read_incident_decisions(incident_id)
            self._json(HTTPStatus.OK,casefile)
        except (OSError,ValueError,json.JSONDecodeError):
            self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"incident_casefile_unavailable"})

    def _handle_incidents(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "dashboard.read" not in principal.roles: self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        try: self._json(HTTPStatus.OK,read_incidents(30))
        except (OSError,ValueError,json.JSONDecodeError): self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"incident_history_unavailable"})

    def _handle_audit_recent(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "dashboard.read" not in principal.roles: self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        events=read_recent_auth_audit()
        self._json(HTTPStatus.OK,{"events":events,"event_count":len(events),"scope":"current_instance","sanitized":True,"read_only":True})

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
            if not isinstance(data,dict) or not {"request_id","preview_id","retention_days"}<=set(data)<= {"request_id","preview_id","retention_days","incident_id"}: raise ValueError()
            if not isinstance(data["request_id"],str) or not data["request_id"] or not isinstance(data["preview_id"],str) or not data["preview_id"].startswith("preview-") or len(data["preview_id"])!=72 or type(data["retention_days"]) is not int or not 30<=data["retention_days"]<=3650: raise ValueError()
            incident_id=data.get("incident_id")
            if incident_id is not None:
                if not isinstance(incident_id,str) or not any(e.get("id")==incident_id and e.get("status")=="OPEN" for e in read_incidents(100).get("events",[])): raise ValueError()
        except Exception: self._json(HTTPStatus.BAD_REQUEST,{"error":"invalid_request"}); return
        try: result=self.server.maintenance_api.prepare_logs(data["request_id"],principal,data["preview_id"],data["retention_days"],data.get("incident_id"))
        except MaintenanceAPIError as exc:
            status={"API_FORBIDDEN":HTTPStatus.FORBIDDEN,"API_INVALID_REQUEST":HTTPStatus.BAD_REQUEST,"API_AUDIT_UNAVAILABLE":HTTPStatus.SERVICE_UNAVAILABLE,"API_PROVIDER_UNAVAILABLE":HTTPStatus.SERVICE_UNAVAILABLE}.get(exc.code,HTTPStatus.INTERNAL_SERVER_ERROR); self._json(status,{"error":"maintenance_unavailable","request_id":data["request_id"]}); return
        self._json(HTTPStatus.OK,result)

    def _handle_maintenance_logs_execute(self) -> None:
        token=self._cookie_token(); principal=self.server.session_store.get(token) if token is not None else None
        if principal is None: self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"}); return
        if "maintenance.logs.execute" not in principal.roles: self._json(HTTPStatus.FORBIDDEN,{"error":"forbidden"}); return
        try:
            length=int(self.headers.get("Content-Length","0")); data=json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data,dict) or not {"request_id","preparation","confirmation","nonce"}<=set(data)<= {"request_id","preparation","confirmation","nonce","incident_id"}: raise ValueError()
            if not isinstance(data["request_id"],str) or not data["request_id"] or not isinstance(data["preparation"],dict) or not isinstance(data["confirmation"],str) or not isinstance(data["nonce"],str): raise ValueError()
            incident_id=data.get("incident_id")
            if incident_id is not None:
                if not isinstance(incident_id,str) or not any(e.get("id")==incident_id and e.get("status")=="OPEN" for e in read_incidents(100).get("events",[])): raise ValueError()
        except Exception: self._json(HTTPStatus.BAD_REQUEST,{"error":"invalid_request"}); return
        try: result=self.server.maintenance_api.execute_logs(data["request_id"],principal,data["preparation"],data["confirmation"],data["nonce"],data.get("incident_id"))
        except MaintenanceAPIError as exc:
            status={"API_FORBIDDEN":HTTPStatus.FORBIDDEN,"API_INVALID_REQUEST":HTTPStatus.BAD_REQUEST,"API_PROVIDER_UNAVAILABLE":HTTPStatus.SERVICE_UNAVAILABLE}.get(exc.code,HTTPStatus.INTERNAL_SERVER_ERROR)
            self._json(status,{"error":"maintenance_unavailable","request_id":data["request_id"]}); return
        self._json(HTTPStatus.OK,result)

    def _progress_principal(self):
        _, principal = self._account_principal()
        if principal is None:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return None
        if not progress_authorized(principal):
            self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            return None
        return principal

    def _handle_progress_get(self, page=False):
        if page:
            _, principal = self._account_principal()
            if principal is None:
                self._respond(HTTPStatus.SEE_OTHER, b"", "text/plain; charset=utf-8",
                              (("Location", "/manager/"),))
                return
            if not progress_authorized(principal):
                self._respond(HTTPStatus.FORBIDDEN,
                              b"Acceso restringido al superadministrador.",
                              "text/plain; charset=utf-8")
                return
            self._respond(HTTPStatus.OK, PROGRESS_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        principal = self._progress_principal()
        if principal is None:
            return
        if page:
            self._respond(HTTPStatus.OK, PROGRESS_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        try:
            self._json(HTTPStatus.OK, progress_snapshot(principal))
        except Exception:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "progress_unavailable"})

    def _handle_progress_post(self):
        principal = self._progress_principal()
        if principal is None:
            return
        origin = self.headers.get("Origin")
        if origin != "https://homecargps.com" or self.headers.get("X-Requested-With") != "TraccarManager":
            self._json(HTTPStatus.FORBIDDEN, {"error": "origin_denied"})
            return
        payload = self._read_json_object(limit=16000)
        try:
            result = progress_update(principal, payload)
        except (ProgressError, ValueError, TypeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_progress_update"})
            return
        except Exception:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "progress_unavailable"})
            return
        self._json(HTTPStatus.OK, result)

    def _handle_progress_event(self):
        principal=self._progress_principal()
        if principal is None:return
        if self.headers.get("Origin")!="https://homecargps.com" or self.headers.get("X-Requested-With")!="TraccarManager":
            self._json(HTTPStatus.FORBIDDEN,{"error":"origin_denied"});return
        payload=self._read_json_object(limit=16000)
        try:
            outcome=progress_ingest_event(principal,payload)
        except (ProgressError,ValueError,TypeError):
            self._json(HTTPStatus.BAD_REQUEST,{"error":"invalid_event"});return
        except Exception:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE,{"error":"progress_unavailable"});return
        self._json(HTTPStatus.OK,outcome)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=True)
        if path == "/":
            self._respond(HTTPStatus.OK, PAGE, "text/html; charset=utf-8")
        elif path == "/health":
            payload = json.dumps(HEALTH, separators=(",", ":")).encode("ascii")
            self._respond(HTTPStatus.OK, payload, "application/json")
        elif path == "/progress-client.js":
            principal = self._progress_principal()
            if principal is not None:
                data = (_ProgressPath(__file__).parent / "progress_client.js").read_bytes()
                self._respond(HTTPStatus.OK, data, "application/javascript; charset=utf-8")
        elif path == "/app.js":
            self._respond(HTTPStatus.OK, APP_JS, "application/javascript; charset=utf-8")
        elif path == "/brand-icon.svg":
            self._respond(HTTPStatus.OK, BRAND_ICON, "image/svg+xml; charset=utf-8")
        elif path.startswith("/assets/vehicle-icons/") or path.startswith("/manager/assets/vehicle-icons/") or path.startswith("/assets/vehicle-icons-webp/") or path.startswith("/manager/assets/vehicle-icons-webp/"):
            webp_pack = "/assets/vehicle-icons-webp/" in path
            marker = "/assets/vehicle-icons-webp/" if webp_pack else "/assets/vehicle-icons/"
            rel = path.split(marker,1)[1].split("?",1)[0]
            if rel.endswith((".svg", ".webp")) and "/" not in rel:
                asset_dir = "vehicle-icons-webp" if webp_pack else "vehicle-icons"
                asset = Path(__file__).resolve().parent / "assets" / asset_dir / rel
                if asset.is_file():
                    data=asset.read_bytes(); content_type="image/webp" if rel.endswith(".webp") else "image/svg+xml"; self.send_response(200); self.send_header("Content-Type",content_type); self.send_header("Cache-Control","public, max-age=31536000, immutable"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
            self._respond(HTTPStatus.NOT_FOUND, b"Not Found\n", "text/plain; charset=utf-8")
            return
        elif path == "/progress":
            self._handle_progress_get(page=True)
        elif path == "/api/progress":
            self._handle_progress_get()
        elif path == "/api/progress/plan":
            principal = self._progress_principal()
            if principal is not None:
                self._json(HTTPStatus.OK, progress_plan_source())
        elif path == "/api/auth/me":
            self._handle_me()
        elif path == "/api/account/profile":
            self._handle_account_profile_get()
        elif path == "/api/account/avatar":
            self._handle_account_avatar()
        elif path == "/api/dashboard/snapshot":
            self._handle_dashboard_snapshot()
        elif path == "/api/server/status":
            self._handle_server_status()
        elif path == "/api/devices/inventory":
            self._handle_device_inventory()
        elif path == "/api/audit/recent":
            self._handle_audit_recent()
        elif path == "/api/audit/interventions":
            self._handle_global_interventions()
        elif path == "/api/health/history":
            self._handle_health_history(query)
        elif path == "/api/health/incidents":
            self._handle_incidents()
        elif path.startswith("/api/health/incidents/") and path.endswith("/casefile"):
            incident_id=path[len("/api/health/incidents/"):-len("/casefile")].strip("/")
            self._handle_incident_casefile(incident_id)
        elif path == "/api/health/diagnostics":
            self._handle_preventive_diagnostics()
        elif path == "/api/health/operational-history":
            self._handle_operational_health_history()
        elif path == "/api/health/administrative-index-history":
            self._handle_administrative_index_history()
        elif path == "/api/health/administrative-attention-history":
            self._handle_administrative_attention_history()
        elif path == "/api/health/administrative-attention-metrics":
            self._handle_administrative_attention_metrics()
        elif path == "/api/health/operational-availability":
            self._handle_operational_availability()
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
        if path == "/api/progress/event":
            self._handle_progress_event()
        elif path == "/api/progress":
            self._handle_progress_post()
        elif path == "/api/auth/login":
            self._handle_login()
        elif path == "/api/auth/logout":
            self._handle_logout()
        elif path == "/api/account/profile":
            self._handle_account_profile_save()
        elif path == "/api/account/avatar":
            self._handle_account_avatar_save()
        elif path == "/api/account/password":
            self._handle_account_password_save()
        elif path == "/api/account/alert-state":
            self._handle_account_alert_state()
        elif path == "/api/maintenance/logs/prepare":
            self._handle_maintenance_logs_prepare()
        elif path == "/api/maintenance/logs/execute":
            self._handle_maintenance_logs_execute()
        elif path in ("/", "/health", "/app.js", "/api/auth/me", "/api/dashboard/snapshot", "/api/server/status", "/api/maintenance/logs/preview"):
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
