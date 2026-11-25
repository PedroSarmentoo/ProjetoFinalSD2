"""Histórico curto e isolado por usuário.

Responsável: Bruna — issue #16.

Contrato:
    h = Historicos()                        # limite: config.HISTORICO_TROCAS trocas por usuário
    h.obter("ana")                          # -> cópia da lista no formato da API da LLM
    h.registrar("ana", pergunta, resposta)  # só depois de uma resposta com sucesso
    h.esquecer("ana")                       # opcional: apaga o contexto do usuário

Cada usuário tem a própria fila (deque com tamanho máximo): quando passa do
limite, a troca mais antiga sai sozinha. Assim a "Ana" nunca vê o contexto do
"Bruno" e o custo de cada chamada à LLM fica limitado.

Várias threads do bot usam o mesmo objeto ao mesmo tempo, por isso todo
acesso passa por um threading.Lock.
"""

from __future__ import annotations

import threading
from collections import deque

from common import config


class Historicos:
    def __init__(self, trocas: int | None = None):
        self.trocas = config.HISTORICO_TROCAS if trocas is None else trocas
        self._lock = threading.Lock()
        self._por_usuario: dict[str, deque] = {}

    def obter(self, usuario: str) -> list[dict]:
        """Cópia do histórico (a thread que chama pode usá-la sem o lock)."""
        with self._lock:
            return list(self._por_usuario.get(usuario.lower(), ()))

    def registrar(self, usuario: str, pergunta: str, resposta: str) -> None:
        with self._lock:
            fila = self._por_usuario.setdefault(usuario.lower(), deque(maxlen=self.trocas * 2))
            fila.append({"role": "user", "content": pergunta})
            fila.append({"role": "assistant", "content": resposta})

    def esquecer(self, usuario: str) -> None:
        with self._lock:
            self._por_usuario.pop(usuario.lower(), None)

    def usuarios(self) -> list[str]:
        with self._lock:
            return sorted(self._por_usuario)
