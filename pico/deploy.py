"""Copy the robot code onto a Pico W over USB. Runs on the laptop.

Needs mpremote (pip install mpremote) and MicroPython already on the Pico.
Close Thonny first, since only one program can hold the Pico's port.

  python pico/deploy.py               copy everything, then restart the Pico
  python pico/deploy.py --bench       leave main.py off, so nothing drives on boot
  python pico/deploy.py --port COM7   pick the port when more than one board is plugged in

With --bench, run motor_test.py, link_test.py, or calibrate.py from Thonny.
Deploy again without --bench to make the robot start by itself.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROBOT = ["navigation.py", "stepper.py", "wifi_link.py", "brain.py", "config.py"]
BENCH = ["motor_test.py", "link_test.py", "calibrate.py"]


def mpremote() -> list[str]:
    if shutil.which("mpremote"):
        return ["mpremote"]
    try:
        import mpremote as _  # noqa: F401
    except ImportError:
        sys.exit("mpremote is not installed. Run: pip install mpremote")
    return [sys.executable, "-m", "mpremote"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy the robot code onto a Pico W.")
    parser.add_argument("--bench", action="store_true", help="leave main.py off the Pico")
    parser.add_argument("--port", help="serial port, such as COM7 (default: first Pico found)")
    args = parser.parse_args()

    if not (HERE / "config.py").exists():
        sys.exit("pico/config.py is missing. Copy pico/config_example.py to pico/config.py and fill it in.")
    if "CHANGE_ME" in (HERE / "config.py").read_text(encoding="utf-8"):
        sys.exit("pico/config.py still has ROBOT_TOKEN = CHANGE_ME. Set it to RATTLE_ROBOT_TOKEN.")

    command = mpremote() + ["connect", args.port or "auto"]
    files = ROBOT + BENCH + ([] if args.bench else ["main.py"])
    for name in files:
        command += ["cp", str(HERE / name), ":" + name, "+"]
    if args.bench:
        # A main.py left from an earlier deploy would still drive on boot.
        command += ["exec", "import os\ntry:\n os.remove('main.py')\nexcept OSError:\n pass", "+"]
    command += ["reset"]

    print("Copying", len(files), "files to the Pico" + (" (bench mode, no main.py)" if args.bench else ""))
    result = subprocess.run(command)
    if result.returncode != 0:
        sys.exit("mpremote failed. Is the Pico plugged in, with Thonny closed?")
    print("Done. The Pico restarted." + ("" if args.bench else " The robot runs main.py on its own."))


if __name__ == "__main__":
    main()
