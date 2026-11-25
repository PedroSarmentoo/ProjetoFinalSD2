"""Camada de rede do bot.

Responsável: Pedro — issue #11.
Conecta como role "bot", recebe BOT_REQ e despacha cada pergunta para um
pool de threads, para uma consulta lenta não bloquear as outras:

    BOT_REQ (ref, on_behalf_of, pergunta)
        -> pool: historico.obter -> consultar_llm -> historico.registrar
        -> BOT_RESP (ou BOT_ERR com o code do ErroLLM), mesmo ref e usuário
"""

from __future__ import annotations

from common import config


class BotRede:
    def __init__(self, host: str = config.HOST, porta: int = config.PORTA,
                 usar_tls: bool = False, max_threads: int = 4):
        self.host = host
        self.porta = porta
        self.usar_tls = usar_tls
        self.max_threads = max_threads

    def executar(self) -> None:
        """Conecta e atende pedidos até o servidor encerrar (bloqueia)."""
        raise NotImplementedError("issue #11 (Pedro)")
