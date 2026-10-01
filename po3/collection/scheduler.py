"""Agendamento factual de snapshots a cada cinco minutos, sem LLM."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from threading import Event
import time

def next_boundary(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc).replace(second=0, microsecond=0)
    minute = ((value.minute // 5) + 1) * 5
    if minute >= 60:
        value = value.replace(minute=0) + timedelta(hours=1)
    else:
        value = value.replace(minute=minute)
    return value

def run_scheduler(capture, stop_event: Event, *, poll_seconds: int = 1, max_cycles: int | None = None) -> int:
    cycles = 0
    while not stop_event.is_set() and (max_cycles is None or cycles < max_cycles):
        now = datetime.now(timezone.utc)
        boundary = next_boundary(now)
        wait = max(0.0, (boundary - now).total_seconds())
        if stop_event.wait(min(wait, poll_seconds)):
            break
        if datetime.now(timezone.utc) >= boundary:
            capture(boundary)
            cycles += 1
    return cycles
