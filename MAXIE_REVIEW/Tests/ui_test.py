import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Interface.remote_server import RemoteServer  # noqa: E402


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RemoteEndpointsTest(unittest.TestCase):
    """/ui (mobile page) and /voice (WAV) endpoints."""

    def setUp(self):
        self.port = free_port()
        self.server = RemoteServer(
            port=self.port,
            on_command=lambda text: "REPLY:" + text,
            on_voice=lambda path: {"transcript": "hello app",
                                   "response": "Hi from MAXIE"},
        )
        assert self.server.start()

    def tearDown(self):
        self.server.stop()

    def request(self, path, body=None, ctype="application/json", raw=False):
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path),
            data=body,
            headers={"Content-Type": ctype},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = response.read()
            return response.status, data if raw else data.decode("utf-8")

    def test_mobile_ui_served_publicly(self):
        status, body = self.request("/ui", raw=True)
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("MAXIE", html)
        self.assertIn("Hold to talk", html)

    def test_ui_file_exists_and_is_used(self):
        path = os.path.join(PROJECT_ROOT, "Interface", "mobile_ui.html")
        self.assertTrue(os.path.exists(path))
        status, body = self.request("/ui", raw=True)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), body)

    def test_command_still_works(self):
        status, body = self.request(
            "/command", json.dumps({"text": "hi"}).encode()
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["response"], "REPLY:hi")

    def test_voice_accepts_wav(self):
        wav = b"RIFF\x00\x00\x00\x00WAVEfmt "
        status, body = self.request("/voice", wav, "audio/wav")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["transcript"], "hello app")
        self.assertEqual(payload["response"], "Hi from MAXIE")

    def test_voice_rejects_non_wav(self):
        try:
            self.request("/voice", b"nope", "audio/wav")
            self.fail("Expected HTTP 400")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 400)


class NoVoiceEndpointTest(unittest.TestCase):
    def test_missing_voice_handler_returns_501(self):
        port = free_port()
        server = RemoteServer(port=port, on_command=lambda t: t)
        assert server.start()
        try:
            wav = b"RIFF\x00\x00\x00\x00WAVEfmt "
            req = urllib.request.Request(
                "http://127.0.0.1:%d/voice" % port,
                data=wav,
                headers={"Content-Type": "audio/wav"},
            )
            try:
                urllib.request.urlopen(req, timeout=10)
                self.fail("Expected HTTP 501")
            except urllib.error.HTTPError as error:
                self.assertEqual(error.code, 501)
        finally:
            server.stop()


class UiModuleTest(unittest.TestCase):
    """GUI module imports headless; autostart helper logic."""

    @unittest.skipUnless(os.name == "posix",
                         "autostart enable/disable only on POSIX dev box")
    def test_autostart_targets_run_py(self):
        from Ui.gui import _load_autostart

        auto = _load_autostart()
        try:
            auto.disable()
            auto.enable()
            content = ""
            desktop = os.path.join(
                os.path.expanduser("~"), ".config", "autostart", "maxie.desktop"
            )
            with open(desktop, "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("run.py", content)
            self.assertIn("--gui", content)
            self.assertIn("--minimized", content)
        finally:
            auto.disable()
            self.assertIn("DISABLED", auto.status())

    def test_import_gui_is_safe(self):
        import Ui.gui  # noqa: F401

    def test_runpy_exposes_gui_flag(self):
        result = subprocess.run(
            [sys.executable, os.path.join(PROJECT_ROOT, "run.py"), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--gui", result.stdout)


if __name__ == "__main__":
    unittest.main()