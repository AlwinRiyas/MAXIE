import logging
import os
from logging.handlers import RotatingFileHandler

from Config.config import Config


class Logger:
    """Application logger: rotating file + console.

    Any module can access the shared instance via
    ``Logger.instance()``; all MAXIE modules may also use the module
    level ``log`` helper.
    """

    _instance = None

    def __init__(self, level=logging.INFO):
        self.logger = logging.getLogger("MAXIE")
        self.logger.setLevel(level)

        if self.logger.handlers:
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

        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.setLevel(logging.WARNING)
        self.logger.addHandler(console)

    @classmethod
    def instance(cls):
        if cls._instance is None:
            Config.load()
            cls._instance = cls()
        return cls._instance

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