"""End-to-end check against a real PhotoCraft window.

    python scripts/smoke.py --exe <photocraft.exe> [--photos DIR] [--limit SECONDS]

Starts the helper with a temporary data folder, opens each photo, chooses
Filter > Plug-ins > Remove Background (AI) through the control channel, and times the click until
the mask is applied. Then checks that one undo step restores the photo and that the helper exits
after PhotoCraft quits. The first photo includes loading the model and is not held to --limit.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from removebg.control import Control, port_open  # noqa: E402
from removebg.photocraft import INDICATOR_NAME  # noqa: E402
from removebg.trigger import MENU_NAME, PLUGIN_ID  # noqa: E402

PORT = 7893


def wait_for(condition, timeout, what):
    deadline = time.monotonic() + timeout
    while True:
        result = condition()
        if result:
            return result
        if time.monotonic() > deadline:
            raise SystemExit(f"timed out waiting for {what}")
        time.sleep(0.2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exe", required=True, help="path to photocraft.exe")
    parser.add_argument("--photos", default=str(REPO / "tests" / "fixtures"))
    parser.add_argument("--limit", type=float, default=12.0, help="seconds allowed per photo once the model is loaded")
    args = parser.parse_args()

    home = Path(tempfile.mkdtemp(prefix="removebg-smoke-"))
    (home / "config.json").write_text(json.dumps(
        {"photocraftExe": args.exe, "controlPort": PORT, "lockPort": PORT + 1}), encoding="utf-8")
    env = dict(os.environ, PHOTOCRAFT_REMOVEBG_HOME=str(home),
               PHOTOCRAFT_REMOVEBG_MODELS=os.environ.get("PHOTOCRAFT_REMOVEBG_MODELS",
                                                         str(REPO / ".cache" / "models")))
    if port_open(PORT):
        raise SystemExit(f"port {PORT} is already in use; close the PhotoCraft left open by an earlier run")
    helper = subprocess.Popen([sys.executable, "-m", "removebg.helper"], cwd=REPO, env=env)
    failures = []
    rows = []
    try:
        wait_for(lambda: port_open(PORT), 60, "PhotoCraft to open its control port")
        token = wait_for(lambda: (home / "control.token").is_file() and (home / "control.token").read_text().strip(),
                         10, "the control token")
        ctl = Control(PORT, token)
        wait_for(lambda: any(p["id"] == PLUGIN_ID for p in ctl.run("plugin.list")["plugins"]), 30,
                 "the helper to install the plug-in")

        photos = sorted(p for p in Path(args.photos).iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        for n, photo in enumerate(photos):
            shutil.copy(photo, home / "exchange" / photo.name)
            ctl.call("app.open", {"path": photo.name})
            before = ctl.run("document.inspect")
            target = before["activeLayer"]

            def done():
                doc = ctl.run("document.inspect")
                layers = {layer["id"]: layer for layer in doc["layers"]}
                finished = (layers.get(target, {}).get("hasMask")
                            and not any(layer["name"] == INDICATOR_NAME for layer in doc["layers"]))
                return doc if finished else None

            started = time.perf_counter()
            ctl.call("ui.menu.invoke", {"id": f"plugin.filter.{PLUGIN_ID}"})
            doc = wait_for(done, 120, f"the mask on {photo.name}")
            seconds = time.perf_counter() - started

            one_step = doc["history"] == before["history"] + [MENU_NAME]
            ctl.run("edit.undo")
            after = ctl.run("document.inspect")
            restored = (after["history"] == before["history"]
                        and not next(layer for layer in after["layers"] if layer["id"] == target)["hasMask"])
            within = n == 0 or seconds <= args.limit
            rows.append((photo.name, seconds, one_step, restored, within))
            if not (one_step and restored and within):
                failures.append(photo.name)
            index = next(d["index"] for d in ctl.call("ui.inspect")["session"]["documents"] if d["name"] == photo.name)
            ctl.run("file.close", {"document": index})

        ctl.call("app.quit")
        try:
            helper.wait(timeout=40)
            helper_exited = True
        except subprocess.TimeoutExpired:
            helper_exited = False
            failures.append("helper did not exit")
    finally:
        if helper.poll() is None:
            helper.kill()
        log_file = home / "helper.log"
        if log_file.is_file():
            print("\nhelper.log:")
            for line in log_file.read_text(encoding="utf-8").splitlines():
                if "Removed the background" in line or "ERROR" in line:
                    print("  " + line)
        shutil.rmtree(home, ignore_errors=True)

    print(f"\n{'photo':<24}{'seconds':>8}  one step  undo ok  within limit")
    for name, seconds, one_step, restored, within in rows:
        note = "  (includes loading the model)" if name == rows[0][0] else ""
        print(f"{name:<24}{seconds:>8.1f}  {one_step!s:<8}  {restored!s:<7}  {within!s}{note}")
    print(f"helper exited after PhotoCraft quit: {helper_exited}")
    print("PASS" if not failures else f"FAIL: {', '.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
