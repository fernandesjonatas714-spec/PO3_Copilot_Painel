"""Supervisor local: Streamlit e coletor factual M1, sem IA automática."""
from __future__ import annotations
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

def _stop_process_gracefully(process, timeout: float = 15.0) -> bool:
    if process is None or process.poll() is not None:
        return True
    try:
        if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=timeout)
        return True
    except (subprocess.TimeoutExpired, OSError):
        return False

def main() -> int:
    root = Path(__file__).resolve().parents[1]
    py = sys.executable
    env = os.environ.copy()
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    stop_file = root / "data" / ".po3_worker.stop"
    ai_stop_file = root / "data" / ".po3_ai_worker.stop"
    stop_file.unlink(missing_ok=True)
    ai_stop_file.unlink(missing_ok=True)
    env["PO3_WORKER_STOP_FILE"] = str(stop_file)
    env["PO3_AI_WORKER_STOP_FILE"] = str(ai_stop_file)
    def _raise_keyboard_interrupt(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGINT, _raise_keyboard_interrupt)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _raise_keyboard_interrupt)
    worker = None
    ai_worker = None
    if env.get("AUTO_DATA_COLLECTION", "true").lower() in {"1","true","sim","yes"}:
        worker = subprocess.Popen([py, "-m", "po3.collection.mt5_m1_collector"], cwd=root, env=env,
                                  creationflags=creationflags)
    if env.get("SHADOW_MODE_ENABLED", "false").lower() in {"1", "true", "sim", "yes"} or env.get("AUTO_DECISION_ENGINE", "false").lower() in {"1", "true", "sim", "yes"}:
        ai_worker = subprocess.Popen([py, "-m", "po3.ai_worker"], cwd=root, env=env,
                                     creationflags=creationflags)
    streamlit = subprocess.Popen([py, "-m", "streamlit", "run", str(root / "macro_app.py"),
                                  "--server.address", "127.0.0.1", "--server.port", "8501",
                                  "--server.headless", "false", "--server.showEmailPrompt", "false",
                                  "--browser.gatherUsageStats", "false"], cwd=root, env=env,
                                  creationflags=creationflags)
    try:
        return streamlit.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        if worker is not None and worker.poll() is None:
            # O sinal de console pode não atravessar o shim do Python no
            # Windows. O arquivo é um pedido de parada graciosa observado
            # pelo worker no próximo ciclo, garantindo release_lease/finally.
            stop_file.parent.mkdir(parents=True, exist_ok=True)
            stop_file.write_text("stop\n", encoding="ascii")
            if not _stop_process_gracefully(worker):
                worker.terminate()
                worker.wait(timeout=10)
        if ai_worker is not None and ai_worker.poll() is None:
            ai_stop_file.parent.mkdir(parents=True, exist_ok=True)
            ai_stop_file.write_text("stop\n", encoding="ascii")
            if not _stop_process_gracefully(ai_worker):
                ai_worker.terminate()
                ai_worker.wait(timeout=10)
        if streamlit.poll() is None:
            if not _stop_process_gracefully(streamlit):
                streamlit.terminate()
        stop_file.unlink(missing_ok=True)
        ai_stop_file.unlink(missing_ok=True)

if __name__ == "__main__":
    raise SystemExit(main())
