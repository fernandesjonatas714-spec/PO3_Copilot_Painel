"""Alinhamento auditavel entre timestamps crus do MT5 e UTC canonico."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

@dataclass(frozen=True)
class Mt5TimeAlignment:
    observed_at_system_utc: datetime | None
    raw_tick_time: int | None
    raw_tick_time_msc: int | None
    detected_offset_seconds: float | None
    normalized_tick_at_utc: datetime | None
    status: str
    feed_liveness_status: str
    clock_alignment_status: str
    source: str = "MT5"
    detected_at: datetime | None = None
    detail: str = ""

def epoch_utc(value: float | int | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return datetime.fromtimestamp(float(value), timezone.utc)

def _raw_epoch_seconds(raw_time: float | int | None, raw_time_msc: int | None) -> float | None:
    if raw_time_msc is not None:
        return float(raw_time_msc) / 1000.0
    return float(raw_time) if raw_time is not None else None

def normalize_mt5_timestamp(raw_time: float | int | datetime, detected_offset_seconds: float, *, already_normalized: bool = False) -> datetime:
    """Normaliza um timestamp cru exatamente uma vez para UTC."""
    raw = raw_time.timestamp() if isinstance(raw_time, datetime) else float(raw_time)
    if already_normalized:
        return datetime.fromtimestamp(raw, timezone.utc)
    return datetime.fromtimestamp(raw + float(detected_offset_seconds), timezone.utc)

class Mt5TimeAlignmentDetector:
    def __init__(self, *, source: str = "MT5", live_tolerance_seconds: float = 2.0,
                 offset_tolerance_seconds: float = 2.0, max_samples: int = 8):
        self.source = source
        self.live_tolerance_seconds = float(live_tolerance_seconds)
        self.offset_tolerance_seconds = float(offset_tolerance_seconds)
        self.samples: deque[tuple[float, float, float]] = deque(maxlen=max_samples)
        self.last: Mt5TimeAlignment = Mt5TimeAlignment(
            None, None, None, None, None, "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE",
            source=source, detail="Ainda sem duas amostras de tick."
        )

    def observe(self, *, raw_tick_time: int | None, raw_tick_time_msc: int | None,
                observed_at_system_utc: datetime | None = None) -> Mt5TimeAlignment:
        observed = (observed_at_system_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
        raw_epoch = float(raw_tick_time) if raw_tick_time is not None else _raw_epoch_seconds(raw_tick_time, raw_tick_time_msc)
        raw_live_epoch = _raw_epoch_seconds(raw_tick_time, raw_tick_time_msc)
        if raw_epoch is None or raw_live_epoch is None:
            self.last = Mt5TimeAlignment(observed, raw_tick_time, raw_tick_time_msc, None, None,
                "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", source=self.source,
                detected_at=observed, detail="MT5 nao forneceu timestamp de tick.")
            return self.last
        raw_offset = observed.replace(microsecond=0).timestamp() - raw_epoch
        # O epoch do tick pode variar alguns segundos entre a leitura do
        # relogio e a chegada do tick. O offset canonico e arredondado para o
        # minuto mais proximo, sem assumir um fuso especifico.
        offset = round(raw_offset / 60.0) * 60.0
        previous = self.samples[-1] if self.samples else None
        self.samples.append((observed.timestamp(), raw_epoch, raw_live_epoch))
        if previous is None:
            self.last = Mt5TimeAlignment(observed, raw_tick_time, raw_tick_time_msc, offset,
                normalize_mt5_timestamp(raw_epoch, offset), "UNAVAILABLE", "UNAVAILABLE",
                "UNAVAILABLE", source=self.source, detected_at=observed,
                detail="Primeira amostra; aguardando confirmacao de liveness.")
            return self.last
        wall_elapsed = observed.timestamp() - previous[0]
        tick_elapsed = raw_live_epoch - previous[2]
        live = wall_elapsed > 0 and tick_elapsed > 0 and abs(tick_elapsed - wall_elapsed) <= self.live_tolerance_seconds
        liveness = "LIVE" if tick_elapsed > 0 else "STALE"
        offsets = [observed_ts - raw_offset for observed_ts, raw_offset, _ in self.samples]
        stable = max(offsets) - min(offsets) <= self.offset_tolerance_seconds
        if tick_elapsed <= 0:
            status, clock, detail = "STALE", "UNSTABLE_OFFSET", "Tick nao avancou de forma compativel com o relogio."
        elif not stable:
            status, clock, detail = "UNSTABLE_OFFSET", "UNSTABLE_OFFSET", "Offset variou alem do limite de estabilidade."
        elif not live:
            status, clock, detail = "STALE", "UNSTABLE_OFFSET", "Tick nao avancou de forma compativel com o relogio."
        else:
            clock = "OFFSET_DETECTED" if abs(offset) > self.offset_tolerance_seconds else "ALIGNED"
            status = clock
            detail = f"Feed LIVE; wall_elapsed={wall_elapsed:.3f}s; tick_elapsed={tick_elapsed:.3f}s."
        self.last = Mt5TimeAlignment(observed, raw_tick_time, raw_tick_time_msc, offset,
            normalize_mt5_timestamp(raw_epoch, offset), status, liveness, clock,
            source=self.source, detected_at=observed, detail=detail)
        return self.last

    @property
    def usable(self) -> bool:
        return self.last.feed_liveness_status == "LIVE" and self.last.clock_alignment_status in {"ALIGNED", "OFFSET_DETECTED"}

    def normalize(self, raw_time: float | int | datetime) -> datetime:
        if not self.usable or self.last.detected_offset_seconds is None:
            raise RuntimeError("Alinhamento MT5 ainda não validado.")
        # Barras M1 sao alinhadas em segundos inteiros; evita microssegundos
        # do instante de observacao deslocarem a chave temporal do candle.
        return normalize_mt5_timestamp(raw_time, round(self.last.detected_offset_seconds))
