import json
import os
import tempfile
import json
import unittest
from pathlib import Path

from Config.config import Config, ConfigError


class ConfigTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        Config.load(force=True)

    def test_system_defaults(self):
        system = Config.system()
        self.assertEqual(system["assistant_name"], "Maxie")
        self.assertTrue(system["wake_word_enabled"] in (True, False))
        self.assertEqual(system["remote_server"]["host"], "127.0.0.1")

    def test_audio_defaults(self):
        audio = Config.audio()
        self.assertEqual(int(audio["sample_rate"]), 16000)
        self.assertGreater(float(audio["max_seconds"]), 0)
        self.assertIn("whisper_model", audio)

    def test_personality_defaults(self):
        personality = Config.personality()
        self.assertIn("style", personality)
        self.assertIn("voice_gender", personality)

    def test_compat_attributes(self):
        self.assertEqual(Config.ASSISTANT_NAME, "Maxie")
        self.assertEqual(Config.USER_NAME, "Alwin")
        self.assertTrue(Config.VERSION)

    def test_remote_config(self):
        remote = Config.remote_config()
        self.assertIn("enabled", remote)
        self.assertIn("port", remote)

    def test_project_root_resolves(self):
        root = Config.get_project_root()
        self.assertTrue(os.path.isdir(root))


