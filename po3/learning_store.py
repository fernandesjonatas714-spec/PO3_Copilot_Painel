"""Persistência local das análises para acompanhamento futuro.

O banco é somente um diário de evidências: não altera prompts, modelos ou regras.
"""
from __future__ import annotations

from datetime import datetime
from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any


DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "po3_learning.sqlite"


def _json(value: Any) -> str:
    try:
        # asdict() pode recursar indefinidamente quando um objeto do snapshot
        # contém uma referência circular. A persistência não pode interromper
        # uma análise já concluída.
        if is_dataclass(value):
            value = asdict(value)
        return json.dumps(value, ensure_ascii=False, default=str)
    except (RecursionError, ValueError, TypeError):
        return json.dumps(
            {"status": "conteúdo omitido", "motivo": "referência circular ou objeto não serializável"},
            ensure_ascii=False,
        )


def initialize(db_path: str | Path = DEFAULT_DB) -> Path:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                symbol TEXT NOT NULL,
                price REAL,
                bias TEXT,
                response TEXT NOT NULL,
                context_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER NOT NULL,
                observed_at TEXT NOT NULL,
                future_price REAL,
                movement REAL,
                observed_bias TEXT,
                notes TEXT,
                FOREIGN KEY (analysis_id) REFERENCES analysis_runs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_analysis_created_at ON analysis_runs(created_at);
            CREATE INDEX IF NOT EXISTS idx_outcomes_analysis_id ON outcomes(analysis_id);
            CREATE TABLE IF NOT EXISTS ai_error_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                operation TEXT NOT NULL,
                error_type TEXT NOT NULL,
                message TEXT NOT NULL,
                recovery TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ai_error_created_at ON ai_error_events(created_at);
            """
        )
    return path


def save_analysis(snapshot: Any, context: dict, response: str, db_path: str | Path = DEFAULT_DB) -> int:
    """Salva uma análise concluída e retorna seu identificador local."""
    path = initialize(db_path)
    macro = getattr(snapshot, "macro", {}) or {}
    bias = macro.get("bias") or macro.get("direction") or "não classificado"
    with sqlite3.connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO analysis_runs (created_at, symbol, price, bias, response, context_json, snapshot_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (datetime.now().astimezone().isoformat(), getattr(snapshot, "symbol", ""),
             getattr(snapshot, "last_price", None), str(bias), str(response), _json(context), _json(snapshot)),
        )
        return int(cursor.lastrowid)


def record_ai_error(operation: str, error_type: str, message: str, recovery: str,
                    db_path: str | Path = DEFAULT_DB) -> int:
    """Registra uma falha e a recuperação aplicada, sem guardar segredos."""
    try:
        path = initialize(db_path)
    except sqlite3.Error:
        # O diário de erros nunca pode interromper a análise principal.
        return -1
    safe_message = str(message)
    for secret in ("OPENROUTER_API_KEY", "Authorization", "Bearer"):
        if secret.lower() in safe_message.lower():
            safe_message = "detalhe protegido"
            break
    try:
        with sqlite3.connect(path) as conn:
            cursor = conn.execute(
                "INSERT INTO ai_error_events (created_at, operation, error_type, message, recovery) VALUES (?, ?, ?, ?, ?)",
                (datetime.now().astimezone().isoformat(), str(operation), str(error_type), safe_message, str(recovery)),
            )
            return int(cursor.lastrowid)
    except sqlite3.Error:
        return -1


def record_outcome(analysis_id: int, future_price: float | None, movement: float | None,
                   observed_bias: str | None, notes: str = "", db_path: str | Path = DEFAULT_DB) -> None:
    path = initialize(db_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO outcomes (analysis_id, observed_at, future_price, movement, observed_bias, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (analysis_id, datetime.now().astimezone().isoformat(), future_price, movement, observed_bias, notes),
        )

def recent_analyses(limit: int = 10, db_path: str | Path = DEFAULT_DB) -> list[dict[str, Any]]:
    """Retorna um resumo local das análises, sem expor segredos."""
    try:
        path = initialize(db_path)
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT id, created_at, symbol, price, bias, response, context_json FROM analysis_runs ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 100)),)).fetchall()
        result=[]
        for row in rows:
            structured={}
            try: structured=json.loads(row["context_json"]).get("_structured", {})
            except (TypeError, ValueError, json.JSONDecodeError): pass
            decisions={x.get("id_decisao"):x.get("decisao") for x in structured.get("decisoes",[]) if isinstance(x,dict)}
            result.append({"id":row["id"],"data_hora":row["created_at"],"ativo":row["symbol"],"preco":row["price"],"vies":row["bias"],"regime_macro":decisions.get("regime_macro","—"),"contexto_tecnico":decisions.get("contexto_tecnico","—"),"contexto_operacional":decisions.get("contexto_operacional","—"),"status":structured.get("gate",{}).get("status","—"),"modelo":structured.get("modelo_utilizado","—"),"resposta":row["response"]})
        return result
    except (sqlite3.Error, OSError, ValueError):
        return []