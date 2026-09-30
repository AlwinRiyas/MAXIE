import hashlib
import logging
import os
import threading
import time
from logging.handlers import RotatingFileHandler

from Config.config import Config


class Logger:
    """Application logger: rotating file + console.

    Any module can access the shared instance via
    ``Logger.instance()``; all MAXIE modules may also use the module
    level ``log`` helper.
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self, level=logging.INFO):
        self.logger = logging.getLogger("MAXIE")
        self.logger.setLevel(level)

        if self.logger.handlers:
            self._restrict_logfile()
            return

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )

        logs_dir = Config.resolve("Logs")
        os.makedirs(logs_dir, exist_ok=True)

        file_handler = RotatingFileHandler(
            os.path.join(logs_dir, "maxie.log"),
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        self._restrict_logfile()

        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.setLevel(logging.WARNING)
        self.logger.addHandler(console)

    @staticmethod
    def _restrict_logfile():
        """TD-17/SEC-09 (partial): logs carry user utterances; make the
        file owner-only instead of the umask default (often 0644/0777).
        Runs after the file exists, on every construction, so pre-existing
        permissive files are tightened too."""
        try:
            os.chmod(os.path.join(Config.resolve("Logs"), "maxie.log"), 0o600)
        except OSError:
            pass

    @classmethod
    def instance(cls):
        # TD-16: double-checked lock so concurrent first-callers cannot
        # build two instances (both would re-add handlers to the same
        # stdlib logger and spew duplicate lines).
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    Config.load()
                    cls._instance = cls()
        return cls._instance

    def shutdown(self):
        """Close and flush every handler (TD-47).

        Lets the process exit cleanly and lets a new ``Logger.instance()``
        recreate a fresh handler chain after this one is retired.
        """
        for handler in list(self.logger.handlers):
            try:
                handler.flush()
                handler.close()
            finally:
                self.logger.removeHandler(handler)
        type(self)._instance = None

    @staticmethod
    def utterance(text):
        """Render a user utterance for the log (TD-17).

        Plaintext utterances are never written to disk by default: the
        log gets a character count plus a short digest, which is enough
        to correlate the same utterance across lines and to prove a leak
        in a test, without persisting the words. Set
        ``logging.log_utterances: true`` in ``Config/system_config.json``
        to opt back in to plaintext (debugging only).
        """
        text = "" if text is None else str(text)
        settings = Config.system().get("logging", {}) or {}
        if settings.get("log_utterances", False):
            return text
        digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        return f"<{len(text)} chars #{digest[:8]}>"

    @classmethod
    def sweep(cls, retention_days=None, logs_dir=None):
        """Delete rotated log files older than the retention window.

        Rotated backups (``maxie.log.1`` ...) are the bulk of what
        accumulates on disk; the live file is rotated by the handler and
        left alone. Returns the removed file names.
        """
        if retention_days is None:
            settings = Config.system().get("logging", {}) or {}
            retention_days = int(settings.get("retention_days", 7))
        retention_days = int(retention_days)
        if retention_days <= 0:
            return []
        if logs_dir is None:
            logs_dir = Config.resolve("Logs")

        cutoff = time.time() - (retention_days * 86400)
        removed = []
        try:
            names = os.listdir(logs_dir)
        except OSError:
            return removed

        for name in names:
            if not name.startswith("maxie.log."):
                continue
            path = os.path.join(logs_dir, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed.append(name)
            except OSError:
                continue
        return removed

    def info(self, message):
        self.logger.info(self._text(message))

    def warning(self, message):
        self.logger.warning(self._text(message))

    def error(self, message):
        self.logger.error(self._text(message))

    def debug(self, message):
        self.logger.debug(self._text(message))

    @staticmethod
    def _text(message):
        if isinstance(message, Exception):
            return f"{type(message).__name__}: {message}"
        return str(message)


_log = Logger.instance


def log_info(message):
    Logger.instance().info(message)


def log_warning(message):
    Logger.instance().warning(message)


def log_error(message):
    Logger.instance().error(message)