"""Worker de IA separado do coletor factual.

Este processo lê apenas MarketStates congelados no SQLite. Ele não acessa o
terminal de negociação, não lê Outcomes para decidir e não executa ordens.
"""
from __future__ import annotations

import argparse
import os
import signal
from dataclasses import dataclass
from threading import Event, Thread

from po3.storage.migrations import migrate
from po3.storage.market_repository import acquire_lease, heartbeat, release_lease
from po3.v2_config import AUTO_DECISION_ENGINE, SHADOW_MODE_ENABLED
from po3.decision_engine.schemas import DECISION_ENGINE_VERSION, PROMPT_VERSION


@dataclass(frozen=True)
class AIWorkerConfig:
    symbol: str
    db_path: str
    poll_seconds: int = 10
    lease_ttl_seconds: int = 90
    heartbeat_interval_seconds: float = 25.0
    lease_name: str = "po3-ai"


def _heartbeat_loop(config: AIWorkerConfig, owner: str, stop_event: Event,
                    heartbeat_stop: Event, lease_lost: Event) -> None:
    """Renova o lease independentemente de chamadas lentas de IA."""
    interval = max(0.25, min(float(config.heartbeat_interval_seconds),
                              max(0.25, config.lease_ttl_seconds / 3.0)))
    while not heartbeat_stop.wait(interval):
        if not heartbeat(config.lease_name, config.symbol, owner, config.db_path,
                         config.lease_ttl_seconds):
            lease_lost.set()
            stop_event.set()
            return


def run_ai_worker(config: AIWorkerConfig, stop_event: Event | None = None, max_cycles: int | None = None) -> None:
    migrate(config.db_path)
    owner = acquire_lease(config.lease_name, config.symbol, config.db_path, ttl_seconds=config.lease_ttl_seconds)
    if not owner:
        raise RuntimeError("Outro AI worker possui o lease")
    stop_event = stop_event or Event()
    heartbeat_stop = Event()
    lease_lost = Event()
    heartbeat_thread = Thread(
        target=_heartbeat_loop,
        args=(config, owner, stop_event, heartbeat_stop, lease_lost),
        name="po3-ai-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()
    stop_file = os.getenv("PO3_AI_WORKER_STOP_FILE")
    shadow_runner = None
    shadow_model = None
    if SHADOW_MODE_ENABLED:
        try:
            from po3.shadow_runner import build_shadow_decision_runner
            shadow_runner, shadow_model = build_shadow_decision_runner()
        except Exception as exc:
            print(f"Shadow indisponível: {type(exc).__name__}: {exc}", flush=True)
    cycles = 0
    try:
        while not stop_event.is_set() and (max_cycles is None or cycles < max_cycles):
            if stop_file and os.path.exists(stop_file):
                stop_event.set()
                break
            if AUTO_DECISION_ENGINE and not lease_lost.is_set() and not stop_event.is_set():
                try:
                    from po3.auto_decision import process_pending_auto_decisions
                    process_pending_auto_decisions(config.db_path, symbol=config.symbol, limit=1)
                except Exception as exc:
                    print(f"AI Auto Decision: {type(exc).__name__}: {exc}", flush=True)
            if SHADOW_MODE_ENABLED and shadow_runner is not None and not lease_lost.is_set() and not stop_event.is_set():
                try:
                    from po3.shadow_mode import process_pending_shadow_states
                    process_pending_shadow_states(
                        config.db_path, shadow_runner, limit=1,
                        model_configured=shadow_model or "UNSPECIFIED",
                        decision_engine_version=DECISION_ENGINE_VERSION,
                        prompt_version=PROMPT_VERSION, symbol=config.symbol,
                    )
                except Exception as exc:
                    print(f"AI Shadow: {type(exc).__name__}: {exc}", flush=True)
            if lease_lost.is_set():
                raise RuntimeError("Lease do AI worker perdido")
            cycles += 1
            if max_cycles is None:
                stop_event.wait(max(1, config.poll_seconds))
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=max(1.0, config.heartbeat_interval_seconds + 1.0))
        release_lease(config.lease_name, config.symbol, owner, config.db_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Worker de Shadow e análise oficial do PO3 Copilot")
    parser.add_argument("--symbol", default=os.getenv("MT5_SYMBOL", "WINV26"))
    parser.add_argument("--db", default="data/po3_learning.sqlite")
    parser.add_argument("--poll-seconds", type=int, default=10)
    args = parser.parse_args()
    stop = Event()
    stop_file = os.getenv("PO3_AI_WORKER_STOP_FILE")

    def request_stop(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, request_stop)
    if stop_file and os.path.exists(stop_file):
        os.unlink(stop_file)
    run_ai_worker(AIWorkerConfig(args.symbol, args.db, args.poll_seconds), stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
