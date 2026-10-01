"""Supervisor local: Streamlit e coletor factual M1, sem IA automática."""
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path

def main() -> int:
    root = Path(__file__).resolve().parents[1]
    py = sys.executable
    env = os.environ.copy()
    worker = None
    if env.get("AUTO_DATA_COLLECTION", "true").lower() in {"1","true","sim","yes"}:
        worker = subprocess.Popen([py, "-m", "po3.collection.mt5_m1_collector"], cwd=root, env=env)
    streamlit = subprocess.Popen([py, "-m", "streamlit", "run", str(root / "macro_app.py"),
                                  "--server.address", "127.0.0.1", "--server.port", "8501",
                                  "--server.headless", "false", "--server.showEmailPrompt", "false",
                                  "--browser.gatherUsageStats", "false"], cwd=root, env=env)
    try:
        return streamlit.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try: worker.wait(timeout=10)
            except subprocess.TimeoutExpired: worker.kill()
        if streamlit.poll() is None:
            streamlit.terminate()

if __name__ == "__main__":
    raise SystemExit(main())
