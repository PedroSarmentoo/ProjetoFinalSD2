"""Núcleo de rede do servidor.

Responsável: Pedro — issues #5, #6, #7, #8 e #9 (TLS na porta 5001: #20, com o Fellipe).

Contrato com a GUI (Bruna):
    fila = queue.Queue()
    servidor = ServidorChat(fila)
    servidor.iniciar()          # sobe as threads de aceitação e retorna
    ...                         # a GUI consome a fila (common/eventos.py)
    servidor.expulsar("ana")    # botão "Desconectar selecionado"
    servidor.parar()            # ao fechar a janela
"""

from __future__ import annotations

import queue

from common import config


class ServidorChat:
    def __init__(self, fila_eventos: queue.Queue, host: str = config.HOST,
                 porta: int = config.PORTA, porta_tls: int | None = config.PORTA_TLS):
        self.fila_eventos = fila_eventos
        self.host = host
        self.porta = porta
        self.porta_tls = porta_tls      # None = só a porta sem criptografia

    def iniciar(self) -> None:
        """Abre as portas e inicia as threads de aceitação (não bloqueia)."""
        raise NotImplementedError("issue #5 (Pedro)")

    def parar(self) -> None:
        """Envia BYE SERVER_SHUTDOWN a todos e fecha os sockets."""
        raise NotImplementedError("issue #8 (Pedro)")

    def expulsar(self, nome: str) -> None:
        """Desconecta um participante (BYE KICKED)."""
        raise NotImplementedError("issue #8 (Pedro)")
