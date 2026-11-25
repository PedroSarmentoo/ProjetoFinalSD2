"""Camada de rede do cliente humano.

Responsável: Pedro — issue #10.

Contrato com a GUI (Bruna):
    fila = queue.Queue()                       # recebe EnvelopeRecebido / ConexaoEncerrada
    rede = ClienteRede(fila)
    rede.conectar("ana", usar_tls=True)        # lança ErroConexao se falhar ou o nome for recusado
    id_msg = rede.enviar_sala("oi")            # cada envio devolve o id da mensagem
    id_msg = rede.enviar_privada("bruno", "oi")
    id_msg = rede.perguntar_bot("minha internet caiu")   # guardar para casar com o `ref` da resposta
    rede.sair()

Uma thread de recepção publica tudo na fila; os métodos de envio não
bloqueiam a interface.
"""

from __future__ import annotations

import queue

from common import config


class ErroConexao(Exception):
    """Falha ao conectar ou nome recusado (mensagem pronta para o usuário)."""


class ClienteRede:
    def __init__(self, fila: queue.Queue):
        self.fila = fila
        self.nome: str | None = None

    def conectar(self, nome: str, host: str = config.HOST, porta: int | None = None,
                 usar_tls: bool = False) -> None:
        """Sem `porta`, usa 5001 com TLS e 5000 sem."""
        raise NotImplementedError("issue #10 (Pedro)")

    def enviar_sala(self, texto: str) -> str:
        raise NotImplementedError("issue #10 (Pedro)")

    def enviar_privada(self, destinatario: str, texto: str) -> str:
        raise NotImplementedError("issue #10 (Pedro)")

    def perguntar_bot(self, pergunta: str) -> str:
        """Envia '@bot <pergunta>'; devolve o id usado como `ref` na resposta."""
        raise NotImplementedError("issue #10 (Pedro)")

    def sair(self) -> None:
        raise NotImplementedError("issue #10 (Pedro)")
