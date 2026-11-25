"""Contextos TLS do servidor e do cliente.

Responsável: Fellipe — issues #19 e #20.

Como é usado pelo resto do código:

    ctx = contexto_servidor()                              # servidor, porta 5001
    sock_tls = ctx.wrap_socket(conexao, server_side=True)

    ctx = contexto_cliente()                               # cliente/bot com "TLS"
    sock_tls = ctx.wrap_socket(sock, server_hostname="127.0.0.1")

Validação do certificado (exigência do edital) — feita pelo CLIENTE:
  1. verify_mode = CERT_REQUIRED: o servidor É OBRIGADO a apresentar um
     certificado, e a cadeia precisa terminar na CA em que o cliente confia
     (certs/ca.crt). Certificado de outra origem -> conexão recusada.
  2. check_hostname = True: o nome/IP usado para conectar (server_hostname)
     precisa constar no SAN do certificado (localhost, 127.0.0.1).
  3. VERIFY_X509_STRICT: rejeita certificados malformados (regras RFC 5280).
  4. TLS 1.2 como versão mínima (na prática negocia TLS 1.3).
É proibido usar CERT_NONE ou check_hostname=False.

Onde a mensagem é cifrada e decifrada:
  cliente → [cifra no wrap_socket do cliente] → rede (bytes ilegíveis)
          → [decifra no wrap_socket do servidor, na thread daquele cliente] → servidor
  Ou seja, o TLS protege o ENLACE cliente↔servidor. Dentro do servidor a
  mensagem está em claro (ele precisa ler o envelope para rotear). Se o
  destinatário estiver na porta 5001, ela é cifrada de novo no enlace dele.
"""

from __future__ import annotations

import ssl
from pathlib import Path

from common import config

DICA = "Gere os certificados com:  python certs/gerar_certificados.py"


def _exigir(arquivo: Path) -> None:
    if not Path(arquivo).is_file():
        raise FileNotFoundError(f"arquivo {arquivo} não encontrado. {DICA}")


def contexto_servidor(certfile: Path = config.CERT_SERVIDOR,
                      keyfile: Path = config.CHAVE_SERVIDOR) -> ssl.SSLContext:
    """Contexto do servidor: apresenta servidor.crt e prova que tem servidor.key."""
    _exigir(certfile)
    _exigir(keyfile)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=str(certfile), keyfile=str(keyfile))
    return ctx


def contexto_cliente(cafile: Path = config.CERT_CA) -> ssl.SSLContext:
    """Contexto do cliente: só confia em servidores com certificado assinado pela CA."""
    _exigir(cafile)
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(cafile))
    ctx.verify_mode = ssl.CERT_REQUIRED          # (já é o padrão — deixado explícito de propósito)
    ctx.check_hostname = True
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.verify_flags |= ssl.VERIFY_X509_STRICT
    return ctx


def descrever(sock) -> str:
    """Resumo da sessão TLS para logs e para a GUI. Ex.: 'TLSv1.3 · TLS_AES_256_GCM_SHA384'."""
    try:
        versao = sock.version()
        cifra = sock.cipher()
    except (AttributeError, ssl.SSLError, OSError):
        return "sem TLS"
    if not versao:
        return "sem TLS"
    return f"{versao} · {cifra[0]}" if cifra else versao
