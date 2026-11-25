"""Contrato entre a REDE e as INTERFACES (Pedro ↔ Bruna) — issue #9.

A rede nunca mexe nos widgets do tkinter (ele não é thread-safe). Em vez
disso, publica objetos destes tipos numa queue.Queue, e a GUI consome a
fila com root.after(...).

Servidor  → GUI do servidor: ParticipanteEntrou, ParticipanteSaiu,
                              MensagemTrafegada, EventoServidor, StatusServidor
Cliente   → GUI do cliente:   EnvelopeRecebido, ConexaoEncerrada
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time


# ------------------------------------------------------------------ servidor
@dataclass
class ParticipanteEntrou:
    nome: str
    papel: str            # "human" | "bot"
    endereco: str         # "127.0.0.1:53122"
    canal: str            # "TCP :5000" | "TLS :5001"
    desde: float = field(default_factory=time.time)


@dataclass
class ParticipanteSaiu:
    nome: str
    motivo: str           # LEFT | CONNECTION_LOST | KICKED


@dataclass
class MensagemTrafegada:
    envelope: dict        # envelope completo, como passou pelo servidor


@dataclass
class EventoServidor:
    nivel: str            # "info" | "join" | "leave" | "bot" | "erro"
    texto: str
    quando: float = field(default_factory=time.time)


@dataclass
class StatusServidor:
    conectados: int
    pendentes_bot: int
    bot_online: bool


# ------------------------------------------------------------------ cliente
@dataclass
class EnvelopeRecebido:
    envelope: dict


@dataclass
class ConexaoEncerrada:
    motivo: str           # texto para mostrar ao usuário
