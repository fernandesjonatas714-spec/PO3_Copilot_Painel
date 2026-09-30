"""Cliente isolado do OpenRouter, sem lógica de interface ou execução de ordens."""
from __future__ import annotations
import json, os, socket, ssl, time
from pathlib import Path
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3.8-27b:free"
DEFAULT_TIMEOUT_SECONDS = 30
FREE_MODEL_PRIORITY = (
    "google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free",
    "inclusionai/ling-3.0-flash-fin:free", "nex-agi/nex-n2.5-mini:free",
    "nex-agi/nex-n2.5-pro:free", "inclusionai/ling-3.0-flash-sante:free",
    "nvidia/nemotron-3.5-lightning:free", "nvidia/nemotron-3-ultra-550b-a55b:free",
    "poolside/laguna-s-2.1:free",
)

class OpenRouterError(RuntimeError):
    """Falha controlada de comunicação com o OpenRouter."""

@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    model: str = DEFAULT_MODEL
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

def _load_dotenv_fallback() -> None:
    if load_dotenv is not None:
        load_dotenv(override=False)
        return
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in {"OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENROUTER_TIMEOUT_SECONDS", "DECISION_ENGINE_ENABLED"}:
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

def configured_model_name() -> str:
    _load_dotenv_fallback()
    return os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

def load_config() -> OpenRouterConfig:
    _load_dotenv_fallback()
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise OpenRouterError("OPENROUTER_API_KEY não configurada.")
    model = configured_model_name()
    if not model.endswith(":free"):
        raise OpenRouterError("O PO3 Copilot aceita somente modelos gratuitos do OpenRouter.")
    try: timeout = max(1, int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))))
    except ValueError: timeout = DEFAULT_TIMEOUT_SECONDS
    return OpenRouterConfig(key, model, timeout)

def _error_from_http(exc: HTTPError) -> OpenRouterError:
    labels = {401:"API key rejeitada",403:"acesso ao modelo recusado",404:"modelo ou endpoint não encontrado",429:"limite de requisições atingido"}
    message = f"OpenRouter: {labels.get(exc.code, f'erro HTTP {exc.code}')}"
    try:
        detail=json.loads(exc.read().decode("utf-8", errors="replace")); api_message=detail.get("error",{}).get("message") if isinstance(detail,dict) else None
        if api_message: message += f". Detalhe: {api_message}"
    except Exception: pass
    return OpenRouterError(message)

def send_message_detailed(message: str, *, config: OpenRouterConfig | None = None, system_instruction: str | None = None) -> dict:
    """Retorna conteúdo e metadados seguros, incluindo o modelo que respondeu."""
    if not isinstance(message, str) or not message.strip(): raise OpenRouterError("A mensagem para a IA não pode estar vazia.")
    config=config or load_config(); messages=[]
    if system_instruction and system_instruction.strip(): messages.append({"role":"system","content":system_instruction.strip()})
    messages.append({"role":"user","content":message})
    ordered=[config.model]+[x for x in FREE_MODEL_PRIORITY if x != config.model]
    last_error=None; started=time.monotonic(); attempts=[]; context=ssl.create_default_context()
    for start in range(0,len(ordered),4):
        batch=ordered[start:start+4]; attempts.extend(batch)
        payload={"model":batch[0],"models":batch[1:4],"messages":messages,"max_tokens":4000}
        request=Request(API_URL,data=json.dumps(payload).encode("utf-8"),method="POST",headers={"Authorization":f"Bearer {config.api_key}","Content-Type":"application/json","X-Title":"PO3 Copilot B3"})
        try:
            with urlopen(request,timeout=config.timeout_seconds,context=context) as response: candidate=json.loads(response.read().decode("utf-8"))
            raw=candidate.get("choices",[{}])[0].get("message",{}).get("content")
            if isinstance(raw,list): raw="".join(str(x.get("text","")) for x in raw if isinstance(x,dict))
            if not isinstance(raw,str) or not raw.strip(): last_error=OpenRouterError(f"O modelo {batch[0]} retornou uma mensagem vazia."); continue
            used=str(candidate.get("model") or batch[0]); return {"content":raw.strip(),"model_configured":config.model,"model_used":used,"fallback_used":used!=config.model,"duration_seconds":round(time.monotonic()-started,3),"attempts":attempts}
        except HTTPError as exc: last_error=_error_from_http(exc)
        except (TimeoutError,socket.timeout): last_error=OpenRouterError("Tempo limite excedido ao conectar ao OpenRouter.")
        except URLError as exc: last_error=OpenRouterError(f"Falha de conexão com o OpenRouter: {exc.reason}")
        except (json.JSONDecodeError,UnicodeDecodeError): last_error=OpenRouterError("Resposta inválida recebida do OpenRouter.")
        except OSError as exc: last_error=OpenRouterError(f"Falha de rede ao consultar o OpenRouter: {exc}")
    raise last_error or OpenRouterError("Nenhum modelo gratuito disponível no momento.")

def send_message(message: str, *, config: OpenRouterConfig | None = None, system_instruction: str | None = None) -> str:
    return send_message_detailed(message, config=config, system_instruction=system_instruction)["content"]