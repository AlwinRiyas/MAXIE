import argparse
import os
import sys

# Allow running from anywhere: make the project root importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from Config.config import Config  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="MAXIE — Jarvis-style assistant")
    parser.add_argument("--gui", action="store_true",
                        help="Launch the desktop control panel")
    parser.add_argument("--minimized", action="store_true",
                        help="Start the GUI minimized (for auto-start)")
    parser.add_argument("--console", action="store_true",
                        help="Force the console interface")
    args = parser.parse_args()

    Config.load()

    from Core.core_manager import Maxie

    if args.gui and not args.console:
        from Ui.gui import launch

        try:
            launch(minimized=args.minimized)
        except Exception as error:
            print(f"GUI could not open: {error}")
            print("Hint: the GUI needs a display. Use --console instead.")
        return

    assistant = Maxie()

    try:
        assistant.start()
    except KeyboardInterrupt:
        assistant.shutdown()
        print("\nMAXIE stopped cleanly.")
    except SystemExit:
        assistant.shutdown()
        raise
    finally:
        assistant.shutdown()


if __name__ == "__main__":
    main()