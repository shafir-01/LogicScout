"""Launch the gate service (:8790) and the API (default $PORT or 8787); forward signals."""
from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
import time

GATE_MODULE = "logicscout.worlds.gate_service"


def main() -> int:
    env = os.environ.copy()
    procs: list[subprocess.Popen] = []
    try:
        have_gate = importlib.util.find_spec(GATE_MODULE) is not None
    except Exception:
        have_gate = False
    if have_gate:
        procs.append(subprocess.Popen([sys.executable, "-m", GATE_MODULE], env=env))
    else:
        print(f"[serve] {GATE_MODULE} not found; starting API only", file=sys.stderr)
    procs.append(subprocess.Popen([sys.executable, "-m", "logicscout.server"], env={**env, "PORT": env.get("PORT", "8787")}))

    def stop(*_):
        for p in procs:
            if p.poll() is None:
                p.terminate()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    finally:
        stop()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return max((p.returncode or 0) for p in procs)


if __name__ == "__main__":
    raise SystemExit(main())
