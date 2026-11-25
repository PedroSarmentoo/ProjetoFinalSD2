"""Camada de protocolo compartilhada por servidor, cliente e bot (PROTOCOLO.md).

Responsável: Pedro — issue #4.

Resumo do que este módulo garante:
  * framing: uma mensagem = um JSON UTF-8 terminado em "\\n" (§2);
  * limite de 64 KiB por mensagem (§2);
  * validação do envelope e dos campos de cada tipo (§3 e §4);
  * regras de identificação usadas pelo servidor: nomes (§6.1) e o
    prefixo "@bot" (§5.3).

Uso típico:
    leitor = LeitorDeMensagens(sock)
    while (env := leitor.proximo()) is not None:      # None = conexão encerrada
        ...
    enviar(sock, novo_envelope(MSG, "ana", TODOS, "oi"))
"""

from __future__ import annotations

import json
import re
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
PAPEIS = {"human", "bot"}

# Campos extras obrigatórios por tipo (além do envelope comum).
_CAMPOS_EXTRAS = {
    HELLO: ("role",),
    BOT_REQ: ("ref", "on_behalf_of"),
    BOT_RESP: ("ref",),
    BOT_ERR: ("ref", "code"),
    ERROR: ("code",),
    LEAVE: ("code",),
    PONG: ("ref",),
}
# Tipos cujo `content` não pode ser vazio.
_CONTEUDO_OBRIGATORIO = {MSG, BOT_REQ, BOT_RESP, BOT_ERR, ERROR}

_REGEX_NOME = re.compile(r"[A-Za-z0-9_-]{1,20}")
_REGEX_BOT = re.compile(r"@bot(?:\s+|$)", re.IGNORECASE)
_TAMANHO_RECV = 4096


class ErroProtocolo(Exception):
    """Mensagem inválida.

    code  — um dos códigos da seção 6.2 (BAD_MESSAGE, MSG_TOO_LARGE...);
    fatal — True se a conexão deve ser encerrada depois de enviar o ERROR;
    ref   — id da mensagem que causou o erro, quando foi possível lê-lo.
    """

    def __init__(self, code: str, mensagem: str, fatal: bool = False, ref: str | None = None):
        super().__init__(mensagem)
        self.code = code
        self.fatal = fatal
        self.ref = ref


# ------------------------------------------------------------------ construção
def novo_id() -> str:
    return uuid.uuid4().hex


def novo_envelope(tipo: str, remetente: str, destinatario: str, conteudo="", **extras) -> dict:
    """Monta um envelope v1 com `id` e `ts` preenchidos.

    `extras`: ref, role, on_behalf_of, code (valores None são omitidos).
    """
    env = {"v": config.VERSAO_PROTOCOLO, "type": tipo, "id": novo_id(),
           "from": remetente, "to": destinatario, "ts": time.time(), "content": conteudo}
    env.update({k: v for k, v in extras.items() if v is not None})
    return env


# ------------------------------------------------------------------ validação
def validar(envelope) -> dict:
    """Confere o envelope (§3) e os campos do tipo (§4). Devolve o próprio
    envelope ou lança ErroProtocolo."""
    if not isinstance(envelope, dict):
        raise ErroProtocolo("BAD_MESSAGE", "a mensagem precisa ser um objeto JSON")

    ref = envelope.get("id") if isinstance(envelope.get("id"), str) else None

    def erro(code, texto, fatal=False):
        return ErroProtocolo(code, texto, fatal=fatal, ref=ref)

    if "v" not in envelope:
        raise erro("BAD_MESSAGE", "campo 'v' ausente")
    if envelope["v"] != config.VERSAO_PROTOCOLO or isinstance(envelope["v"], bool):
        raise erro("VERSION_UNSUPPORTED",
                   f"versão {envelope['v']!r} não suportada (esperado {config.VERSAO_PROTOCOLO})",
                   fatal=True)

    for campo in ("type", "id", "from", "to"):
        valor = envelope.get(campo)
        if not isinstance(valor, str) or not valor:
            raise erro("BAD_MESSAGE", f"campo '{campo}' ausente ou não é texto")
    if len(envelope["id"]) > 64:
        raise erro("BAD_MESSAGE", "campo 'id' longo demais")

    ts = envelope.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        raise erro("BAD_MESSAGE", "campo 'ts' ausente ou não é número")

    tipo = envelope["type"]
    if tipo not in TIPOS:
        raise erro("UNKNOWN_TYPE", f"tipo desconhecido: {tipo!r}")

    if "content" not in envelope:
        raise erro("BAD_MESSAGE", "campo 'content' ausente")
    conteudo = envelope["content"]
    if tipo == USERS:
        if not isinstance(conteudo, list) or not all(isinstance(n, str) for n in conteudo):
            raise erro("BAD_MESSAGE", "USERS precisa de uma lista de nomes em 'content'")
    elif not isinstance(conteudo, str):
        raise erro("BAD_MESSAGE", "campo 'content' precisa ser texto")
    elif tipo in _CONTEUDO_OBRIGATORIO and not conteudo.strip():
        raise erro("BAD_MESSAGE", f"{tipo} com 'content' vazio")

    for campo in _CAMPOS_EXTRAS.get(tipo, ()):
        valor = envelope.get(campo)
        if not isinstance(valor, str) or not valor:
            raise erro("BAD_MESSAGE", f"{tipo} exige o campo '{campo}'")
    if tipo == HELLO and envelope["role"] not in PAPEIS:
        raise erro("BAD_MESSAGE", f"role inválido: {envelope['role']!r}")

    return envelope


