"""Setup MAXIE's TTS voice.

Fixes the "robotic" voice: installs a neural text-to-speech engine and
switches MAXIE to it.

Usage:
    python Installers/setup_tts.py                      # piper (offline, recommended)
    python Installers/setup_tts.py --engine edge        # Microsoft neural (online)
    python Installers/setup_tts.py --engine espeak      # revert to CLI fallback
    python Installers/setup_tts.py --test               # synthesize a sample line

Piper = fully offline neural voices (great clarity, female voice by
default). Edge = Microsoft Edge neural voices (even more natural, but
needs internet the first time and for every utterance).
"""

import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Config.config import Config  # noqa: E402

PIPER_BASE = ("https://huggingface.co/rhasspy/piper-voices/resolve/"
              "v1.0.0/{iso}/{lang}/{speaker}/{quality}/{voice}")


def pip_install(package):
    """pip install, falling back to pipx on externally-managed (PEP 668)
    systems where `pip` refuses to touch the system environment."""
    print(f"Installing {package}…")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", package]
        )
        return
    except subprocess.CalledProcessError:
        pass

    pipx = subprocess.run(
        ["pipx", "--version"], capture_output=True, text=True
    )
    if pipx.returncode == 0:
        print(f"System pip is managed by the OS — using pipx for {package}…")
        subprocess.check_call(["pipx", "install", "--force", package])
        return

    raise SystemExit(
        "Could not install the TTS package. Either use a virtual "
        "environment, `pipx`, or add `--break-system-packages`."
    )


def download(url, dest, tries=3):
    import shutil
    import urllib.request

    for attempt in range(1, tries + 1):
        try:
            print(f"  downloading {os.path.basename(dest)} "
                  f"({attempt}/{tries})…")
            request = urllib.request.Request(
                url, headers={"User-Agent": "MAXIE-setup-tts"}
            )
            with urllib.request.urlopen(request, timeout=120) as resp, \
                    open(dest, "wb") as out:
                shutil.copyfileobj(resp, out)
            print(f"  → {os.path.getsize(dest):,} bytes")
            return
        except Exception as error:
            if attempt == tries:
                raise SystemExit(f"Download failed: {error}")
    raise SystemExit("Download failed.")


def piper_model_urls(voice):
    iso, lang, speaker, quality = _parse_voice(voice)
    base = PIPER_BASE.format(
        iso=iso, lang=lang, speaker=speaker, quality=quality, voice=voice
    )
    return base + ".onnx", base + ".onnx.json"


def _parse_voice(voice):
    parts = voice.split("-")
    lang = parts[0]
    iso = lang.split("_")[0] if "_" in lang else lang
    speaker = parts[1] if len(parts) > 1 else "lessac"
    quality = parts[2] if len(parts) > 2 else "medium"
    return iso, lang, speaker, quality


def install_piper(voice):
    pip_install("piper-tts")
    dest_dir = Config.resolve(os.path.join("Config", "tts_models"))
    os.makedirs(dest_dir, exist_ok=True)
    onnx, voice_json = piper_model_urls(voice)
    dest1 = os.path.join(dest_dir, os.path.basename(onnx))
    dest2 = os.path.join(dest_dir, os.path.basename(voice_json))
    if os.path.exists(dest1) and os.path.exists(dest2):
        print(f"Piper model already present: {dest1}")
    else:
        download(onnx, dest1)
        download(voice_json, dest2)
    Config.set_audio(tts_engine="piper", piper_voice=voice)
    print(f"MAXIE voice engine → piper ({voice}). "
          "Run `python run.py` and hear the difference.")


def install_edge(voice):
    pip_install("edge-tts")
    Config.set_audio(tts_engine="edge", edge_voice=voice)
    print(f"MAXIE voice engine → edge ({voice}). "
          "First utterance downloads the voice; needs internet.")


def install_espeak():
    Config.set_audio(tts_engine="espeak")
    print("MAXIE voice engine → espeak (robotic fallback).")


def test_voice():
    from Voice.voice_engine import VoiceEngine

    Config.load(force=True)
    engine = VoiceEngine()
    print(f"  engine detected: {engine.engine_name()}")
    if engine.disabled:
        print("  ❌ no TTS engine available; check `tts_engine` in "
              "Config/audio_config.json")
        return
    print("  speaking a sample: “Hello, I am MAXIE.”")
    engine.speak("Hello, I am MAXIE. Your voice now sounds natural.")
    timeout = 15
    while engine.is_speaking() and timeout:
        time.sleep(0.1)
        timeout -= 1
    engine.shutdown()


def main():
    parser = argparse.ArgumentParser(description="Set up MAXIE's TTS voice")
    parser.add_argument("--engine", choices=["piper", "edge", "espeak"],
                        default="piper", help="TTS backend")
    parser.add_argument("--voice", default="en_US-lessac-medium",
                        help="Piper model (default en_US-lessac-medium, "
                             "female) or edge voice (e.g. en-US-JennyNeural)")
    args = parser.parse_args()

    if args.engine == "piper":
        install_piper(args.voice)
    elif args.engine == "edge":
        install_edge(args.voice)
    else:
        install_espeak()

    test_voice()


if __name__ == "__main__":
    main()