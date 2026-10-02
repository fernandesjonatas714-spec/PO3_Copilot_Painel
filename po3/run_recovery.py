"""Regras comuns para recuperação segura de execuções interrompidas."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# Margem suficiente para uma chamada legítima, além do TTL nominal do AI worker.
ORPHAN_RUN_STALE_SECONDS = 180


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def run_is_recoverable(
    db_path: str | Path,
    row: Any,
    *,
    status: str,
    worker_owner_id: str | None = None,
    stale_timeout_seconds: int = ORPHAN_RUN_STALE_SECONDS,
    timestamp_column: str = "created_at_utc",
) -> bool:
    """Retorna se uma execução em andamento pode ser retomada.

    Um run ainda pertencente ao lease atual nunca é assumido. Runs legados sem
    proprietário também permanecem protegidos enquanto houver lease ativo;
    depois do vencimento e do timeout de segurança podem ser recuperados.
    """
    if row["status"] != status:
        return False
    row_owner = row["worker_owner_id"] if "worker_owner_id" in row.keys() else None
    if worker_owner_id and row_owner == worker_owner_id:
        return False
    now = datetime.now(timezone.utc)
    with sqlite3.connect(Path(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        lease = conn.execute(
            "SELECT owner_id, expires_at FROM collector_leases "
            "WHERE collector_name='po3-ai' AND symbol=?",
            (row["symbol"],),
        ).fetchone()
    lease_expiry = _parse_utc(lease["expires_at"] if lease else None)
    if lease_expiry and lease_expiry > now:
        # Um proprietário diferente indica que o lease anterior já foi perdido
        # e um novo worker assumiu; proprietário ausente é legado e fica seguro.
        if row_owner and lease["owner_id"] != row_owner:
            return True
        if row_owner:
            return False
        created = _parse_utc(row[timestamp_column] if timestamp_column in row.keys() else None)
        return bool(created and now - created >= timedelta(seconds=max(1, int(stale_timeout_seconds))))
    created = _parse_utc(row[timestamp_column] if timestamp_column in row.keys() else None)
    if created is None:
        return False
    return now - created >= timedelta(seconds=max(1, int(stale_timeout_seconds)))
