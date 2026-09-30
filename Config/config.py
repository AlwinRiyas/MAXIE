import copy
import json
import os
import shutil
import tempfile


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
        """Persist audio settings (used by installers/customization)."""
        cls.load()
        updated = cls.data["audio"]
        updated.update(kwargs)
        resolved = cls.FILES["audio"]
        cls.data["audio"] = updated
        with open(resolved, "w", encoding="utf-8") as f:
            json.dump(updated, f, indent=2, default=str)
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