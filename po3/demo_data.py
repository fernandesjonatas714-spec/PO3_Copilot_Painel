from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .levels import build_context_levels, build_daily_zones
from .models import MarketSnapshot, PO3Event


SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def _bars(timeframe_minutes: int, count: int, base: float, seed: int) -> list[dict]:
    randomizer = random.Random(seed)
    now = datetime.now(SAO_PAULO).replace(second=0, microsecond=0)
    result: list[dict] = []
    previous = base
    for index in range(count):
        time = now - timedelta(minutes=timeframe_minutes * (count - index - 1))
        drift = math.sin(index / 7.0) * 35 + randomizer.uniform(-55, 55)
        open_price = previous
        close = open_price + drift
        high = max(open_price, close) + randomizer.uniform(15, 60)
        low = min(open_price, close) - randomizer.uniform(15, 60)
        result.append(
            {
                "time": time,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "tick_volume": randomizer.randint(300, 2200),
            }
        )
        previous = close
    return result


def build_demo_snapshot(symbol: str = "WINV26") -> MarketSnapshot:
    now = datetime.now(SAO_PAULO)
    intraday = {
        "M15": _bars(15, 80, 187_700, 15),
        "M5": _bars(5, 100, 188_150, 5),
        "M1": _bars(1, 120, 188_500, 1),
    }
    daily = [
        {"time": now - timedelta(days=6), "open": 180_000, "high": 181_000, "low": 178_000, "close": 179_000},
        {"time": now - timedelta(days=5), "open": 179_000, "high": 191_000, "low": 178_500, "close": 190_000},
        {"time": now - timedelta(days=4), "open": 190_000, "high": 195_000, "low": 189_500, "close": 194_000},
        {"time": now - timedelta(days=3), "open": 194_000, "high": 196_000, "low": 193_500, "close": 195_000},
        {"time": now - timedelta(days=2), "open": 196_000, "high": 199_000, "low": 196_500, "close": 198_000},
        {"time": now - timedelta(days=1), "open": 198_000, "high": 200_000, "low": 197_000, "close": 199_000},
    ]
    weekly = [
        {"time": now - timedelta(days=14), "open": 173_000, "high": 179_220, "low": 172_000, "close": 178_400},
        {"time": now - timedelta(days=7), "open": 178_500, "high": 190_100, "low": 177_900, "close": 188_400},
    ]
    monthly = [
        {"time": now - timedelta(days=62), "open": 169_200, "high": 185_670, "low": 167_975, "close": 183_500},
        {"time": now - timedelta(days=31), "open": 183_600, "high": 190_100, "low": 181_970, "close": 188_400},
    ]
    levels = build_context_levels(daily, weekly, monthly)
    zones = {"M15": build_daily_zones(daily)}
    intraday["D1"] = daily
    last_price = float(intraday["M1"][-1]["close"])
    return MarketSnapshot(
        symbol=symbol,
        as_of=now,
        last_price=last_price,
        connected=False,
        source="Demonstracao local",
        bars=intraday,
        levels=levels,
        zones=zones,
        events=[
            PO3Event(now - timedelta(minutes=35), "Contexto carregado", "Niveis semanais e mensais calculados no M15."),
            PO3Event(now - timedelta(minutes=25), "Objetivos D1", "FVGs e Order Blocks diarios ativos projetados no M15."),
            PO3Event(now - timedelta(minutes=12), "Pregao anterior", "Niveis diarios calculados no M5."),
            PO3Event(now, "Entrada", "M1 aguardando confirmacao manual."),
        ],
        notes=["Dados simulados: nenhuma conexao com conta ou corretora."],
    )
