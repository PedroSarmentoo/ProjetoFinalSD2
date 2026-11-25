"""Ponto de entrada: python -m bot   (processo separado; precisa do servidor rodando)

    python -m bot          # conecta pela porta 5000
    python -m bot --tls    # conecta pela porta TLS (5001)
"""

import sys

from bot.rede import BotRede, ErroBot
from common import config


def main() -> None:
    usar_tls = "--tls" in sys.argv
    print(f".env: {config.ARQUIVO_ENV or 'NÃO ENCONTRADO (crie o .env na raiz do projeto)'}")
    if not config.LLM_API_KEY:
        print("AVISO: LLM_API_KEY vazia — o bot vai responder com erro LLM_AUTH.")
    bot = BotRede(usar_tls=usar_tls)
    try:
        bot.executar()
    except ErroBot as e:
        print(f"ERRO: {e}")
        input("Pressione Enter para fechar...")
        sys.exit(1)
    except KeyboardInterrupt:
        bot.parar()


if __name__ == "__main__":
    main()
