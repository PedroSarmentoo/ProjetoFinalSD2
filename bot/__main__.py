"""Ponto de entrada: python -m bot   (processo separado; precisa do servidor rodando)

    python -m bot                          # conecta pela porta 5000
    python -m bot --tls                    # conecta pela porta TLS (5001)
    python -m bot --simular-falha timeout  # demonstração (#17): a LLM real estoura o tempo limite
    python -m bot --simular-falha chave    # demonstração (#17): a LLM real recusa a chave (401)

As falhas simuladas fazem uma chamada DE VERDADE ao Groq em condições ruins
(tempo limite de 0,01 s ou chave inválida). O erro que volta é real, e o
usuário recebe um BOT_ERR sem que o sistema caia.
"""

import argparse
import sys

from bot.rede import BotRede, ErroBot
from common import config


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot do chat SD2")
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--simular-falha", choices=["timeout", "chave"])
    opcoes = parser.parse_args()

    print(f".env: {config.ARQUIVO_ENV or 'NÃO ENCONTRADO (crie o .env na raiz do projeto)'}")
    if opcoes.simular_falha == "timeout":
        config.LLM_TIMEOUT = 0.01
        print("MODO DEMONSTRAÇÃO: tempo limite da LLM = 0,01 s -> as perguntas recebem LLM_TIMEOUT.")
    elif opcoes.simular_falha == "chave":
        config.LLM_API_KEY = "gsk_chave_invalida_para_demonstracao"
        print("MODO DEMONSTRAÇÃO: chave da LLM inválida -> as perguntas recebem LLM_AUTH.")
    elif not config.LLM_API_KEY:
        print("AVISO: LLM_API_KEY vazia — o bot vai responder com erro LLM_AUTH.")

    bot = BotRede(usar_tls=opcoes.tls)
    try:
        bot.executar()
    except ErroBot as e:
        print(f"ERRO: {e}")
        try:
            input("Pressione Enter para fechar...")
        except EOFError:
            pass
        sys.exit(1)
    except KeyboardInterrupt:
        bot.parar()


if __name__ == "__main__":
    main()
