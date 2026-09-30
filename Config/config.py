import copy
import json
import os
import shutil
import tempfile


class ConfigError(Exception):
    """Raised when configuration cannot be coerced into a usable state.

    Surfaces as a friendly message in ``run.py`` instead of a traceback
    from deep inside a subsystem (TD-27).
    """


class Config:
    """Central configuration for MAXIE.

    Loads JSON files from the Config directory and creates them with
    defaults when they are missing. All paths are derived from the
    project root so MAXIE works from any working directory on both
    Windows and Linux.

    Backward-compatible class attributes (ASSISTANT_NAME, USER_NAME,
    ...) are kept so older code still works.
    """

    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    CONFIG_DIR = os.path.join(PROJECT_ROOT, "Config")

    DEFAULT_SYSTEM = {
        "assistant_name": "Maxie",
        "user_name": "Alwin",
        "language": "en",
        "version": "1.3.0",
        "wake_word_enabled": False,
        "wake_word": "hey maxie",
        "auto_listen": True,
        "ai": {
            "provider": "ollama",
            "url": "http://127.0.0.1:11434",
            "model": "llama3.2:3b",
            "temperature": 0.2,
            "max_tokens": 150,
            "num_ctx": 2048,
            "context_turns": 6,
            "retries": 2,
            "retry_delay_seconds": 1.0,
            "availability_ttl_seconds": 10.0,
            "max_context_chars": 6000,
            "max_context_row_chars": 2000,
            "auto_learn_session_cap": 30,
        },
        "memory": {
            "conversation_cap": 500,
        },
        "weather": {
            "city": "Chennai",
            "latitude": None,
            "longitude": None,
        },
        "remote_server": {
            "enabled": False,
            "host": "127.0.0.1",
            "port": 8778,
            "token": "",
            "max_voice_bytes": 10485760,
            "max_command_bytes": 65536,
            "allowed_origins": [],
            "rate_limit_per_minute": 60,
            "max_connections": 16,
            "audit_log": False,
        },
        "allow_local_power_control": False,
    }

    DEFAULT_PERSONALITY = {
        "style": "FRIDAY",
        "voice_gender": "female",
        "speech_rate": 0,
        "volume": 100,
        "response_length": "short",
    }

    DEFAULT_AUDIO = {
        "sample_rate": 16000,
        "channels": 1,
        "block_size": 512,
        "vad_threshold": 0.35,
        "min_speech_ms": 150,
        "min_silence_ms": 500,
        "max_seconds": 12,
        "pre_roll_ms": 220,
        "speech_wait_timeout": 20,
        "microphone_index": None,
        "preferred_microphone_keywords": ["microphone array"],
        "whisper_model": "base.en",
        "whisper_device": "cpu",
        "whisper_compute_type": "int8",
        "whisper_language": "en",
        "whisper_retry_seconds": 60,  # backoff before retrying a failed load
        "silero_retry_seconds": 60,   # backoff before retrying a failed load
        "tts_engine": "auto",  # auto | piper | edge | sapi | pyttsx | espeak
        "piper_voice": "en_US-lessac-medium",  # offline neural model name
        "edge_voice": "en-US-JennyNeural",     # online Microsoft voice
        "tts_synth_timeout": 60,  # hard limit on synthesis, seconds
        "echo_cooldown_seconds": 0.45,
"weak_speech_gain": 4.0,
        "weak_rms_threshold": 0.005,
        "barge_in_rms_threshold": 0.003,
        "vad_noise_ratio": 1.8,
    }

    FILES = {
        "system": os.path.join(CONFIG_DIR, "system_config.json"),
        "personality": os.path.join(CONFIG_DIR, "personality.json"),
        "audio": os.path.join(CONFIG_DIR, "audio_config.json"),
    }

    # ----------------------------------------------------------
    # Schema (TD-27)
    #
    # Every tunable that a hand-edit can plausibly break, as
    # (path, python type, lower bound, upper bound). Values outside the
    # bound are a hard error; values of the wrong type are coerced when
    # that is unambiguous (e.g. "8778" -> 8778) and rejected otherwise.
    # ----------------------------------------------------------

    SCHEMA = {
        # system
        ("system", "wake_word_enabled"): (bool, None, None),
        ("system", "auto_listen"): (bool, None, None),
        ("system", "allow_local_power_control"): (bool, None, None),
        # system.ai
        ("system", "ai", "temperature"): (float, 0.0, 2.0),
        ("system", "ai", "max_tokens"): (int, 16, 32768),
        ("system", "ai", "num_ctx"): (int, 256, 262144),
        ("system", "ai", "context_turns"): (int, 0, 100),
        ("system", "ai", "retries"): (int, 0, 10),
        ("system", "ai", "retry_delay_seconds"): (float, 0.0, 60.0),
        ("system", "ai", "availability_ttl_seconds"): (float, 0.0, 600.0),
        ("system", "ai", "max_context_chars"): (int, 256, 200000),
        ("system", "ai", "max_context_row_chars"): (int, 64, 200000),
        ("system", "ai", "auto_learn_session_cap"): (int, 0, 10000),
        # system.memory
        ("system", "memory", "conversation_cap"): (int, 0, 100000),
        # system.remote_server
        ("system", "remote_server", "enabled"): (bool, None, None),
        ("system", "remote_server", "port"): (int, 1, 65535),
        ("system", "remote_server", "max_voice_bytes"): (int, 1024, 1 << 30),
        ("system", "remote_server", "max_command_bytes"): (int, 16, 1 << 24),
        ("system", "remote_server", "rate_limit_per_minute"): (
            int, 1, 100000),
        ("system", "remote_server", "max_connections"): (int, 1, 1024),
        ("system", "remote_server", "audit_log"): (bool, None, None),
        # personality
        ("personality", "speech_rate"): (int, -10, 10),
        ("personality", "volume"): (int, 0, 100),
        # audio
        ("audio", "sample_rate"): (int, 8000, 192000),
        ("audio", "channels"): (int, 1, 2),
        ("audio", "block_size"): (int, 64, 8192),
        ("audio", "vad_threshold"): (float, 0.0, 1.0),
        ("audio", "min_speech_ms"): (int, 0, 60000),
        ("audio", "min_silence_ms"): (int, 0, 60000),
        ("audio", "max_seconds"): (int, 1, 3600),
        ("audio", "pre_roll_ms"): (int, 0, 5000),
        ("audio", "speech_wait_timeout"): (int, 1, 600),
        ("audio", "vad_noise_ratio"): (float, 0.1, 20.0),
        ("audio", "weak_rms_threshold"): (float, 0.0, 1.0),
        ("audio", "barge_in_rms_threshold"): (float, 0.0, 1.0),
        ("audio", "echo_cooldown_seconds"): (float, 0.0, 10.0),
    }

    # ----------------------------------------------------------
    # Loaded data and backward-compatible attributes
    # ----------------------------------------------------------

    data = {}
    ASSISTANT_NAME = "Maxie"
    USER_NAME = "Alwin"
    LANGUAGE = "en"
    VERSION = "1.3.0"
    VOICE_RATE = 0
    GREETING_STYLE = "FRIDAY"
    WAKE_WORD = "hey maxie"

    LOGGER = None

    # ----------------------------------------------------------
    # Load / persist
    # ----------------------------------------------------------

    @classmethod
    def load(cls, force=False):
        if cls.data and not force:
            return cls.data

        os.makedirs(cls.CONFIG_DIR, exist_ok=True)

        cls.data = {
            "system": cls._load_file(
                cls.FILES["system"], cls.DEFAULT_SYSTEM
            ),
            "personality": cls._load_file(
                cls.FILES["personality"], cls.DEFAULT_PERSONALITY
            ),
            "audio": cls._load_file(
                cls.FILES["audio"], cls.DEFAULT_AUDIO
            ),
        }

        cls.validate()

        # Sync backward-compatible attributes.
        sys = cls.data["system"]
        person = cls.data["personality"]

        cls.ASSISTANT_NAME = sys.get("assistant_name", "Maxie")
        cls.USER_NAME = sys.get("user_name", "Alwin")
        cls.LANGUAGE = sys.get("language", "en")
        cls.VERSION = sys.get("version", "1.3.0")
        cls.GREETING_STYLE = person.get("style", "FRIDAY")
        cls.VOICE_RATE = person.get("speech_rate", 0)
        cls.WAKE_WORD = sys.get("wake_word", "hey maxie").lower()

        return cls.data

    # ----------------------------------------------------------
    # Schema validation (TD-27)
    # ----------------------------------------------------------

    @classmethod
    def validate(cls, data=None):
        """Coerce and range-check every :attr:`SCHEMA` entry.

        Wrong-type values are coerced when the intent is unambiguous
        (``"8778"`` -> ``8778``, ``"0.5"`` -> ``0.5``, ``"true"`` ->
        ``True``); anything that cannot be coerced, or that falls
        outside the declared bounds, raises :class:`ConfigError` with a
        message naming the exact setting. Callers (``run.py``) turn that
        into a friendly one-liner instead of a traceback.

        Returns the validated data. Never raises for a value that is
        absent — defaults have already been merged in by then.
        """
        if data is None:
            data = cls.data
        if not data:
            return data

        for path, (wanted, low, high) in cls.SCHEMA.items():
            node = data
            for key in path[:-1]:
                node = node.get(key) if isinstance(node, dict) else None
                if node is None:
                    break
            if not isinstance(node, dict) or path[-1] not in node:
                continue

            raw = node[path[-1]]
            value = cls._coerce(raw, wanted)
            if value is None:
                raise ConfigError(
                    f"Config setting {'.'.join(path)} must be "
                    f"{wanted.__name__}, got {raw!r}."
                )
            if low is not None and not (low <= value <= high):
                raise ConfigError(
                    f"Config setting {'.'.join(path)} must be between "
                    f"{low} and {high}, got {value!r}."
                )
            node[path[-1]] = value

        return data

    @staticmethod
    def _coerce(value, wanted):
        if wanted is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in ("true", "yes", "1", "on"):
                    return True
                if lowered in ("false", "no", "0", "off"):
                    return False
            if isinstance(value, (int, float)) and value in (0, 1):
                return bool(value)
            return None

        # bool is a subclass of int; never let True become 1 here.
        if isinstance(value, bool):
            return None

        if wanted is int:
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, str):
                try:
                    return int(value.strip())
                except ValueError:
                    return None
            return None

        if wanted is float:
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value.strip())
                except ValueError:
                    return None
            return None

        if isinstance(value, wanted):
            return value
        return None

    @classmethod
    def _load_file(cls, path, defaults):
        # TD-09: reading configuration must never write to disk. The only
        # write path is "file does not exist" (create once with defaults).
        # A parse failure is backed up and logged, never silently wiped.
        defaults = copy.deepcopy(defaults)

        if not os.path.exists(path):
            cls._save_file(path, defaults)
            return defaults

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            try:
                backup = path + ".bak"
                shutil.copy2(path, backup)
            except Exception:
                pass
            try:
                import sys

                print(
                    f"[Config] WARNING: {path} is malformed; backed up to "
                    f"{path}.bak and defaults restored.",
                    file=sys.stderr,
                )
            except Exception:
                pass
            cls._save_file(path, defaults)
            return defaults

        if not isinstance(data, dict):
            data = {}

        return cls._deep_merge(defaults, data)

    @classmethod
    def _save_file(cls, path, data):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    @staticmethod
    def _deep_merge(base, override):
        base = dict(base)
        for key, value in (override or {}).items():
            if (
                key in base
                and isinstance(base[key], dict)
                and isinstance(value, dict)
            ):
                base[key] = Config._deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    @classmethod
    def save(cls):
        """Persist current loaded config back to disk."""
        if not cls.data:
            return
        cls.load()
        cls._save_file(cls.FILES["system"], cls.data["system"])
        cls._save_file(cls.FILES["personality"], cls.data["personality"])
        cls._save_file(cls.FILES["audio"], cls.data["audio"])

    @classmethod
    def set(cls, section, key, value):
        """Set a config value (section: system|personality|audio)."""
        cls.load()
        if section not in cls.data:
            return
        cls.data[section][key] = value
        cls._save_file(cls.FILES[section], cls.data[section])
        cls.load(force=True)

    # ----------------------------------------------------------
    # Accessors
    # ----------------------------------------------------------

    @classmethod
    def get(cls, section, key, default=None):
        cls.load()
        table = cls.data.get(section, {})
        if isinstance(table, dict) and key in table:
            return table[key]
        return default

    @classmethod
    def audio(cls):
        cls.load()
        return cls.data["audio"]

    @classmethod
    def set_audio(cls, **kwargs):
        """Persist audio settings (used by installers/customization).

        TD-26: uses the same ``_save_file`` write path as ``set`` and, like
        ``set``, reloads from disk afterwards so ``cls.data`` and the file
        never diverge.
        """
        cls.load()
        updated = dict(cls.data["audio"])
        updated.update(kwargs)
        cls.data["audio"] = updated
        cls._save_file(cls.FILES["audio"], updated)
        cls.load(force=True)
        return updated

    @classmethod
    def system(cls):
        cls.load()
        return cls.data["system"]

    @classmethod
    def personality(cls):
        cls.load()
        return cls.data["personality"]

    @classmethod
    def ai_config(cls):
        cls.load()
        sys = cls.data["system"]
        return sys.get("ai", dict(cls.DEFAULT_SYSTEM["ai"]))

    @classmethod
    def memory_config(cls):
        cls.load()
        sys = cls.data["system"]
        return sys.get("memory", dict(cls.DEFAULT_SYSTEM["memory"]))

    @classmethod
    def remote_config(cls):
        cls.load()
        sys = cls.data["system"]
        return sys.get("remote_server", dict(cls.DEFAULT_SYSTEM["remote_server"]))

    @classmethod
    def get_project_root(cls):
        return cls.PROJECT_ROOT

    @classmethod
    def resolve(cls, relative):
        """Resolve a project-relative path against the project root."""
        if os.path.isabs(relative):
            return relative
        return os.path.join(cls.PROJECT_ROOT, relative)

    @classmethod
    def temp_path(cls, name):
        """Scratch file in the system temp dir (per-user)."""
        directory = os.path.join(
            tempfile.gettempdir(), "maxie_" + cls._safe_user()
        )
        os.makedirs(directory, exist_ok=True)
        return os.path.join(directory, name)

    @staticmethod
    def _safe_user():
        import getpass

        try:
            user = getpass.getuser()
        except Exception:
            user = "user"
        return "".join(c for c in user if c.isalnum() or c in "_-")[:24]

    @classmethod
    def which(cls, program):
        """shutil.which wrapper (cross-platform PATH lookup)."""
        return shutil.which(program)


Config.load()