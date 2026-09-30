"""HTTP endpoint that lets a phone (or any HTTP client) drive MAXIE.

Security model (see AGENTS.md):

- Binds ``127.0.0.1`` by default.
- Binding to any non-loopback address (LAN access) REQUIRES an explicit
  token in the config; otherwise construction fails closed.
- Every endpoint requires ``X-MAXIE-Token: <token>`` (or
  ``Authorization: Bearer <token>``) when a token is configured.
- Request bodies are size-capped before they are read (``max_voice_bytes``
  for ``/voice``, ``max_command_bytes`` for ``/command``).
- CORS is deny-by-default: ``Access-Control-Allow-Origin`` is emitted only
  for origins explicitly allowlisted in ``remote_server.allowed_origins``.
- Token comparison is constant-time (``hmac.compare_digest``).
- Remote commands are rate-limited per client and, when enabled, appended
  to an audit log.

Standard library only (``http.server``) — no Flask/requests needed.
"""

import hmac
import json
import os
import tempfile
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from Logs.logger import Logger

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_TIMEOUT = 20  # seconds to wait for the conversation loop


class _TokenBucket:
    """Minimal rate limiter: ``capacity`` tokens, refilled at ``rate``/second."""

    def __init__(self, capacity, rate):
        self.capacity = float(capacity)
        self.rate = float(rate)
        self._tokens = self.capacity
        self._updated = time.monotonic()

    def try_take(self):
        now = time.monotonic()
        elapsed = now - self._updated
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._updated = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class _BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with a hard ceiling on live request threads.

    The per-IP token bucket bounds *request rate*, not concurrent
    connections, so a client that opens many sockets at once would still
    grow the thread pool without bound (TD-07 / SEC-11). This subclass
    caps concurrent request threads: past the ceiling, new sockets are
    closed immediately instead of being serviced. Rate limiting is the
    first line; this is the backstop for a burst.
    """

    daemon_threads = True
    allow_reuse_address = True
    # Small accept backlog so a connection flood cannot park forever in
    # the kernel queue either.
    request_queue_size = 16

    def __init__(self, server_address, handler_class, max_threads=16):
        super().__init__(server_address, handler_class)
        self.max_threads = max(1, int(max_threads))
        self._active = 0
        self._counted = set()
        self._active_lock = threading.Lock()

    def process_request(self, request, client_address):
        with self._active_lock:
            if self._active >= self.max_threads:
                self._shed(request)
                return
            self._active += 1
            self._counted.add(request)
        try:
            super().process_request(request, client_address)
        except Exception:
            self._release(request)
            self._shed(request)
            raise

    def shutdown_request(self, request):
        # The stdlib calls this immediately after the response has been
        # written, which is the tightest point at which the slot can come
        # back. Note the ceiling therefore counts connections whose
        # response is still being flushed: a client that re-connects in
        # the same microsecond its last byte lands can briefly exceed
        # max_threads. That is why the default ceiling is 16 rather
        # than something tight.
        try:
            super().shutdown_request(request)
        finally:
            self._release(request)

    def _release(self, request):
        with self._active_lock:
            if request in self._counted:
                self._counted.discard(request)
                self._active -= 1

    def _shed(self, request):
        try:
            request.sendall(
                b"HTTP/1.1 503 Service Unavailable\r\n"
                b"Content-Length: 0\r\n"
                b"Connection: close\r\n\r\n"
            )
        except OSError:
            pass
        try:
            super().shutdown_request(request)
        except OSError:
            pass

    @property
    def active_threads(self):
        with self._active_lock:
            return self._active


class RemoteServer:
    """Threaded HTTP server bridging phone/CLI text -> ConversationEngine."""

    def __init__(self, host="127.0.0.1", port=8778, token="", on_command=None,
                 timeout=DEFAULT_TIMEOUT, on_voice=None, config=None):
        self.host = host or "127.0.0.1"
        self.port = int(port)
        self.token = (token or "").strip()
        self.on_command = on_command
        self.on_voice = on_voice
        self.timeout = timeout
        self.logger = Logger.instance()

        self._config = config or {}
        self.max_voice_bytes = int(
            self._config.get("max_voice_bytes", 10 * 1024 * 1024)
        )
        self.max_command_bytes = int(
            self._config.get("max_command_bytes", 64 * 1024)
        )
        self.allowed_origins = {
            str(o).rstrip("/") for o in self._config.get("allowed_origins", [])
        }
        self.max_connections = max(
            1, int(self._config.get("max_connections", 16))
        )
        self.audit_log = bool(self._config.get("audit_log", False))

        if self.host not in LOOPBACK_HOSTS and not self.token:
            # Fail closed: never expose an unauthenticated LAN service.
            raise ValueError(
                "Refusing to bind remote server to non-loopback address "
                f"'{self.host}' without a token. Set a token in "
                "system_config.json -> remote_server.token first."
            )

        self._server = None
        self._thread = None
        self._lock = threading.Lock()
        self._buckets = {}
        self._buckets_lock = threading.Lock()
        rate = float(self._config.get("rate_limit_per_minute", 60))
        self._bucket_capacity = max(1.0, rate)
        self._bucket_rate = max(0.0, rate) / 60.0

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
        supplied = supplied.strip()
        if not supplied:
            return False
        return hmac.compare_digest(supplied.encode("utf-8"),
                                   self.token.encode("utf-8"))

    def _bucket_for(self, client_address):
        with self._buckets_lock:
            bucket = self._buckets.get(client_address)
            if bucket is None:
                bucket = _TokenBucket(self._bucket_capacity, self._bucket_rate)
                self._buckets[client_address] = bucket
            return bucket

    def _audit(self, client_address, method, path, outcome):
        if not self.audit_log:
            return
        try:
            entry = json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "client": client_address,
                "method": method,
                "path": path,
                "outcome": outcome,
            })
            self.logger.info("REMOTE_AUDIT " + entry)
        except Exception:  # noqa: BLE001 - audit must never break the request
            pass

    # ----------------------------------------------------------
    # Command dispatch -> conversation loop
    # ----------------------------------------------------------

    def _dispatch(self, text):
        """Returns a (status_code, payload) pair, never raises."""
        if not self.on_command:
            return 503, {
                "ok": False, "error": "MAXIE is not listening for remote commands."
            }

        try:
            future = self.on_command(text)
        except Exception:  # defensive: never crash the server
            self.logger.error("Remote command enqueue failed")
            return 500, {"ok": False, "error": "Command could not be started."}

        if future is None:
            return 200, {"ok": True, "response": ""}

        # A Future-like object (conversation.submit_text contract).
        if hasattr(future, "result"):
            try:
                return 200, {"ok": True, "response": future.result(
                    timeout=self.timeout) or ""}
            except Exception as error:
                self.logger.error(f"Remote command failed/timed out: {error}")
                return 200, {
                    "ok": True,
                    "response": "MAXIE took too long to respond. Please try again.",
                }

        return 200, {"ok": True, "response": str(future)}

    # ----------------------------------------------------------
    # Lifecycle (thread-safe; TD-24)
    # ----------------------------------------------------------

    def start(self):
        with self._lock:
            if self._server is not None:
                return True

            handler = self._build_handler()
            try:
                self._server = _BoundedThreadingHTTPServer(
                    (self.host, self.port), handler,
                    max_threads=self.max_connections,
                )
            except OSError as error:
                self.logger.error(f"Remote server bind failed: {error}")
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
        with self._lock:
            server, thread = self._server, self._thread
            self._server = None
            self._thread = None
        if server is None:
            return
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            self.logger.error("Remote server stop error")
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    @property
    def running(self):
        return self._server is not None

    # ----------------------------------------------------------
    # Handler factory (captures this instance's auth/dispatch)
    # ----------------------------------------------------------

    def _build_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "MAXIE-Remote/2.0"
            protocol_version = "HTTP/1.1"

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

            def _origin_allowed(self):
                origin = self.headers.get("Origin")
                if not origin:
                    return True  # no cross-origin intent
                return origin.rstrip("/") in outer.allowed_origins

            def _send_cors(self):
                if self._origin_allowed():
                    origin = self.headers.get("Origin")
                    if origin:
                        self.send_header("Access-Control-Allow-Origin", origin)
                        self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Headers",
                                 "Content-Type, Authorization, X-MAXIE-Token")
                self.send_header("Access-Control-Allow-Methods",
                                 "GET, POST, OPTIONS")

            def _check_auth(self):
                if outer._authorized(self.headers):
                    return True
                outer._audit(self.client_address[0], self.command, self.path, 401)
                self._send_json(401, {"ok": False, "error": "Invalid or missing token."})
                return False

            def _too_large(self, cap):
                length = self.headers.get("Content-Length", "0")
                try:
                    actual = int(length)
                except ValueError:
                    actual = 0
                if actual < 0 or actual > cap:
                    outer._audit(self.client_address[0], self.command, self.path, 413)
                    self._send_json(413, {
                        "ok": False,
                        "error": f"Request body exceeds the {cap}-byte limit.",
                    })
                    return True
                return False

            def _read_capped(self, cap):
                # Read at most `cap` bytes total; a lying Content-Length is
                # re-read incrementally so it cannot stream forever.
                length = int(self.headers.get("Content-Length", 0) or 0)
                remaining = min(length, cap)
                chunks = []
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 16384))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                return b"".join(chunks)

            def log_message(self, fmt, *args):  # route to MAXIE logger
                outer.logger.debug("Remote: " + (fmt % args))

            # ---- HTTP verbs ---------------------------------------------
            def do_OPTIONS(self):
                self.send_response(204)
                self._send_cors()
                self.end_headers()

            def do_GET(self):
                if self.path == "/ui":
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

                bucket = outer._bucket_for(self.client_address[0])
                if not bucket.try_take():
                    outer._audit(self.client_address[0], self.command, self.path, 429)
                    self._send_json(429, {
                        "ok": False,
                        "error": "Too many requests. Please wait and try again.",
                    })
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
                if self._too_large(outer.max_command_bytes):
                    return

                raw = self._read_capped(outer.max_command_bytes)
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
                    outer._audit(self.client_address[0], self.command, self.path, 400)
                    self._send_json(400, {"ok": False, "error": "Empty command."})
                    return

                code, payload = outer._dispatch(text)
                payload.setdefault("ok", code < 400)
                self._send_json(code, payload)

            # ---- /voice (phone sends a WAV) -----------------------------
            def _handle_voice(self):
                if not outer.on_voice:
                    self._send_json(501, {
                        "ok": False,
                        "error": "Voice endpoint not configured.",
                    })
                    return

                if self._too_large(outer.max_voice_bytes):
                    return

                audio = self._read_capped(outer.max_voice_bytes)
                if not audio.startswith(b"RIFF"):
                    outer._audit(self.client_address[0], self.command, self.path, 400)
                    self._send_json(400, {
                        "ok": False,
                        "error": "Expected a WAV (RIFF) payload.",
                    })
                    return

                result = {"error": "Voice processing failed."}
                handle = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".wav", prefix="maxie_voice_"
                )
                try:
                    handle.write(audio)
                    handle.close()
                    result = outer.on_voice(handle.name)
                except Exception:
                    outer.logger.error("Voice dispatch failed")
                    result = {"error": "Voice processing failed."}
                finally:
                    try:
                        os.unlink(handle.name)
                    except OSError:
                        pass

                if isinstance(result, dict) and result.get("error"):
                    outer._audit(self.client_address[0], self.command, self.path, 500)
                    self._send_json(500, {"ok": False, **result})
                elif isinstance(result, dict):
                    payload = {"ok": True, **result}
                    self._send_json(200, payload)
                else:
                    self._send_json(200, {"ok": True, "response": str(result or "")})

        return Handler

    # ----------------------------------------------------------
    # Mobile UI asset
    # ----------------------------------------------------------

    _ui_cache = None

    def _load_ui_html(self):
        if RemoteServer._ui_cache:
            return RemoteServer._ui_cache
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "mobile_ui.html")
        try:
            with open(path, "r", encoding="utf-8") as f:
                RemoteServer._ui_cache = f.read()
        except OSError:
            RemoteServer._ui_cache = "<h1>MAXIE</h1><p>UI file missing.</p>"
        return RemoteServer._ui_cache