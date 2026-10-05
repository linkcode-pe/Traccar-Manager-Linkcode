import unittest
from unittest.mock import Mock
from manager.auth.session_store import SessionPrincipal
from manager.maintenance_http import ManagerMaintenanceAPI, MaintenanceAPIError
from worker.maintenance_preview_dispatch import ROLE

class ManagerMaintenanceAPITests(unittest.TestCase):
    def principal(self, roles=(ROLE,)):
        return SessionPrincipal("a"*32,"admin",roles,"2099-01-01T00:00:00Z")
    def test_roleless_fails_before_worker(self):
        worker=Mock(); api=ManagerMaintenanceAPI(ledger=Mock(),worker_query=worker)
        with self.assertRaisesRegex(MaintenanceAPIError,"API_FORBIDDEN"): api.preview_logs("req-1",self.principal(()),90)
        worker.assert_not_called()
    def test_verified_preview_returns_sanitized_model(self):
        preview={"log_dir":"/opt/traccar/logs","retention_days":90,"cutoff_utc":"2026-01-01T00:00:00Z","candidate_count":0,"candidate_bytes":0,"candidates":[],"active_log_protected":True,"destructive_action_performed":False}
        receipt={"x":1}; worker=Mock(return_value={"preview":preview,"preview_id":"preview-"+"a"*64,"audit_receipt":receipt})
        ledger=Mock(); ledger.verify_finalization_receipt_generic.return_value=True
        result=ManagerMaintenanceAPI(ledger=ledger,worker_query=worker).preview_logs("req-1",self.principal(),90)
        self.assertEqual(preview,result["preview"]); self.assertNotIn("audit_receipt",result); self.assertEqual(1,result["schema_version"])
    def test_invalid_audit_receipt_fails_closed(self):
        worker=Mock(return_value={"preview":{},"preview_id":"preview-"+"a"*64,"audit_receipt":{}}); ledger=Mock(); ledger.verify_finalization_receipt_generic.return_value=False
        with self.assertRaisesRegex(MaintenanceAPIError,"API_AUDIT_UNAVAILABLE"): ManagerMaintenanceAPI(ledger=ledger,worker_query=worker).preview_logs("req-1",self.principal(),90)

class MaintenanceHTTPRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import http.client, threading
        from manager.auth.auth_store import AuthenticatedUser
        from manager.auth.session_store import SessionStore
        from manager.web_app import ManagerHTTPServer
        class NoAuth:
            def authenticate(self,*_): return None
        class DashboardStub:
            def close(self): pass
        class MaintenanceStub:
            def __init__(self): self.calls=[]
            def preview_logs(self,request_id,principal,days):
                self.calls.append((request_id,principal.subject_id,principal.roles,days))
                return {"schema_version":1,"request_id":request_id,"operation":"maintenance.logs.preview",
                        "preview_id":"preview-"+"a"*64,"preview":{"log_dir":"/opt/traccar/logs","retention_days":days,
                        "cutoff_utc":"2026-07-07T00:00:00Z","candidate_count":1,"candidate_bytes":1234,
                        "candidates":[{"name":"tracker-server.log.20260101","size_bytes":1234,"mtime_utc":"2026-01-01T00:00:00Z"}],
                        "active_log_protected":True,"destructive_action_performed":False}}
            def close(self): pass
        cls.http=http.client; cls.sessions=SessionStore(); cls.maintenance=MaintenanceStub()
        user=AuthenticatedUser("d"*32,"maint",("dashboard.read","maintenance.logs.preview")); cls.token,_=cls.sessions.create(user)
        cls.server=ManagerHTTPServer(0,auth_store=NoAuth(),session_store=cls.sessions,audit_writer=lambda *_: True,
                                     dashboard_api=DashboardStub(),maintenance_api=cls.maintenance)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=3)
    def req(self,path,method="GET",headers=None):
        c=self.http.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3); c.request(method,path,headers=headers or {}); r=c.getresponse(); b=r.read(); out=(r.status,dict(r.getheaders()),b); c.close(); return out
    def test_authenticated_preview_route(self):
        status,headers,body=self.req("/api/maintenance/logs/preview?request_id=maint-http-1&retention_days=90",headers={"Cookie":"tm_session="+self.token})
        self.assertEqual(200,status); self.assertEqual("no-store",headers.get("Cache-Control")); data=__import__('json').loads(body)
        self.assertFalse(data["preview"]["destructive_action_performed"]); self.assertTrue(data["preview"]["active_log_protected"])
    def test_route_rejects_anonymous_spoof_and_bad_parameters(self):
        before=len(self.maintenance.calls)
        self.assertEqual(401,self.req("/api/maintenance/logs/preview?request_id=x&retention_days=90",headers={"X-Role":"maintenance.logs.preview"})[0])
        cookie={"Cookie":"tm_session="+self.token}
        self.assertEqual(400,self.req("/api/maintenance/logs/preview?request_id=x&retention_days=29",headers=cookie)[0])
        self.assertEqual(400,self.req("/api/maintenance/logs/preview?request_id=x&retention_days=90&path=/tmp",headers=cookie)[0])
        self.assertEqual(before,len(self.maintenance.calls))
    def test_post_is_method_not_allowed(self):
        status,headers,_=self.req("/api/maintenance/logs/preview",method="POST")
        self.assertEqual(405,status); self.assertEqual("GET",headers.get("Allow"))
