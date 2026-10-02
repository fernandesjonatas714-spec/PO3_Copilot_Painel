"""Supervisor local: Streamlit e coletor factual M1, sem IA automática."""
from __future__ import annotations
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

RESTART_BACKOFF_SECONDS = (5.0, 10.0, 30.0)
HEALTHY_RESET_SECONDS = 60.0

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


def _supervise_children(streamlit, children, factories, shutdown_requested,
                        *, poll_interval: float = 0.5, sleep_fn=time.sleep,
                        clock=time.monotonic):
    """Mantém coletor e AI ativos enquanto o Streamlit define a vida útil."""
    restart_count = {name: 0 for name in factories}
    next_restart = {name: None for name in factories}
    healthy_since = {name: None for name in factories}
    while streamlit.poll() is None:
        if shutdown_requested():
            break
        now = clock()
        for name, factory in factories.items():
            process = children.get(name)
            if process is not None and process.poll() is None:
                if healthy_since[name] is None:
                    healthy_since[name] = now
                elif now - healthy_since[name] >= HEALTHY_RESET_SECONDS:
                    restart_count[name] = 0
                    next_restart[name] = now + RESTART_BACKOFF_SECONDS[0]
                continue
            healthy_since[name] = None
            if next_restart[name] is None:
                next_restart[name] = now + RESTART_BACKOFF_SECONDS[0]
            if now < next_restart[name] or shutdown_requested():
                continue
            try:
                children[name] = factory()
            except Exception as exc:
                print(f"Falha ao relançar {name}: {type(exc).__name__}: {exc}", flush=True)
            restart_count[name] += 1
            delay_index = min(restart_count[name], len(RESTART_BACKOFF_SECONDS) - 1)
            next_restart[name] = now + RESTART_BACKOFF_SECONDS[delay_index]
            healthy_since[name] = now
        sleep_fn(poll_interval)
    return streamlit.poll()

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
    children = {}
    factories = {}
    if env.get("AUTO_DATA_COLLECTION", "true").lower() in {"1","true","sim","yes"}:
        factories["worker"] = lambda: subprocess.Popen(
            [py, "-m", "po3.collection.mt5_m1_collector"], cwd=root, env=env,
            creationflags=creationflags)
        children["worker"] = factories["worker"]()
    if env.get("SHADOW_MODE_ENABLED", "false").lower() in {"1", "true", "sim", "yes"} or env.get("AUTO_DECISION_ENGINE", "false").lower() in {"1", "true", "sim", "yes"}:
        factories["ai_worker"] = lambda: subprocess.Popen(
            [py, "-m", "po3.ai_worker"], cwd=root, env=env,
            creationflags=creationflags)
        children["ai_worker"] = factories["ai_worker"]()
    streamlit = subprocess.Popen([py, "-m", "streamlit", "run", str(root / "macro_app.py"),
                                  "--server.address", "127.0.0.1", "--server.port", "8501",
                                  "--server.headless", "false", "--server.showEmailPrompt", "false",
                                  "--browser.gatherUsageStats", "false"], cwd=root, env=env,
                                  creationflags=creationflags)
    shutdown_requested = False
    try:
        return _supervise_children(streamlit, children, factories, lambda: shutdown_requested)
    except KeyboardInterrupt:
        shutdown_requested = True
        return 130
    finally:
        shutdown_requested = True
        worker = children.get("worker")
        ai_worker = children.get("ai_worker")
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
