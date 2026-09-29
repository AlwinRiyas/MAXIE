import argparse
import os
import subprocess
import sys

# Allow running from anywhere: make the project root importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP_NAME = "MAXIE"
REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
XDG_AUTOSTART_DIR = os.path.join(
    os.path.expanduser("~"), ".config", "autostart"
)


def _python_command():
    """pythonw on Windows (no console window) else the current python."""
    if sys.platform.startswith("win"):
        for candidate in (sys.executable, "pythonw.exe", "pythonw"):
            if os.path.basename(candidate or "").lower().startswith("pythonw"):
                return os.path.abspath(candidate) if candidate == sys.executable else candidate
            if candidate == sys.executable:
                continue
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.exists(pythonw):
            return pythonw
    return sys.executable


def _target_command():
    """Command line that starts MAXIE with the GUI at login."""
    python = _python_command()
    run_py = os.path.join(ROOT, "run.py")
    return [python, run_py, "--gui", "--minimized"]


def is_enabled():
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
                winreg.QueryValueEx(key, APP_NAME)
            return True
        except OSError:
            return False

    if sys.platform.startswith("linux"):
        return os.path.exists(os.path.join(XDG_AUTOSTART_DIR, "maxie.desktop"))

    return False


def enable():
    cmd = _target_command()

    if sys.platform.startswith("win"):
        import winreg

        quoted = f'"{cmd[0]}" {" ".join('"' + a + '"' for a in cmd[1:])}'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, quoted)
        return f"MAXIE will start automatically at login. ({quoted})"

    if sys.platform.startswith("linux"):
        os.makedirs(XDG_AUTOSTART_DIR, exist_ok=True)
        desktop = os.path.join(XDG_AUTOSTART_DIR, "maxie.desktop")
        python = cmd[0]
        run_py = cmd[1]
        args = " ".join(cmd[2:])
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=MAXIE\n"
            "Comment=Jarvis-style personal assistant\n"
            f"Exec={python} {run_py} {args}\n"
            "X-GNOME-Autostart-enabled=true\n"
            "Terminal=false\n"
        )
        with open(desktop, "w", encoding="utf-8") as f:
            f.write(content)
        return f"MAXIE will start automatically at login. ({desktop})"

    return "Auto-start isn't supported on this platform."


def disable():
    if sys.platform.startswith("win"):
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, APP_NAME)
        except OSError:
            pass
        return "MAXIE auto-start disabled."

    if sys.platform.startswith("linux"):
        desktop = os.path.join(XDG_AUTOSTART_DIR, "maxie.desktop")
        if os.path.exists(desktop):
            os.remove(desktop)
        return "MAXIE auto-start disabled."

    return "Auto-start isn't supported on this platform."


def status():
    return "MAXIE auto-start is ENABLED." if is_enabled() else (
        "MAXIE auto-start is DISABLED."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Register MAXIE to start automatically at login."
    )
    parser.add_argument(
        "action", choices=["enable", "disable", "status", "test"],
        help="What to do",
    )
    args = parser.parse_args()

    if args.action == "enable":
        print(enable())
    elif args.action == "disable":
        print(disable())
    elif args.action == "status":
        print(status())
    elif args.action == "test":
        cmd = _target_command()
        print("Will launch:", cmd)
        if is_enabled():
            print(status())
        else:
            print("Auto-start is disabled.")


if __name__ == "__main__":
    main()