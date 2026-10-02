"""Cliente isolado da Decisions API do Jev Shadow."""
from __future__ import annotations

import json
import os
import socket
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

JEV_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
JEV_MODEL = "typesafe/jev-1.13"


class JevError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, error_type: str = "JEV_ERROR"):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


@dataclass(frozen=True)
class JevConfig:
    api_key: str
    model: str = JEV_MODEL
    timeout_seconds: int = 30


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv(override=False)
        return
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in {"OPENROUTER_JEV_API_KEY", "JEV_MODEL", "JEV_TIMEOUT_SECONDS"}:
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_jev_config() -> JevConfig:
    _load_env()
    key = os.getenv("OPENROUTER_JEV_API_KEY", "").strip()
    if not key:
        raise JevError("OPENROUTER_JEV_API_KEY não configurada.", error_type="CONFIG_MISSING")
    model = os.getenv("JEV_MODEL", JEV_MODEL).strip() or JEV_MODEL
    if model != JEV_MODEL:
        raise JevError(f"Modelo Jev inválido: esperado {JEV_MODEL}.", error_type="CONFIG_INVALID")
    try:
        timeout = max(1, int(os.getenv("JEV_TIMEOUT_SECONDS", "30")))
    except ValueError:
        timeout = 30
    return JevConfig(key, model, timeout)


def _http_error(exc: HTTPError) -> JevError:
    detail = ""
    try:
        body = json.loads(exc.read().decode("utf-8", errors="replace"))
        if isinstance(body, dict):
            value = body.get("error")
            detail = value.get("message", "") if isinstance(value, dict) else str(value or "")
    except Exception:
        pass
    suffix = f": {detail}" if detail else ""
    labels = {401: "JEV_UNAUTHORIZED", 403: "JEV_FORBIDDEN", 404: "JEV_NOT_FOUND", 429: "JEV_RATE_LIMIT"}
    return JevError(f"{labels.get(exc.code, f'JEV_HTTP_{exc.code}')}{suffix}", status_code=exc.code,
                    error_type=labels.get(exc.code, "JEV_HTTP_ERROR"))


def _normalize_answers(payload: dict) -> list[dict]:
    answers = payload.get("answers")
    if isinstance(answers, dict):
        answers = [{"decision_id": key, **(value if isinstance(value, dict) else {"answer": value})}
                   for key, value in answers.items()]
    if not isinstance(answers, list) or len(answers) != 6:
        raise JevError("Resposta Jev não contém exatamente seis respostas.", error_type="INVALID_ANSWER_SHAPE")
    return answers


def send_jev_decisions(state: dict, questions: dict, *, config: JevConfig | None = None) -> dict:
    config = config or load_jev_config()
    started = time.monotonic()
    payload = {"model": config.model, "state": state, "questions": questions}
    request = Request(JEV_ENDPOINT, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
                      headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json",
                               "X-Title": "PO3 Copilot O5A Jev Shadow"})
    try:
        with urlopen(request, timeout=config.timeout_seconds, context=ssl.create_default_context()) as response:
            raw = json.loads(response.read().decode("utf-8"))
            status = getattr(response, "status", 200)
    except HTTPError as exc:
        raise _http_error(exc) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise JevError("Tempo limite da Decisions API.", error_type="TIMEOUT") from exc
    except URLError as exc:
        raise JevError(f"Falha de rede da Decisions API: {exc.reason}", error_type="NETWORK_ERROR") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JevError("JSON inválido recebido da Decisions API.", error_type="INVALID_JSON") from exc
    except OSError as exc:
        raise JevError(f"Falha de rede da Decisions API: {exc}", error_type="NETWORK_ERROR") from exc
    if not isinstance(raw, dict):
        raise JevError("Resposta Jev não é um objeto JSON.", error_type="INVALID_JSON")
    answers = _normalize_answers(raw)
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    return {"model_configured": config.model, "model_used": raw.get("model") or config.model,
            "provider": raw.get("provider", "openrouter"), "answers": answers,
            "input_tokens": usage.get("input_tokens", usage.get("prompt_tokens")),
            "output_tokens": usage.get("output_tokens", usage.get("completion_tokens")),
            "cost_usd": usage.get("cost", raw.get("cost_usd")),
            "duration_seconds": round(time.monotonic() - started, 3),
            "request_id": raw.get("id") or raw.get("request_id"), "http_status": status,
            "raw_response": raw}
