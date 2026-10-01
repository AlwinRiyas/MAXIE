"""Repository hygiene: nothing live or secret may be tracked (SEC-02).

SEC-02 was closed by *action* — `.gitignore` excludes `Config/*.json` and the
three live files were untracked with `git rm --cached`. That is a snapshot of
one afternoon. Nothing stopped someone later running `git add -f
Config/system_config.json`, or `git add Config/` after editing `.gitignore`.

These tests make the fix durable: they ask git directly, so they fail on the
commit that reintroduces the exposure rather than on the day it ships.

Every test here skips rather than fails when git or the repository is absent,
because the point is to guard a checkout, not to hard-require one. A test that
fails on a source tarball is a test people learn to delete.
"""

import json
import os
import re
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Config files the app creates at runtime and must never be committed.
LIVE_CONFIG_NAMES = (
    "system_config.json",
    "audio_config.json",
    "personality.json",
    "home_devices.json",
)


def _git(*args):
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _git_or_skip(testcase):
    """Return the tracked-file list, or skip if this is not a git checkout."""
    if not (PROJECT_ROOT / ".git").exists():
        testcase.skipTest("not a git checkout")
    result = _git("ls-files")
    if result.returncode != 0:
        testcase.skipTest(f"git ls-files failed: {result.stderr.strip()}")
    return set(result.stdout.split())


class TrackedConfigTest(unittest.TestCase):
    """No live config may be tracked; only code and examples."""

    @classmethod
    def setUpClass(cls):
        if not (PROJECT_ROOT / ".git").exists():
            return
        result = _git("ls-files")
        if result.returncode == 0:
            cls.tracked = set(result.stdout.split())
        else:
            cls.tracked = None

    def setUp(self):
        if self.tracked is None:
            self.skipTest("not a git checkout")

    def test_no_live_config_json_is_tracked(self):
        offenders = [
            path for path in self.tracked
            if path.startswith("Config/")
            and path.endswith(".json")
            and not path.endswith(".example.json")
        ]
        self.assertEqual(
            offenders, [],
            "a live config file is tracked; it may contain a token. "
            "Untrack it with: git rm --cached <path>",
        )

    def test_the_named_live_configs_are_all_ignored(self):
        """gitignore coverage is asserted per file, so adding a fourth live
        config without a rule fails here rather than in production."""
        for name in LIVE_CONFIG_NAMES:
            with self.subTest(config=name):
                result = _git("check-ignore", "-q", f"Config/{name}")
                self.assertEqual(
                    result.returncode, 0,
                    f"Config/{name} is not ignored; a token in it would be "
                    "committed by any `git add Config/`",
                )

    def test_examples_stay_tracked(self):
        """The negation must keep working, or the fix silently becomes
        'never commit any config'."""
        for name in ("system_config.example.json",
                     "audio_config.example.json",
                     "personality.example.json"):
            with self.subTest(example=name):
                result = _git("check-ignore", "-q", f"Config/{name}")
                self.assertNotEqual(
                    result.returncode, 0,
                    f"Config/{name} is ignored; example files must be "
                    "committed so a fresh clone can create its config",
                )

    def test_no_ignored_file_is_still_tracked(self):
        """`.gitignore` does not untrack anything.

        This caught a real one: `Memory/memory.json` was listed in
        `.gitignore` from the start and was nonetheless committed in three
        commits, carrying the user's actual facts ("gym": "6 PM", a college
        name). The ignore rule was doing nothing at all for that file, and
        reading the `.gitignore` would never have revealed it.

        The check is deliberately generic — every non-ignored-tracked file
        under the runtime-data paths — rather than a hardcoded list, so it
        keeps working when someone adds a new artifact.
        """
        offenders = {}
        for rule in ("Memory/memory.json", "Memory/todos.json",
                     "Memory/maxie_memory.db*", "Logs/screenshot.png",
                     "Config/tts_models/", "voice.wav", "barge_in.wav"):
            result = _git("ls-files", "-z", "--", rule)
            hits = [path for path in result.stdout.split("\0") if path]
            if hits:
                offenders[rule] = hits
        self.assertEqual(
            offenders, {},
            "these files are in .gitignore but still tracked, so their "
            "content is in git history: untrack with "
            "`git rm --cached <path>` and rotate anything sensitive",
        )

    def test_no_tts_model_is_tracked(self):
        """Piper voices are hundreds of MB of binary that the repo must not
        carry; they are re-downloaded by Installers/setup_tts.py."""
        offenders = [
            path for path in self.tracked
            if path.startswith("Config/tts_models/")
        ]
        self.assertEqual(offenders, [])

    def test_user_data_was_removed_from_history(self):
        """`Memory/memory.json` was tracked in three commits while an ignore
        rule for it sat in `.gitignore` the whole time. Untracking stops the
        next commit but not the last three.

        This asserts the file is untracked *now* and that no live store is
        tracked. It cannot rewrite history — that is a rewrite-and-force-push,
        which is the owner's call, not something a test should do.
        """
        result = _git("ls-files", "--", "Memory/memory.json")
        self.assertEqual(
            result.stdout.strip(), "",
            "Memory/memory.json holds user facts and must not be tracked",
        )
        # And the app must still work without it: the SQLite store is the
        # source of truth, and the legacy JSON import is best-effort.
        for name in ("Memory/maxie_memory.db", "Memory/todos.json"):
            self.assertEqual(
                _git("ls-files", "--", name).stdout.strip(), "",
                f"{name} is user data and must not be tracked",
            )

    def test_tracked_examples_hold_no_secret_looking_value(self):
        """An example is a template, not a record. A real token pasted into
        one to 'make it work' is the most likely way this leak recurs."""
        suspicious = re.compile(
            r'"(token|api_key|apikey|secret|password|bearer)"\s*:\s*'
            r'"(?!\s*")[^"]{8,}"',
            re.IGNORECASE,
        )
        for path in sorted(self.tracked):
            if not path.endswith(".json") or not path.startswith("Config/"):
                continue
            full = PROJECT_ROOT / path
            try:
                text = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                self.assertIsNone(
                    suspicious.search(line),
                    f"{path}:{number} looks like a real credential in a "
                    f"committed example: {line.strip()[:80]}",
                )

    def test_the_token_field_in_live_config_is_not_reproducible_from_git(self):
        """The specific SEC-02 claim: the remote-server token is not in
        history. Cheap version — check no committed file anywhere contains a
        plausible token literal."""
        tokenish = re.compile(
            r'"remote_token"\s*:\s*"[^"]{12,}"', re.IGNORECASE)
        for path in sorted(self.tracked):
            if not path.endswith((".json", ".py", ".md")):
                continue
            full = PROJECT_ROOT / path
            try:
                text = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if tokenish.search(line):
                    self.fail(
                        f"{path}:{number} appears to contain a real "
                        f"remote token: {line.strip()[:80]}"
                    )


