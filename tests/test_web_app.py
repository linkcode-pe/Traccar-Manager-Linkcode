"""Isolated tests for the loopback-only Manager Web bootstrap."""
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from manager.web_app import BIND_ADDRESS, ManagerHTTPServer


class ManagerWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ManagerHTTPServer(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://{BIND_ADDRESS}:{cls.server.server_port}"
        cls.opener = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, path, method="GET"):
        request = Request(self.base_url + path, method=method)
        try:
            with self.opener.open(request, timeout=3) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            try:
                return error.code, error.headers, error.read()
            finally:
                error.close()

    def test_server_is_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertEqual(self.server.socket.getsockname()[0], "127.0.0.1")

    def test_root_returns_authenticated_manager_page(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        text = body.decode("utf-8")
        self.assertIn("Traccar Manager", text)
        self.assertIn("Manager Web", text)
        self.assertIn('id="login-form"', text)
        self.assertIn('method="post"', text)
        self.assertIn('id="dashboard-panel"', text)
        self.assertIn("Proveedor pendiente", text)
        self.assertIn('<script src="/manager/app.js" defer></script>', text)
        self.assertNotIn("Health: OK", text)
        self.assertNotIn("<script>", text)
        self.assertIn("script-src 'self'", headers.get("Content-Security-Policy", ""))
        self.assertIn("connect-src 'self'", headers.get("Content-Security-Policy", ""))

    def test_frontend_asset_is_served_without_cache(self):
        status, headers, body = self.request("/app.js")
        self.assertEqual(status, 200)
        self.assertIn("application/javascript", headers.get("Content-Type", ""))
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        script = body.decode("utf-8")
        for endpoint in ("auth/login", "auth/me", "auth/logout", "dashboard/snapshot?request_id="):
            self.assertIn(endpoint, script)
        self.assertNotIn("showDashboard", script)
        self.assertIn("snapshot.schema_version !== 1", script)
        self.assertIn("snapshot.request_id !== requestId", script)
        self.assertIn('value.availability === "PENDING_PROVIDER"', script)
        self.assertEqual(script.count("dashboardPanel.hidden = false;"), 1)

    def test_frontend_does_not_persist_secrets_or_run_commands(self):
        _status, _headers, body = self.request("/app.js")
        script = body.decode("utf-8")
        for forbidden in ("localStorage", "sessionStorage", "document.cookie", "systemctl",
                          "subprocess", "console.log", "innerHTML"):
            self.assertNotIn(forbidden, script)

    def test_frontend_asset_rejects_post(self):
        status, headers, _body = self.request("/app.js", method="POST")
        self.assertEqual(status, 405)
        self.assertEqual(headers.get("Allow"), "GET")

    def test_health_returns_expected_json(self):
        status, headers, body = self.request("/health")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "application/json")
        payload = json.loads(body)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "traccar-manager")

    def test_unknown_route_returns_404(self):
        status, _headers, _body = self.request("/not-a-route")
        self.assertEqual(status, 404)

    def test_mutating_methods_are_rejected(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                status, headers, _body = self.request("/health", method=method)
                self.assertEqual(status, 405)
                self.assertEqual(headers.get("Allow"), "GET")


if __name__ == "__main__":
    unittest.main()
