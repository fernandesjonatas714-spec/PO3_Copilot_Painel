"""Teste isolado da conexão com o OpenRouter; não usa o painel visual."""
from po3.ai_service import OpenRouterError, send_message


TEST_MESSAGE = "Responda apenas: conexão com IA funcionando."


def main() -> int:
    try:
        response = send_message(TEST_MESSAGE)
    except OpenRouterError as exc:
        print(f"ERRO: {exc}")
        return 1
    print(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
