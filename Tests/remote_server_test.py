import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import Future

from Interface.remote_server import RemoteServer
from Logs.logger import Logger


class _CapturingLogger:
    """Wraps the real Logger, recording INFO lines for assertions."""

    def __init__(self, real, sink):
        self._real = real
        self._sink = sink

    def info(self, message):
        self._sink.append(str(message))

    def warning(self, message):
        self._sink.append(str(message))

    def error(self, message):
        self._sink.append("ERROR " + str(message))

    def debug(self, message):
        pass

    @staticmethod
    def utterance(text):
        return Logger.utterance(text)


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

    def _start(self, token="", on_command=None, on_voice=None, config=None):
        server = RemoteServer(host="127.0.0.1", port=0, token=token,
                              on_command=on_command, on_voice=on_voice,
                              timeout=2, config=config)
        self.assertTrue(server.start())
        self.server = server
        # Capture the MAXIE log stream for audit assertions. A real
        # Logger is used (not a bare mock) so utterance redaction behaves
        # exactly as it does in production.
        self._log_lines = []
        real = Logger.instance()
        server.logger = _CapturingLogger(real, self._log_lines)
        return server._server.server_address[1]

    def logger_output(self):
        return list(self._log_lines)

    def _request(self, method, port, path, body=None, token=None,
                 headers=None, raw_body=None):
        url = f"http://127.0.0.1:{port}{path}"
        if raw_body is not None:
            data = raw_body
        elif body is not None:
            data = json.dumps(body).encode()
        else:
            data = None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body_text = response.read()
                try:
                    return response.status, json.loads(body_text.decode())
                except ValueError:
                    return response.status, body_text.decode()
        except urllib.error.HTTPError as error:
            body_text = error.read()
            try:
                return error.code, json.loads(body_text.decode())
            except ValueError:
                return error.code, body_text.decode()

    @staticmethod
    def _future_response(text):
        future = Future()
        future.set_result(text)
        return future

    def _drain(self, httpd, expected, timeout=5.0):
        """Wait for the server's live-request count to reach ``expected``.

        A connection slot is released as its response is flushed, which is
        a hair after the client reads the last byte, so any assertion
        about a post-response slot count has to tolerate that ordering.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            active = httpd.active_threads
            if active == expected:
                return active
            time.sleep(0.01)
        return httpd.active_threads

    def _raw_response(self, method, port, path):
        url = f"http://127.0.0.1:{port}{path}"
        request = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)

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

    def test_bearer_auth_accepted(self):
        port = self._start(token="hunter2")
        code, payload = self._request("GET", port, "/health", token="hunter2")
        self.assertEqual(code, 200)

    def test_token_compare_is_constant_time(self):
        # Property-level check: remote compares via compare_digest, not `==`.
        port = self._start(token="correct horse")
        code, _ = self._request("GET", port, "/health", token="correct horse")
        self.assertEqual(code, 200)
        with open("Interface/remote_server.py", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("hmac.compare_digest", source)

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

    def test_voice_body_rejected_above_cap(self):
        config = {"max_voice_bytes": 1024}
        port = self._start(on_voice=lambda path: {"response": "ok"}, config=config)
        code, payload = self._request(
            "POST", port, "/voice", raw_body=b"RIFF" + b"\x00" * 2048
        )
        self.assertEqual(code, 413)
        self.assertIn("limit", payload["error"])

    def test_command_body_rejected_above_cap(self):
        config = {"max_command_bytes": 128}
        port = self._start(config=config)
        code, payload = self._request(
            "POST", port, "/command", raw_body=b"x" * 512
        )
        self.assertEqual(code, 413)
        self.assertIn("limit", payload["error"])

    def test_cors_wildcard_never_emitted(self):
        port = self._start()
        _, body, headers = self._raw_response("GET", port, "/")
        self.assertNotIn(b"Access-Control-Allow-Origin: *", body)
        self.assertNotEqual(
            headers.get("Access-Control-Allow-Origin"), "*"
        )

    def test_cors_absent_without_origin_header(self):
        port = self._start()
        _, _, headers = self._raw_response("GET", port, "/")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_cors_absent_for_unknown_origin(self):
        port = self._start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/",
            headers={"Origin": "http://evil.example"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_cors_allowed_for_allowlisted_origin(self):
        port = self._start(config={"allowed_origins": ["http://phone.local"]})
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/",
            headers={"Origin": "http://phone.local"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.headers.get("Access-Control-Allow-Origin"),
                             "http://phone.local")

    def test_error_body_does_not_disclose_internal_detail(self):
        def boom(text):
            raise RuntimeError("secret fixture string XYZ")

        port = self._start(on_command=boom)
        code, payload = self._request("POST", port, "/command", {"text": "hi"})
        self.assertEqual(code, 500)
        self.assertNotIn("XYZ", json.dumps(payload))

    def test_voice_error_uses_status_500_and_no_internal_detail(self):
        def boom(_path):
            raise RuntimeError("secret inner fixture XYZ")

        port = self._start(on_voice=boom)
        code, payload = self._request("POST", port, "/voice",
                                      raw_body=b"RIFF" + b"\x00" * 64)
        self.assertEqual(code, 500)
        self.assertFalse(payload.get("ok", True))
        self.assertNotIn("XYZ", json.dumps(payload))
        self.assertNotIn("boom", json.dumps(payload))

    def test_rate_limit_blocks_rapid_commands(self):
        config = {"rate_limit_per_minute": 4}
        port = self._start(
            on_command=lambda text: self._future_response("ok"),
            config=config,
        )
        codes = []
        for _ in range(8):
            code, _ = self._request("POST", port, "/command", {"text": "hi"})
            codes.append(code)
        self.assertIn(200, codes)
        self.assertIn(429, codes)

    # --------------------------------------------------
    # TD-07 / SEC-11: concurrency ceiling
    # --------------------------------------------------

    def test_max_connections_from_config(self):
        server = RemoteServer(host="127.0.0.1", port=0,
                              config={"max_connections": 7})
        self.assertEqual(server.max_connections, 7)
        self.assertEqual(RemoteServer(host="127.0.0.1", port=0)
                         .max_connections, 16, "default ceiling")

    def test_connection_ceiling_sheds_beyond_limit(self):
        release = threading.Event()
        started = threading.Event()

        def slow(text):
            started.set()
            release.wait(5)
            return self._future_response("ok")

        config = {"max_connections": 2, "rate_limit_per_minute": 10000}
        port = self._start(on_command=slow, config=config)
        httpd = self.server._server
        self.assertEqual(httpd.max_threads, 2)

        # Saturate the ceiling with concurrent slow commands.
        threads = []
        for _ in range(2):
            thread = threading.Thread(
                target=self._request, args=("POST", port, "/command"),
                kwargs={"body": {"text": "hi"}}, daemon=True,
            )
            thread.start()
            threads.append(thread)
        self.assertTrue(started.wait(5), "slow handler never started")
        self.assertEqual(self._drain(httpd, 2), 2, "ceiling never saturated")

        # A third concurrent connection is shed, not serviced.
        code, _ = self._request("POST", port, "/command", {"text": "hi"})
        self.assertEqual(code, 503)

        release.set()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(self._drain(httpd, 0), 0, "slots must be released")

    def test_request_id_is_returned_on_every_response(self):
        port = self._start(on_command=lambda text: self._future_response("ok"))
        code, _, headers = self._raw_response("GET", port, "/health")
        self.assertEqual(code, 200)
        request_id = headers.get("X-MAXIE-Request-Id")
        self.assertTrue(request_id, "every response carries a request id")
        self.assertEqual(len(request_id), 8)

    def test_request_ids_differ_between_requests(self):
        port = self._start(on_command=lambda text: self._future_response("ok"))
        seen = set()
        for _ in range(4):
            _, _, headers = self._raw_response("GET", port, "/health")
            seen.add(headers.get("X-MAXIE-Request-Id"))
        self.assertEqual(len(seen), 4)

    def test_request_id_present_on_error_responses(self):
        port = self._start(token="secret", on_command=lambda text: None)
        code, _, headers = self._raw_response("GET", port, "/health")
        self.assertEqual(code, 401)
        self.assertTrue(headers.get("X-MAXIE-Request-Id"))

    def test_accepted_command_is_audited_with_its_request_id(self):
        config = {"audit_log": True}
        port = self._start(
            on_command=lambda text: self._future_response("ok"),
            config=config,
        )
        code, _ = self._request("POST", port, "/command", {"text": "hello"})
        self.assertEqual(code, 200)
        entries = [line for line in self.logger_output()
                   if "REMOTE_AUDIT" in line]
        self.assertTrue(entries, "an accepted command must be audited")
        self.assertTrue(any('"outcome": 200' in line for line in entries))
        self.assertTrue(any("request_id" in line for line in entries))

    def test_audit_entry_redacts_the_command_text(self):
        config = {"audit_log": True}
        port = self._start(
            on_command=lambda text: self._future_response("ok"),
            config=config,
        )
        self._request("POST", port, "/command",
                      {"text": "my bank pin is 4021"})
        blob = "\n".join(self.logger_output())
        self.assertNotIn("4021", blob, "audit log must not keep the words")
        self.assertIn("REMOTE_AUDIT", blob)

    def test_rejected_command_is_audited_with_the_request_id(self):
        config = {"audit_log": True}
        port = self._start(token="s3cret", on_command=lambda text: None,
                           config=config)
        code, _, headers = self._raw_response("GET", port, "/health")
        self.assertEqual(code, 401)
        entries = [line for line in self.logger_output()
                   if "REMOTE_AUDIT" in line]
        self.assertTrue(entries)
        self.assertIn(headers["X-MAXIE-Request-Id"], "\n".join(entries))

    def test_command_callback_receives_the_caller_identity(self):
        seen = {}

        def capture(text, source=None):
            seen["source"] = source
            return self._future_response("ok")

        port = self._start(on_command=capture)
        code, _ = self._request("POST", port, "/command", {"text": "hi"})
        self.assertEqual(code, 200)
        self.assertTrue(seen["source"], "source must be passed to on_command")
        self.assertIn("127.0.0.1", seen["source"])

    def test_single_argument_callback_still_works(self):
        port = self._start(on_command=lambda text: self._future_response("ok"))
        code, payload = self._request("POST", port, "/command", {"text": "hi"})
        self.assertEqual(code, 200)
        self.assertEqual(payload["response"], "ok")

    def test_ceiling_does_not_reject_sequential_requests(self):
        config = {"max_connections": 1, "rate_limit_per_minute": 10000}
        port = self._start(
            on_command=lambda text: self._future_response("ok"),
            config=config,
        )
        for _ in range(5):
            code, _ = self._request("GET", port, "/health")
            self.assertEqual(code, 200)
            # A truly sequential client waits for its slot to drain; the
            # server releases it as the response is flushed.
            self.assertEqual(self._drain(self.server._server, 0), 0)


if __name__ == "__main__":
    unittest.main()