"""Camada de protocolo compartilhada (PROTOCOLO.md).

Responsável: Pedro — issue #4.
Este arquivo define a INTERFACE que servidor, cliente e bot usam. As
constantes e assinaturas abaixo já valem; os corpos marcados com
NotImplementedError serão preenchidos na issue #4.
"""

from __future__ import annotations

import socket
import time
import uuid

from common import config

# ------------------------------------------------------------------ tipos (PROTOCOLO.md §4)
HELLO, WELCOME, USERS, JOIN, LEAVE = "HELLO", "WELCOME", "USERS", "JOIN", "LEAVE"
MSG, BOT_REQ, BOT_RESP, BOT_ERR = "MSG", "BOT_REQ", "BOT_RESP", "BOT_ERR"
ERROR, BYE, PING, PONG = "ERROR", "BYE", "PING", "PONG"

TIPOS = {HELLO, WELCOME, USERS, JOIN, LEAVE, MSG, BOT_REQ, BOT_RESP, BOT_ERR, ERROR, BYE, PING, PONG}

TODOS = "*"
NOME_BOT = "bot"
NOME_SERVIDOR = "servidor"
NOMES_RESERVADOS = {"bot", "servidor", "todos", "*"}


class ErroProtocolo(Exception):
    """Mensagem inválida. `code` é um dos códigos da seção 6.2; `fatal` indica
    se a conexão deve ser encerrada depois de enviar o ERROR."""

    def __init__(self, code: str, mensagem: str, fatal: bool = False):
        super().__init__(mensagem)
        self.code = code
        self.fatal = fatal


def novo_id() -> str:
    return uuid.uuid4().hex


def novo_envelope(tipo: str, remetente: str, destinatario: str, conteudo="", **extras) -> dict:
    """Monta um envelope v1 com id e ts preenchidos. `extras`: ref, role,
    on_behalf_of, code."""
    env = {"v": config.VERSAO_PROTOCOLO, "type": tipo, "id": novo_id(),
           "from": remetente, "to": destinatario, "ts": time.time(), "content": conteudo}
    env.update({k: v for k, v in extras.items() if v is not None})
    return env


def codificar(envelope: dict) -> bytes:
    """Envelope → bytes prontos para sendall (JSON UTF-8 + \\n)."""
    raise NotImplementedError("issue #4 (Pedro)")


def validar(envelope: dict) -> None:
    """Confere campos obrigatórios e tipos; lança ErroProtocolo."""
    raise NotImplementedError("issue #4 (Pedro)")


def enviar(sock: socket.socket, envelope: dict) -> None:
    """Envia um envelope inteiro. Quem chama deve segurar o lock de envio
    daquele socket (PROTOCOLO.md / issue #6)."""
    raise NotImplementedError("issue #4 (Pedro)")


class LeitorDeMensagens:
    """Lê envelopes de um socket respeitando o framing por \\n.

    Uso:
        leitor = LeitorDeMensagens(sock)
        while (env := leitor.proximo()) is not None:
            ...
    `proximo()` devolve None quando a conexão é encerrada e lança
    ErroProtocolo para mensagem malformada ou acima do limite.
    """

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self._buffer = bytearray()

    def proximo(self) -> dict | None:
        raise NotImplementedError("issue #4 (Pedro)")
