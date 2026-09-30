from __future__ import annotations

from dataclasses import dataclass

from .models import MarketSnapshot, PriceLevel


@dataclass(frozen=True)
class ChecklistState:
    context_ok: bool
    sweep_ok: bool
    mss_ok: bool
    poi_ok: bool
    retest_ok: bool
    rr_ok: bool


def status_from_checklist(state: ChecklistState) -> tuple[str, str]:
    checks = [
        state.context_ok,
        state.sweep_ok,
        state.mss_ok,
        state.poi_ok,
        state.retest_ok,
        state.rr_ok,
    ]
    completed = sum(checks)
    if completed == len(checks):
        return "VERDE", "Setup completo para avaliacao manual"
    if completed >= 2:
        return "AMARELO", f"Aguardar confirmacoes ({completed}/{len(checks)})"
    return "VERMELHO", "Sem setup confirmado"


def calculate_rr(direction: str, entry: float, stop: float, target: float) -> float | None:
    direction = direction.lower().strip()
    if direction == "compra":
        risk = entry - stop
        reward = target - entry
    elif direction == "venda":
        risk = stop - entry
        reward = entry - target
    else:
        raise ValueError("Direcao deve ser compra ou venda.")
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def find_level(snapshot: MarketSnapshot, code: str) -> PriceLevel | None:
    for levels in snapshot.levels.values():
        for level in levels:
            if level.code == code:
                return level
    return None


def context_messages(snapshot: MarketSnapshot) -> list[str]:
    messages: list[str] = []
    comparisons = [
        ("PW50", "equilibrio semanal"),
        ("PM50", "equilibrio mensal"),
        ("PD50", "equilibrio diario"),
    ]
    for code, label in comparisons:
        level = find_level(snapshot, code)
        if level is None:
            continue
        side = "acima" if snapshot.last_price >= level.value else "abaixo"
        messages.append(f"Preco {side} do {label} ({level.value:,.0f}).")
    return messages
