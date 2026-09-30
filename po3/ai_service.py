"""Cliente isolado para o OpenRouter.

Esta camada não conhece Streamlit, MT5, regras de mercado ou o chat visual.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv é opcional nesta primeira etapa
    load_dotenv = None


API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3.8-27b:free"

def configured_model_name() -> str:
    """Retorna o modelo configurado sem expor a chave da API."""
    return os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
DEFAULT_TIMEOUT_SECONDS = 30
FREE_MODEL_PRIORITY = (
    "inclusionai/ling-3.0-flash-fin:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nex-agi/nex-n2.5-pro:free",
    "nvidia/nemotron-3.5-lightning:free",
    "poolside/laguna-s-2.1:free",
    "nex-agi/nex-n2.5-mini:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "inclusionai/ling-3.0-flash-sante:free",
)


class OpenRouterError(RuntimeError):
    """Erro controlado da integração com o OpenRouter."""


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    model: str = DEFAULT_MODEL
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


def load_config() -> OpenRouterConfig:
    """Carrega configuração do ambiente sem expor ou armazenar a chave."""
    if load_dotenv is not None:
        load_dotenv(override=False)
    elif not os.getenv("OPENROUTER_API_KEY"):
        # Suporte mínimo a .env sem adicionar uma dependência nesta etapa.
        env_file = Path(__file__).resolve().parent.parent / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition("=")
                if separator and key.strip() in {"OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENROUTER_TIMEOUT_SECONDS"}:
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise OpenRouterError("OPENROUTER_API_KEY não configurada.")
    model = os.getenv("OPENROUTER_MODEL", FREE_MODEL_PRIORITY[0]).strip() or FREE_MODEL_PRIORITY[0]
    if not model.endswith(":free"):
        raise OpenRouterError("O PO3 Copilot aceita somente modelos gratuitos do OpenRouter.")
    raw_timeout = os.getenv("OPENROUTER_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        timeout = max(1, int(raw_timeout))
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SECONDS
    return OpenRouterConfig(api_key=api_key, model=model, timeout_seconds=timeout)


def _error_from_http(exc: HTTPError) -> OpenRouterError:
    if exc.code == 401:
        message = "OpenRouter rejeitou a API key (HTTP 401)."
    elif exc.code == 403:
        message = "OpenRouter recusou o acesso ao modelo (HTTP 403)."
    elif exc.code == 404:
        message = "Modelo ou endpoint não encontrado no OpenRouter (HTTP 404)."
    elif exc.code == 429:
        message = "Limite de requisições do OpenRouter atingido (HTTP 429)."
    else:
        message = f"OpenRouter retornou erro HTTP {exc.code}."
    try:
        detail = json.loads(exc.read().decode("utf-8", errors="replace"))
        api_message = detail.get("error", {}).get("message") if isinstance(detail, dict) else None
        if api_message:
            message += f" Detalhe: {api_message}"
    except Exception:
        pass
    return OpenRouterError(message)


def send_message(
    message: str,
    *,
    config: OpenRouterConfig | None = None,
    system_instruction: str | None = None,
) -> str:
    """Envia uma mensagem e retorna somente o texto produzido pelo modelo."""
    if not isinstance(message, str) or not message.strip():
        raise OpenRouterError("A mensagem para a IA não pode estar vazia.")
    config = config or load_config()
    messages = []
    if system_instruction and system_instruction.strip():
        messages.append({"role": "system", "content": system_instruction.strip()})
    messages.append({"role": "user", "content": message})
    ordered = [config.model] + [item for item in FREE_MODEL_PRIORITY if item != config.model]
    last_error: OpenRouterError | None = None
    body = None
    context = ssl.create_default_context()
    # O OpenRouter aceita no máximo três itens no array models. Usamos lotes
    # sequenciais para preservar toda a ordem sem gerar HTTP 400.
    for start in range(0, len(ordered), 4):
        batch = ordered[start:start + 4]
        payload = {"model": batch[0], "models": batch[1:4], "messages": messages, "max_tokens": 4000}
        request = Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
                "X-Title": "PO3 Copilot B3",
            },
        )
        try:
            with urlopen(request, timeout=config.timeout_seconds, context=context) as response:
                candidate = json.loads(response.read().decode("utf-8"))
            # Alguns provedores podem retornar choices sem conteúdo textual.
            # Nesse caso, não encerramos o fluxo: tentamos o próximo modelo gratuito.
            try:
                candidate_content = candidate["choices"][0]["message"].get("content")
            except (KeyError, IndexError, TypeError, AttributeError):
                candidate_content = None
            if isinstance(candidate_content, list):
                candidate_content = "".join(
                    str(part.get("text", "")) for part in candidate_content
                    if isinstance(part, dict)
                )
            if not isinstance(candidate_content, str) or not candidate_content.strip():
                last_error = OpenRouterError(f"O modelo {batch[0]} retornou uma mensagem vazia.")
                body = None
                continue
            body = candidate
            break
        except HTTPError as exc:
            last_error = _error_from_http(exc)
        except (TimeoutError, socket.timeout):
            last_error = OpenRouterError("Tempo limite excedido ao conectar ao OpenRouter.")
        except URLError as exc:
            last_error = OpenRouterError(f"Falha de conexão com o OpenRouter: {exc.reason}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            last_error = OpenRouterError("Resposta inválida recebida do OpenRouter.")
        except OSError as exc:
            last_error = OpenRouterError(f"Falha de rede ao consultar o OpenRouter: {exc}")
    if body is None:
        raise last_error or OpenRouterError("Nenhum modelo gratuito disponível no momento.")

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError("Resposta do OpenRouter sem conteúdo de mensagem válido.") from exc
    if not isinstance(content, str) or not content.strip():
        raise OpenRouterError("OpenRouter retornou uma mensagem vazia.")
    return content.strip()