class IgnoreRuleTest(unittest.TestCase):
    """The rules themselves, read as text.

    Asserting on `.gitignore` content rather than only on `git check-ignore`
    means a future edit that removes `Config/*.json` fails here with a message
    pointing at the line, instead of failing some later check-ignore test with
    no context.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    def test_live_config_is_excluded_and_examples_re_included(self):
        self.assertIn("Config/*.json", self.text)
        self.assertIn("!Config/*.example.json", self.text)
        # Order matters: the negation must come after the exclusion or git
        # applies the last matching pattern and the example is ignored.
        self.assertLess(
            self.text.index("Config/*.json"),
            self.text.index("!Config/*.example.json"),
            "the example negation must follow the exclusion",
        )

    def test_tts_models_are_excluded(self):
        self.assertIn("Config/tts_models/", self.text)

    def test_memory_and_log_artifacts_are_excluded(self):
        """Runtime state must not be committed: a committed SQLite store
        carries everything the user ever said."""
        for rule in ("Memory/", "Logs/", "*.log"):
            self.assertIn(rule, self.text, f"{rule} should be gitignored")

    def test_private_key_material_is_excluded(self):
        for rule in ("*.pem", "*.key", "id_rsa", ".env"):
            self.assertIn(rule, self.text, f"{rule} should be gitignored")


class ExampleFilesAreLoadableTest(unittest.TestCase):
    """An example that cannot be parsed is worse than no example.

    The app auto-creates a missing config from `DEFAULT_*`, so a broken example
    silently ships a surprise to anyone reading the repo for the real key names.
    """

    def test_every_example_is_valid_json(self):
        for path in sorted((PROJECT_ROOT / "Config").glob("*.example.json")):
            with self.subTest(example=path.name):
                with open(path, encoding="utf-8") as handle:
                    json.load(handle)

    def test_examples_declare_no_live_endpoint(self):
        """Examples point at placeholders, never a real hub or LAN address.
        A committed internal URL is an information leak even without a token.
        """
        for path in sorted((PROJECT_ROOT / "Config").glob("*.example.json")):
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), start=1):
                lowered = line.lower()
                for marker in ("192.168.", "10.0.", "172.16."):
                    self.assertNotIn(
                        marker, lowered,
                        f"{path.name}:{number} contains a private address; "
                        "examples must use a placeholder",
                    )


if __name__ == "__main__":
    unittest.main()