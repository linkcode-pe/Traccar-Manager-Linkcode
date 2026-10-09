"""AUD-003: HTTP authorization regression in an isolated SQLite lab."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from manager.auth.auth_store import AuthenticatedUser
from manager.auth.session_store import SessionStore
from manager import progress
from manager.web_app import ManagerHTTPServer

class ProgressRoleHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(progress, "DB_PATH", Path(self.tmp.name) / "progress.sqlite3")
        self.db_patch.start()
        self.sessions = SessionStore()
        self.admin, _ = self.sessions.create(AuthenticatedUser("a"*32, "audit-admin", ("development.progress.manage",)))
        self.viewer, _ = self.sessions.create(AuthenticatedUser("b"*32, "audit-viewer", ("dashboard.read",)))
        self.server = ManagerHTTPServer(port=0, session_store=self.sessions)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.db_patch.stop()
        self.tmp.cleanup()

    def request(self, method, path, token=None, payload=None, origin="https://homecargps.com"):
        headers = {}
        if token:
            headers["Cookie"] = "tm_session=" + token
        body = None
        if payload is not None:
            body = json.dumps(payload)
            headers.update({"Content-Type": "application/json", "Origin": origin, "X-Requested-With": "TraccarManager"})
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        status, location = resp.status, resp.getheader("Location")
        conn.close()
        return status, location, data

    def test_anonymous_read_denied(self):
        self.assertEqual(self.request("GET", "/api/progress")[0], 401)
        self.assertEqual(self.request("GET", "/api/progress/ledger")[0], 401)
        self.assertEqual(self.request("GET", "/progress")[0], 303)

    def test_viewer_cannot_read_or_write(self):
        for path in ("/progress", "/api/progress", "/api/progress/plan", "/api/progress/ledger"):
            self.assertEqual(self.request("GET", path, self.viewer)[0], 403, path)
        event = {"event_id":"audit003-test-event-001","task_id":"AUD-003","source":"test-suite","state":"in_testing","doc_state":"in_review","evidence":["test"]}
        self.assertEqual(self.request("POST", "/api/progress/event", self.viewer, event)[0], 403)
        self.assertEqual(self.request("POST", "/api/progress", self.viewer, {"task_id":"AUD-003","state":"in_testing","doc_state":"in_review","evidence":["test"]})[0], 403)

    def test_ledger_http_authorization_pagination_and_invalid_cursor(self):
        from manager.progress_evidence_ledger import record_success
        with progress.connect() as db:
            for i in range(22):
                record_success(db, event_id='test-run-' + format(i, '024x'), task_id='PROG-006',
                               source_sha256='a' * 64, report_path='docs/test-runs/missing.md',
                               report_sha256='b' * 64)
        status, _, body = self.request('GET', '/api/progress/ledger', self.admin)
        self.assertEqual(status, 200)
        first = json.loads(body)
        self.assertEqual(len(first['items']), 10)
        self.assertIsNotNone(first['next_cursor'])
        status, _, body = self.request('GET', '/api/progress/ledger?before=' + first['next_cursor'], self.admin)
        self.assertEqual(status, 200)
        second = json.loads(body)
        status, _, body = self.request('GET', '/api/progress/ledger?before=' + second['next_cursor'], self.admin)
        self.assertEqual(status, 200)
        third = json.loads(body)
        self.assertEqual([len(p['items']) for p in (first, second, third)], [10, 10, 2])
        self.assertIsNone(third['next_cursor'])
        self.assertEqual(len({e['event_id'] for p in (first, second, third) for e in p['items']}), 22)
        self.assertEqual(self.request('GET', '/api/progress/ledger?before=invalid', self.admin)[0], 400)
        self.assertEqual(self.request('GET', '/api/progress/ledger?before=invalid', self.viewer)[0], 403)
        self.assertEqual(self.request('GET', '/api/progress/ledger?before=invalid')[0], 401)

    def test_admin_read_and_origin(self):
        self.assertEqual(self.request("GET", "/progress", self.admin)[0], 200)
        self.assertEqual(self.request("GET", "/api/progress", self.admin)[0], 200)
        event = {"event_id":"audit003-test-event-002","task_id":"AUD-003","source":"test-suite","state":"in_testing","doc_state":"in_review","evidence":["test"]}
        self.assertEqual(self.request("POST", "/api/progress/event", self.admin, event, "https://invalid.example")[0], 403)
        self.assertEqual(self.request("POST", "/api/progress/event", self.admin, event)[0], 200)
        self.assertEqual(self.request("POST", "/api/progress/event", self.admin, event)[0], 200)

if __name__ == "__main__":
    unittest.main(verbosity=2)
