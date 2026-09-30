from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .levels import build_context_levels, build_daily_zones
from .models import MarketSnapshot, PO3Event
from .macro import build_macro


SAO_PAULO = ZoneInfo("America/Sao_Paulo")


class MT5ReadError(RuntimeError):
    pass


def _load_package():
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise MT5ReadError("Pacote MetaTrader5 nao instalado.") from exc
    return mt5


def _rates_to_bars(rates) -> list[dict]:
    if rates is None:
        return []
    bars: list[dict] = []
    for row in rates:
        bars.append(
            {
                "time": datetime.fromtimestamp(int(row["time"]), tz=timezone.utc).astimezone(SAO_PAULO),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "tick_volume": int(row["tick_volume"]),
            }
        )
    return sorted(bars, key=lambda bar: bar["time"])


def read_snapshot(terminal_path: str, symbol: str) -> MarketSnapshot:
    """Le candles e cotacao. Nao expoe nenhuma operacao de negociacao."""
    mt5 = _load_package()
    terminal = Path(terminal_path)
    if not terminal.is_file():
        raise MT5ReadError(f"Terminal nao encontrado: {terminal}")

    if not mt5.initialize(str(terminal), timeout=8_000):
        raise MT5ReadError(f"Falha ao conectar ao MT5: {mt5.last_error()}")

    try:
        terminal_info = mt5.terminal_info()
        if terminal_info is None or not bool(terminal_info.connected):
            raise MT5ReadError("MT5 aberto, mas sem conexao com o servidor.")

        account_info = mt5.account_info()
        account = {}
        if account_info is not None:
            for name in ("balance", "equity", "margin", "margin_free", "margin_level"):
                value = getattr(account_info, name, None)
                if value is not None:
                    account[name] = float(value)

        frames = {
            "M15": (mt5.TIMEFRAME_M15, 160),
            "M5": (mt5.TIMEFRAME_M5, 220),
            "M1": (mt5.TIMEFRAME_M1, 300),
            "D1": (mt5.TIMEFRAME_D1, 120),
        }
        bars: dict[str, list[dict]] = {}
        for name, (timeframe, count) in frames.items():
            bars[name] = _rates_to_bars(mt5.copy_rates_from_pos(symbol, timeframe, 0, count))
            if len(bars[name]) < 2:
                raise MT5ReadError(f"Historico insuficiente para {symbol} {name}.")

        weekly = _rates_to_bars(mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_W1, 0, 120))
        monthly = _rates_to_bars(mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_MN1, 0, 120))
        daily = bars["D1"]
        levels = build_context_levels(daily, weekly, monthly)
        zones = {"M15": build_daily_zones(daily)}

        tick = mt5.symbol_info_tick(symbol)
        last_price = float(tick.last) if tick is not None and tick.last > 0 else float(bars["M1"][-1]["close"])
        now = datetime.now(SAO_PAULO)
        version = mt5.version()
        source = f"MT5 local {version[0] if version else ''}".strip()
        macro_timeframes = {
            **{name: timeframe for name, (timeframe, _) in frames.items()},
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
        }
        macro_frames = {name: build_macro(mt5, symbol, timeframe) for name, timeframe in macro_timeframes.items()}
        macro_frames["W1"] = build_macro(mt5, symbol, mt5.TIMEFRAME_W1)
        macro_frames["MN1"] = build_macro(mt5, symbol, mt5.TIMEFRAME_MN1)
        macro = macro_frames["M15"]
        macro["frames"] = macro_frames
        return MarketSnapshot(
            symbol=symbol,
            as_of=now,
            last_price=last_price,
            connected=True,
            source=source,
            bars=bars,
            levels=levels,
            events=[PO3Event(now, "Leitura atualizada", "Candles D1, M15, M5 e M1 recebidos do MT5 local.")],
            zones=zones,
            notes=["Conexao somente leitura; credenciais nao sao solicitadas pelo painel."],
            account=account,
            macro=macro,
        )
    finally:
        mt5.shutdown()