def validar_nome(nome: str, papel: str = "human") -> str | None:
    """Regras de §6.1. Devolve None se o nome for aceitável ou o código do
    problema (NAME_INVALID / NAME_RESERVED). Unicidade é checada pelo servidor."""
    if papel == "bot":
        return None if nome == NOME_BOT else "NAME_INVALID"
    if not isinstance(nome, str) or not _REGEX_NOME.fullmatch(nome):
        return "NAME_INVALID"
    if nome.lower() in NOMES_RESERVADOS:
        return "NAME_RESERVED"
    return None


def extrair_pergunta_bot(texto: str) -> str | None:
    """Regra de §5.3. Devolve a pergunta (sem o '@bot') se o texto for uma
    pergunta ao bot — pode ser "" quando é só '@bot' — ou None se não for."""
    texto = texto.lstrip()
    m = _REGEX_BOT.match(texto)
    if not m:
        return None
    return texto[m.end():].strip()


# ------------------------------------------------------------------ envio
def codificar(envelope: dict) -> bytes:
    """Envelope → bytes prontos para sendall (JSON UTF-8 compacto + \\n)."""
    dados = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(dados) > config.TAMANHO_MAXIMO:
        raise ErroProtocolo("MSG_TOO_LARGE",
                            f"mensagem de {len(dados)} bytes excede {config.TAMANHO_MAXIMO}")
    return dados


def enviar(sock: socket.socket, envelope: dict) -> None:
    """Envia um envelope inteiro.

    Quem chama deve segurar o lock de envio daquele socket (issue #6): sem
    ele, duas threads podem intercalar bytes de mensagens diferentes.
    """
    sock.sendall(codificar(envelope))


# ------------------------------------------------------------------ recepção
class LeitorDeMensagens:
    """Lê envelopes de um socket respeitando o framing por \\n.

    proximo():
      * devolve o próximo envelope válido;
      * devolve None quando a conexão foi encerrada (normal ou abruptamente);
      * lança ErroProtocolo para mensagem inválida — se `erro.fatal` for
        True, a conexão deve ser encerrada; senão dá para continuar lendo;
      * deixa passar socket.timeout/TimeoutError (o servidor usa isso para
        o prazo do HELLO).

    Uma instância por conexão, usada por uma única thread.
    """

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self._buffer = bytearray()
        self.bytes_recebidos = 0

    def proximo(self) -> dict | None:
        while True:
            fim = self._buffer.find(b"\n")
            if fim >= 0:
                linha = bytes(self._buffer[:fim])
                del self._buffer[:fim + 1]
                if len(linha) + 1 > config.TAMANHO_MAXIMO:
                    raise ErroProtocolo("MSG_TOO_LARGE", "mensagem acima do limite", fatal=True)
                if not linha.strip():
                    continue                      # linha vazia: ignora
                return self._decodificar(linha)

            if len(self._buffer) >= config.TAMANHO_MAXIMO:
                raise ErroProtocolo("MSG_TOO_LARGE",
                                    f"mais de {config.TAMANHO_MAXIMO} bytes sem '\\n'", fatal=True)
            try:
                dados = self.sock.recv(_TAMANHO_RECV)
            except (socket.timeout, TimeoutError):
                raise
            except OSError:                       # reset, socket fechado por outra thread, erro TLS...
                return None
            if not dados:                         # o outro lado fechou a conexão
                return None
            self.bytes_recebidos += len(dados)
            self._buffer += dados

    @staticmethod
    def _decodificar(linha: bytes) -> dict:
        try:
            envelope = json.loads(linha.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            # Bytes que não são JSON: o fluxo pode ter perdido a sincronia (§3, regra 3).
            raise ErroProtocolo("BAD_MESSAGE", f"JSON inválido: {e}", fatal=True) from e
        return validar(envelope)
