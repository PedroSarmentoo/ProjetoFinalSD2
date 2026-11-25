"""Contextos TLS do servidor e do cliente.

Responsável: Fellipe — issues #19 e #20.
Contrato usado pelo resto do código:

    ctx = contexto_servidor()                  # servidor, porta 5001
    sock_tls = ctx.wrap_socket(conexao, server_side=True)

    ctx = contexto_cliente()                   # cliente que marcou "TLS"
    sock_tls = ctx.wrap_socket(sock, server_hostname="localhost")

Regras do edital: o cliente VALIDA explicitamente o certificado
(verify_mode=CERT_REQUIRED, check_hostname=True). Proibido CERT_NONE.
"""

from __future__ import annotations

import ssl
from pathlib import Path

from common import config


def contexto_servidor(certfile: Path = config.CERT_SERVIDOR,
                      keyfile: Path = config.CHAVE_SERVIDOR) -> ssl.SSLContext:
    raise NotImplementedError("issue #19 (Fellipe)")


def contexto_cliente(cafile: Path = config.CERT_CA) -> ssl.SSLContext:
    raise NotImplementedError("issue #19 (Fellipe)")
