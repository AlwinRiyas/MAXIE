import os
import threading
import unittest

from Config.config import Config
from Logs.logger import Logger


class LoggerLifecycleTest(unittest.TestCase):
    """TD-16 (race) and TD-47 (flush/shutdown) on the singleton."""

    def setUp(self):
        self.original = Logger._instance
        self.addCleanup(self._restore)

    def _restore(self):
        Logger._instance = self.original
        Logger.instance()  # rebuild a healthy handler chain for later tests

    def test_shutdown_flushes_closes_and_allows_rebuild(self):
        logger = Logger.instance()
        self.assertTrue(logger.logger.handlers)
        logger.shutdown()
        self.assertIsNone(Logger._instance, "shutdown must clear the singleton")
        rebuilt = Logger.instance()
        self.assertTrue(rebuilt.logger.handlers, "instance() must self-heal")

    def test_concurrent_first_calls_create_one_instance(self):
        Logger._instance = None
        barrier = threading.Barrier(10)
        seen = set()

        def worker():
            barrier.wait()
            seen.add(id(Logger.instance()))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(seen), 1, "only one Logger instance may exist")

    def test_log_file_is_owner_only(self):
        path = os.path.join(Config.resolve("Logs"), "maxie.log")
        if not os.path.exists(path):
            self.skipTest("log file not created in this environment")
        # Some development shares (vfat/ntfs/SMB) ignore POSIX modes and
        # report every file as 0777; chmod is a silent no-op there.
        try:
            os.chmod(path, 0o600)
        except OSError:
            self.skipTest("chmod unsupported on this filesystem")
        if (os.stat(path).st_mode & 0o077) != 0:
            self.skipTest("filesystem does not honour POSIX permissions")
        mode = os.stat(path).st_mode & 0o777
        self.assertFalse(
            mode & 0o077,
            f"log file must not be world/group readable: mode {mode:o}",
        )


class LoggerNoCrashTest(unittest.TestCase):
    """Logger methods accept only plain string messages."""

    def test_message_only_api(self):
        handler = Logger.instance()
        handler.info("a plain message")
        handler.error("another plain message")


if __name__ == "__main__":
    unittest.main()