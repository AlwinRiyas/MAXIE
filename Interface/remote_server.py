"""HTTP endpoint that lets a phone (or any HTTP client) drive MAXIE.

Security model (see AGENTS.md):

- Binds ``127.0.0.1`` by default.
- Binding to any non-loopback address (LAN access) REQUIRES an explicit
  token in the config; otherwise construction fails closed.
- Every endpoint requires ``X-MAXIE-Token: <token>`` (or
  ``Authorization: Bearer <token>``) when a token is configured.

Standard library only (``http.server``) — no Flask/requests needed.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from Logs.logger import Logger

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", ""}
DEFAULT_TIMEOUT = 20  # seconds to wait for the conversation loop


class RemoteServer:
    """Threaded HTTP server bridging phone/CLI text -> ConversationEngine."""

    def __init__(self, host="127.0.0.1", port=8778, token="", on_command=None,
                 timeout=DEFAULT_TIMEOUT, on_voice=None):
        self.host = host or "127.0.0.1"
        self.port = int(port)
        self.token = (token or "").strip()
        self.on_command = on_command
        self.on_voice = on_voice
        self.timeout = timeout
        self.logger = Logger.instance()

        if self.host not in LOOPBACK_HOSTS and not self.token:
            # Fail closed: never expose an unauthenticated LAN service.
            raise ValueError(
                "Refusing to bind remote server to non-loopback address "
                f"'{self.host}' without a token. Set a token in "
                "system_config.json -> remote_server.token first."
            )

        self._server = None
        self._thread = None

    # ----------------------------------------------------------
    # Auth
    # ----------------------------------------------------------

    def _authorized(self, headers):
        if not self.token:
            return True

        supplied = headers.get("X-MAXIE-Token", "")
        if not supplied:
            authorization = headers.get("Authorization", "")
            if authorization.lower().startswith("bearer "):
                supplied = authorization[7:]
        return supplied.strip() == self.token

    # ----------------------------------------------------------
    # Command dispatch -> conversation loop
    # ----------------------------------------------------------

    def _dispatch(self, text):
        if not self.on_command:
            return "MAXIE is not listening for remote commands."

        try:
            future = self.on_command(text)
        except Exception as error:  # defensive: never crash the server
            self.logger.error(f"Remote command enqueue failed: {error}")
            return f"Command failed: {error}"

        if future is None:
            return ""

        # A Future-like object (conversation.submit_text contract).
        if hasattr(future, "result"):
            try:
                return future.result(timeout=self.timeout) or ""
            except Exception as error:
                self.logger.error(f"Remote command timed out/failed: {error}")
                return "MAXIE took too long to respond. Please try again."

        return str(future)

    # ----------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------

    def start(self):
        if self._server is not None:
            return True

        handler = self._build_handler()
        try:
            self._server = ThreadingHTTPServer((self.host, self.port), handler)
        except OSError as error:
            self.logger.error(f"Remote server bind failed: {error}")
            print(f"⚠️ Remote server couldn't start: {error}")
            self._server = None
            return False

        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.2},
            daemon=True, name="MAXIE-Remote",
        )
        self._thread.start()
        self.logger.info(
            f"Remote server listening on http://{self.host}:{self.port}"
        )
        return True

    def stop(self):
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception as error:
            self.logger.error(f"Remote server stop error: {error}")
        finally:
            self._server = None
            self._thread = None

    @property
    def running(self):
        return self._server is not None

    # ----------------------------------------------------------
    # Handler factory (captures this instance's auth/dispatch)
    # ----------------------------------------------------------

    def _build_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "MAXIE-Remote/1.0"

            # ---- helpers -------------------------------------------------
            def _send_json(self, code, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._send_cors()
                self.end_headers()
                self.wfile.write(body)

            def _send_text(self, code, text, content_type="text/plain; charset=utf-8"):
                body = text.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self._send_cors()
                self.end_headers()
                self.wfile.write(body)

            def _send_cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers",
                                 "Content-Type, Authorization, X-MAXIE-Token")
                self.send_header("Access-Control-Allow-Methods",
                                 "GET, POST, OPTIONS")

            def _check_auth(self):
                if outer._authorized(self.headers):
                    return True
                self._send_json(401, {"ok": False, "error": "Invalid or missing token."})
                return False

            def log_message(self, fmt, *args):  # route to MAXIE logger
                outer.logger.debug("Remote: " + (fmt % args))

            # ---- HTTP verbs ---------------------------------------------
            def do_OPTIONS(self):
                self.send_response(204)
                self._send_cors()
                self.end_headers()

            def do_GET(self):
                if self.path == "/ui":
                    # Page shell is public; every command it sends still
                    # carries the token header and is checked there.
                    self._send_text(200, outer._load_ui_html(), "text/html; charset=utf-8")
                    return

                if not self._check_auth():
                    return

                if self.path in ("/", "/index"):
                    self._send_json(200, {
                        "assistant": "MAXIE",
                        "endpoints": {
                            "GET /health": "liveness check",
                            "GET /ui": "mobile voice UI (open in a phone browser)",
                            "POST /command": '{"text": "what time is it"}',
                            "POST /voice": "audio/wav body -> transcript + reply",
                        },
                    })
                    return

                if self.path == "/health":
                    self._send_json(200, {
                        "status": "ok",
                        "running": outer.running,
                    })
                    return

                self._send_json(404, {"ok": False, "error": "Not found."})

            def do_POST(self):
                if not self._check_auth():
                    return

                if self.path == "/command":
                    self._handle_command()
                    return

                if self.path == "/voice":
                    self._handle_voice()
                    return

                self._send_json(404, {"ok": False, "error": "Not found."})

            # ---- /command ------------------------------------------------
            def _handle_command(self):

                try:
                    length = int(self.headers.get("Content-Length", 0) or 0)
                except ValueError:
                    length = 0

                raw = self.rfile.read(length) if length > 0 else b""
                text = ""
                if raw:
                    try:
                        data = json.loads(raw.decode("utf-8"))
                        if isinstance(data, dict):
                            text = str(data.get("text", ""))
                        elif isinstance(data, str):
                            text = data
                    except ValueError:
                        text = raw.decode("utf-8", "ignore")

                text = text.strip()
                if not text:
                    self._send_json(400, {"ok": False, "error": "Empty command."})
                    return

                response = outer._dispatch(text)
                self._send_json(200, {"ok": True, "response": response})

            # ---- /voice (phone sends a WAV) -----------------------------
            def _handle_voice(self):
                if not outer.on_voice:
                    self._send_json(501, {
                        "ok": False,
                        "error": "Voice endpoint not configured.",
                    })
                    return

                try:
                    length = int(self.headers.get("Content-Length", 0) or 0)
                except ValueError:
                    length = 0
                if length <= 0:
                    self._send_json(400, {"ok": False, "error": "Empty audio."})
                    return

                audio = self.rfile.read(length)
                if not audio.startswith(b"RIFF"):
                    self._send_json(400, {
                        "ok": False,
                        "error": "Expected a WAV (RIFF) payload.",
                    })
                    return

                import os
                import tempfile

                result = {"error": "Voice processing failed."}
                handle = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".wav", prefix="maxie_voice_"
                )
                try:
                    handle.write(audio)
                    handle.close()
                    result = outer.on_voice(handle.name)
                except Exception as error:
                    outer.logger.error(f"Voice dispatch failed: {error}")
                    result = {"error": str(error)}
                finally:
                    try:
                        os.unlink(handle.name)
                    except OSError:
                        pass

                if isinstance(result, dict):
                    payload = {"ok": True, **result}
                else:
                    payload = {"ok": True, "response": str(result or "")}
                self._send_json(200, payload)

        return Handler

    # ----------------------------------------------------------
    # Mobile UI asset
    # ----------------------------------------------------------

    _ui_cache = None

    def _load_ui_html(self):
        if RemoteServer._ui_cache:
            return RemoteServer._ui_cache
        import os

        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "mobile_ui.html")
        try:
            with open(path, "r", encoding="utf-8") as f:
                RemoteServer._ui_cache = f.read()
        except OSError:
            RemoteServer._ui_cache = "<h1>MAXIE</h1><p>UI file missing.</p>"
        return RemoteServer._ui_cache
