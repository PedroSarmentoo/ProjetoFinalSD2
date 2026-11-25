"""Histórico curto e isolado por usuário.

Responsável: Bruna — issue #16.
Contrato:
    h = Historicos()                      # limite: config.HISTORICO_TROCAS trocas
    h.obter("ana")                        # -> lista no formato da API
    h.registrar("ana", pergunta, resposta)
Usado por várias threads ao mesmo tempo: proteger com threading.Lock.
"""

from __future__ import annotations

from common import config


class Historicos:
    def __init__(self, trocas: int = config.HISTORICO_TROCAS):
        raise NotImplementedError("issue #16 (Bruna)")

    def obter(self, usuario: str) -> list[dict]:
        raise NotImplementedError("issue #16 (Bruna)")

    def registrar(self, usuario: str, pergunta: str, resposta: str) -> None:
        raise NotImplementedError("issue #16 (Bruna)")