class ConfigReadNoWriteTest(unittest.TestCase):
    """TD-09: reading configuration must never write to disk."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._orig_files = dict(Config.FILES)

    def tearDown(self):
        Config.FILES = dict(self._orig_files)

    def test_read_does_not_rewrite_a_valid_file(self):
        path = os.path.join(self._dir.name, "system.json")
        original = {"assistant_name": "Rosie", "user_name": "Leslie"}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(original, f)

        Config.FILES = {
            **self._orig_files,
            "system": path,
        }
        Config.load(force=True)

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(
            json.loads(content), original,
            "a read must never re-serialize/write a user's valid config",
        )

    def test_malformed_config_is_not_silently_destroyed(self):
        path = os.path.join(self._dir.name, "system.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ this is not json ]]")

        Config.FILES = {
            **self._orig_files,
            "system": path,
        }
        Config.load(force=True)

        self.assertTrue(
            os.path.exists(path + ".bak"),
            "a backup must exist before a malformed file is touched",
        )
        with open(path + ".bak", "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "{ this is not json ]]")

    def test_missing_file_creates_defaults_once(self):
        path = os.path.join(self._dir.name, "system.json")
        Config.FILES = {
            **self._orig_files,
            "system": path,
        }
        Config.load(force=True)

        self.assertTrue(os.path.exists(path), "missing config is created")
        mtime = os.path.getmtime(path)
        Config.load(force=True)
        self.assertEqual(
            os.path.getmtime(path), mtime,
            "creating a missing file must happen once, not on every read",
        )

    def test_defaults_are_not_mutated_by_loading(self):
        Config.load(force=True)
        before = json.dumps(Config.DEFAULT_SYSTEM, sort_keys=True)
        Config.load(force=True)
        after = json.dumps(Config.DEFAULT_SYSTEM, sort_keys=True)
        self.assertEqual(
            before, after,
            "loading must never alias/mutate the class default templates",
        )


class ConfigWriteSyncTest(unittest.TestCase):
    """TD-26: set_audio must use the shared write path and re-sync the
    loaded in-memory config with disk."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._orig_files = dict(Config.FILES)
        self._orig_data = json.loads(json.dumps(Config.data))
        self.addCleanup(self._restore)
        audio_path = os.path.join(self._dir.name, "audio.json")
        with open(audio_path, "w", encoding="utf-8") as f:
            json.dump(Config.DEFAULT_AUDIO, f)
        Config.FILES = {**self._orig_files, "audio": audio_path}
        Config.load(force=True)
        self.audio_path = audio_path

    def _restore(self):
        Config.FILES = dict(self._orig_files)
        Config.data = self._orig_data

    def test_set_audio_syncs_disk_and_memory(self):
        Config.set_audio(sample_rate=48000)
        with open(self.audio_path, "r", encoding="utf-8") as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk["sample_rate"], 48000)
        self.assertEqual(
            Config.audio()["sample_rate"], 48000,
            "loaded data must not diverge from disk after a write",
        )

    def test_set_audio_preserves_unicode(self):
        Config.set_audio(device_name="Mikrofon — Super Tøff")
        with open(self.audio_path, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Mikrofon — Super Tøff", text)


class ConfigValidationTest(unittest.TestCase):
    """TD-27: every schema'd setting is coerced or rejected by name, so a
    hand-edited config never surfaces as a traceback from a subsystem."""

    @staticmethod
    def _data(**remote):
        return {
            "system": {
                "remote_server": {"port": 8778, "max_connections": 16,
                                  **remote},
                "ai": {"temperature": 0.2, "max_tokens": 150},
            },
            "personality": {"speech_rate": 0, "volume": 100},
            "audio": {"sample_rate": 16000, "vad_threshold": 0.35},
        }

    def test_valid_defaults_pass(self):
        data = self._data()
        Config.validate(data)
        self.assertEqual(data["system"]["remote_server"]["port"], 8778)

    def test_confirm_ttl_default_is_declared(self):
        # SEC-11: the confirmation window is a documented tunable, not a
        # magic number buried in the router.
        self.assertEqual(
            Config.DEFAULT_SYSTEM["remote_server"]["confirm_ttl_seconds"], 60)
        example = json.loads(
            (Path(Config.PROJECT_ROOT) / "Config"
             / "system_config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(
            example["remote_server"]["confirm_ttl_seconds"],
            Config.DEFAULT_SYSTEM["remote_server"]["confirm_ttl_seconds"])

    def test_confirm_ttl_bounds(self):
        Config.validate(self._data(confirm_ttl_seconds=30))
        with self.assertRaises(ConfigError):
            Config.validate(self._data(confirm_ttl_seconds=0))
        with self.assertRaises(ConfigError):
            Config.validate(self._data(confirm_ttl_seconds=100000))

    def test_routing_mode_defaults_to_controlled(self):
        # ROADMAP 12.1: the model must not be able to select a skill
        # unless the user asked for that autonomy.
        self.assertEqual(
            Config.DEFAULT_SYSTEM["ai"]["routing_mode"], "controlled")

    def test_routing_mode_accepts_smart(self):
        data = self._data()
        data["system"]["ai"]["routing_mode"] = "smart"
        Config.validate(data)
        self.assertEqual(data["system"]["ai"]["routing_mode"], "smart")

    def test_routing_mode_rejects_agent_without_the_opt_in(self):
        """Phase 12.2 made the planner real, but 'agent' stays illegal on
        its own: one hand-edited word must not hand the machine a chain of
        skills."""
        data = self._data()
        data["system"]["ai"]["routing_mode"] = "agent"
        with self.assertRaises(ConfigError) as caught:
            Config.validate(data)
        message = str(caught.exception)
        self.assertIn("agent_enabled", message,
                      "the error should name the opt-in that is missing")
        self.assertIn("controlled", message,
                      "the error should name the mode to stay on instead")

    def test_routing_mode_accepts_agent_with_the_opt_in(self):
        data = self._data()
        data["system"]["ai"]["routing_mode"] = "agent"
        data["system"]["ai"]["agent_enabled"] = True
        Config.validate(data)
        self.assertEqual(data["system"]["ai"]["routing_mode"], "agent")

    def test_an_odd_spelling_of_the_opt_in_is_not_truthy(self):
        """'false' as a string must not read as enabled. Anything other
        than a real bool is refused rather than guessed at."""
        data = self._data()
        data["system"]["ai"]["routing_mode"] = "agent"
        data["system"]["ai"]["agent_enabled"] = "yes please"
        with self.assertRaises(ConfigError):
            Config.validate(data)

    def test_routing_mode_typo_is_named(self):
        data = self._data()
        data["system"]["ai"]["routing_mode"] = "smrt"
        with self.assertRaises(ConfigError) as caught:
            Config.validate(data)
        self.assertIn("system.ai.routing_mode", str(caught.exception))

    def test_confirm_ttl_is_coerced_from_a_numeric_string(self):
        data = self._data(confirm_ttl_seconds="45")
        Config.validate(data)
        self.assertEqual(data["system"]["remote_server"]["confirm_ttl_seconds"],
                         45)

    def test_numeric_string_is_coerced(self):
        data = self._data()
        data["system"]["remote_server"]["port"] = "9000"
        data["system"]["ai"]["temperature"] = "0.7"
        Config.validate(data)
        self.assertEqual(data["system"]["remote_server"]["port"], 9000)
        self.assertEqual(data["system"]["ai"]["temperature"], 0.7)

    def test_bool_strings_are_coerced(self):
        data = self._data()
        data["system"]["remote_server"]["enabled"] = "true"
        data["system"]["remote_server"]["audit_log"] = "no"
        Config.validate(data)
        self.assertIs(data["system"]["remote_server"]["enabled"], True)
        self.assertIs(data["system"]["remote_server"]["audit_log"], False)

    def test_bad_port_is_rejected_with_the_setting_name(self):
        data = self._data()
        data["system"]["remote_server"]["port"] = 99999
        with self.assertRaises(ConfigError) as caught:
            Config.validate(data)
        message = str(caught.exception)
        self.assertIn("remote_server.port", message)
        self.assertIn("65535", message)

    def test_uncoercible_type_is_rejected(self):
        data = self._data()
        data["audio"]["sample_rate"] = "sixteen thousand"
        with self.assertRaises(ConfigError) as caught:
            Config.validate(data)
        self.assertIn("audio.sample_rate", str(caught.exception))

    def test_bool_is_not_accepted_as_int(self):
        data = self._data()
        data["audio"]["channels"] = True
        with self.assertRaises(ConfigError):
            Config.validate(data)

    def test_zero_port_is_rejected(self):
        data = self._data()
        data["system"]["remote_server"]["port"] = 0
        with self.assertRaises(ConfigError):
            Config.validate(data)

    def test_out_of_range_threshold_is_rejected(self):
        data = self._data()
        data["audio"]["vad_threshold"] = 5.0
        with self.assertRaises(ConfigError) as caught:
            Config.validate(data)
        self.assertIn("vad_threshold", str(caught.exception))

    def test_load_rejects_a_malformed_setting(self):
        with tempfile.TemporaryDirectory() as tmp:
            system_path = os.path.join(tmp, "system.json")
            bad = json.loads(json.dumps(Config.DEFAULT_SYSTEM))
            bad["remote_server"]["port"] = "not-a-port"
            with open(system_path, "w", encoding="utf-8") as f:
                json.dump(bad, f)

            orig_files = dict(Config.FILES)
            orig_data = json.loads(json.dumps(Config.data))
            self.addCleanup(lambda: (
                setattr(Config, "FILES", orig_files),
                setattr(Config, "data", orig_data),
            ))
            Config.FILES = {**orig_files, "system": system_path}
            with self.assertRaises(ConfigError):
                Config.load(force=True)


if __name__ == "__main__":
    unittest.main()