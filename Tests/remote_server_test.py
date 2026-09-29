import json
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import Future

from Interface.remote_server import RemoteServer


class RemoteServerTest(unittest.TestCase):

    def setUp(self):
        self.responses = {}
        self.server = None

    def tearDown(self):
        if self.server is not None:
            self.server.stop()

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    def _start(self, token="", on_command=None):
        server = RemoteServer(host="127.0.0.1", port=0, token=token,
                              on_command=on_command, timeout=2)
        self.assertTrue(server.start())
        self.server = server
        return server._server.server_address[1]

    def _request(self, method, port, path, body=None, token=None):
        url = f"http://127.0.0.1:{port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("X-MAXIE-Token", token)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode())

    @staticmethod
    def _future_response(text):
        future = Future()
        future.set_result(text)
        return future

    # --------------------------------------------------
    # Security: binding + tokens
    # --------------------------------------------------

    def test_lan_binding_without_token_raises(self):
        with self.assertRaises(ValueError):
            RemoteServer(host="0.0.0.0", token="")

    def test_loopback_binding_without_token_is_allowed(self):
        RemoteServer(host="127.0.0.1", port=0, token="")

    def test_missing_token_rejected(self):
        port = self._start(token="hunter2")

        code, payload = self._request("GET", port, "/health")
        self.assertEqual(code, 401)
        self.assertFalse(payload["ok"])

    def test_invalid_token_rejected(self):
        port = self._start(token="hunter2")
        code, payload = self._request("GET", port, "/health", token="wrong")
        self.assertEqual(code, 401)

    # --------------------------------------------------
    # Functionality
    # --------------------------------------------------

    def test_health_endpoint(self):
        port = self._start(token="hunter2")
        code, payload = self._request("GET", port, "/health", token="hunter2")
        self.assertEqual(code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["running"])

    def test_root_endpoint_lists_capabilities(self):
        port = self._start()
        code, payload = self._request("GET", port, "/")
        self.assertEqual(code, 200)
        self.assertIn("endpoints", payload)

    def test_command_endpoint_returns_response(self):
        port = self._start(on_command=lambda text: self._future_response(
            "The time is 10:30 AM." if "time" in text else "Understood."
        ))

        code, payload = self._request(
            "POST", port, "/command", {"text": "what time is it"}
        )
        self.assertEqual(code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["response"], "The time is 10:30 AM.")

    def test_command_timeout_is_graceful(self):
        port = self._start(on_command=lambda text: Future())  # never resolves

        code, payload = self._request("POST", port, "/command", {"text": "hi"})
        self.assertEqual(code, 200)
        self.assertIn("took too long", payload["response"])

    def test_empty_command_rejected(self):
        port = self._start()
        code, payload = self._request("POST", port, "/command", {"text": "  "})
        self.assertEqual(code, 400)

    def test_unknown_path_404(self):
        port = self._start()
        code, payload = self._request("GET", port, "/nope")
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()