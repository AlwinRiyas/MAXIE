"""Check that a configured smart-home hub is really reachable (ROADMAP 13.6).

`Tests/home_test.py` proves the adapters build the right request and handle
a broken backend. It cannot prove that *your* hub answers, that the token is
still valid, or that `home_devices.json` names things that exist. This does.

Read-only by default: it resolves every declared device and reports what it
found, then stops. Pass `--live` to actually switch something, which is the
only way to prove the write path works.

    python Installers/check_home.py                # report only
    python Installers/check_home.py --live         # switch a device and back
    python Installers/check_home.py --json         # machine-readable
    python Installers/check_home.py --device "porch lamp"

Exits 0 when everything checked out, 1 on any failure, so it is usable from
a script.
"""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Config.config import Config  # noqa: E402
from Home.device_registry import DeviceRegistry  # noqa: E402
from Home.home_automation import HomeAutomation  # noqa: E402


def _registry():
    return DeviceRegistry(Config.resolve("Config/home_devices.json"),
                          Config.resolve("Config/home_state.json"))


def _home():
    return HomeAutomation(_registry())


def check_config(report):
    home = Config.home_config()
    adapter = str(home.get("adapter", "none")).lower()
    report["adapter"] = adapter

    if adapter in ("none", ""):
        report["ok"].append(
            "No adapter configured (system.home.adapter = none). Home "
            "control is off; this is the default and is not an error.")
        return adapter
    if adapter not in ("home_assistant", "ha", "hue", "philips_hue"):
        report["failures"].append(
            f"system.home.adapter is {adapter!r}, which is not a backend. "
            "Use none, home_assistant or hue.")
        return adapter
    report["ok"].append(f"system.home.adapter = {adapter!r}.")
    return adapter


def check_backend(report):
    home = _home()
    if home.adapter is None:
        if str(report.get("adapter", "none")).lower() in ("none", ""):
            # Home control is off by design. Not a failure -- there is
            # nothing to reach.
            report["ok"].append("No backend needed: home control is off.")
            return None
        report["failures"].append(
            "No backend could be built from config. For home_assistant both "
            "url and token are required; for hue both bridge_ip and "
            "username are. An empty field is the usual cause.")
        return None
    report["ok"].append(f"Backend {home.adapter.name!r} constructed.")
    report["timeout_seconds"] = home.adapter.timeout_seconds()
    return home


def check_devices(report, registry, only=None):
    """Declared devices, or just the one named by `--device`.

    Always a list of resolved device dicts, never a list of names: the
    live check needs the `target` to switch, not the label.
    """
    names = registry.names()
    report["declared_devices"] = names
    if not names:
        report["failures"].append(
            "Config/home_devices.json declares no usable devices. Copy "
            "Config/home_devices.example.json and edit it.")
        return []
    report["ok"].append(f"{len(names)} device(s) declared: "
                        f"{', '.join(names)}.")

    if not only:
        return [registry.get(name) for name in names]

    chosen = registry.resolve(only)
    if chosen is None:
        report["failures"].append(
            f"No declared device matches {only!r}. Declared: "
            f"{', '.join(names)}.")
        return []
    return [chosen]


def check_live(report, home, devices):
    """Switch one device and put it back.

    The write path is the only thing a read cannot prove, so this is opt-in.
    A device whose recorded state is unknown is reported rather than
    toggled: flipping a light that was already on and calling it "restored"
    would be a lie.
    """
    if not devices:
        report["failures"].append("Nothing to switch.")
        return
    device = devices[0]
    before = home.registry.state.get(device["name"].lower())
    report["live_device"] = device["name"]
    report["live_state_before"] = before

    if before is None:
        report["failures"].append(
            f"{device['name']} has no recorded state, so a live test cannot "
            "put it back. Ask MAXIE to switch it once, then re-run.")
        return

    was_on = before.get("action") in ("on", "set")
    target = "off" if was_on else "on"
    reply = home.execute(device["name"], target)
    report["live_reply"] = reply

    if not home._looks_like_success(reply):
        report["failures"].append(
            f"Switching {device['name']} {target} did not report success: "
            f"{reply}")
        return

    back = "on" if was_on else "off"
    report["live_restore_reply"] = home.execute(device["name"], back)
    after = home.registry.state.get(device["name"].lower())
    report["live_state_after"] = after

    if not home._looks_like_success(report["live_restore_reply"]):
        report["failures"].append(
            f"Could not put {device['name']} back: "
            f"{report['live_restore_reply']}")
    else:
        report["ok"].append(
            f"{device['name']} switched {target} and back {back}.")


def main():
    parser = argparse.ArgumentParser(
        description="Verify the configured smart-home hub is reachable")
    parser.add_argument("--live", action="store_true",
                        help="switch a device and restore it")
    parser.add_argument("--device", default=None,
                        help="the device to use for --live")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output")
    args = parser.parse_args()

    report = {"ok": [], "failures": []}
    adapter = check_config(report)
    registry = _registry()
    backend = check_backend(report)
    devices = check_devices(report, registry, args.device)

    report["resolved"] = [d["name"] for d in devices]
    if adapter not in ("none", "") and not devices:
        report["failures"].append(
            "A backend is configured but nothing is declared, so no "
            "entity can be addressed.")

    if args.live:
        if backend is None:
            report["live"] = "skipped: no backend configured"
        elif report["failures"]:
            report["live"] = "skipped: earlier checks failed"
        else:
            report["live"] = "ran"
            check_live(report, backend, devices)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 1 if report["failures"] else 0

    for line in report["ok"]:
        print(f"  ok  {line}")
    for line in report["failures"]:
        print(f"  !!  {line}")
    print()
    if report["failures"]:
        print(f"{len(report['failures'])} problem(s) found.")
        return 1
    if args.live and report.get("live") == "ran":
        print("Live check passed: a device was switched and restored.")
    elif args.live:
        print(f"--live did not run ({report.get('live')}). Nothing was "
              "switched.")
    elif str(report.get("adapter", "none")).lower() in ("none", ""):
        print("Home control is not configured, so there is nothing to "
              "verify. See Config/home_devices.example.json.")
    else:
        print("Read-only checks passed. Use --live to prove the write path.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
