"""Camada de rede do cliente humano.

Responsável: Pedro — issue #10.

Contrato com a GUI (Bruna):
    fila = queue.Queue()                       # recebe EnvelopeRecebido / ConexaoEncerrada
    rede = ClienteRede(fila)
    rede.conectar("ana", usar_tls=True)        # lança ErroConexao se falhar ou o nome for recusado
    id_msg = rede.enviar_sala("oi")            # cada envio devolve o id da mensagem
    id_msg = rede.enviar_privada("bruno", "oi")
    id_msg = rede.perguntar_bot("minha internet caiu")   # guardar: a resposta chega com ref == id_msg
    rede.sair()

Operação assíncrona (o que o edital avalia):
  * uma THREAD DE RECEPÇÃO fica lendo o socket o tempo todo e coloca cada
    mensagem na fila — a GUI consome com root.after(), então chegar mensagem
    nunca trava a digitação;
  * os envios são feitos pela thread da GUI e só escrevem no socket (rápido);
    um lock de envio garante que duas mensagens não se misturem.
"""

from __future__ import annotations

import queue
import socket
import ssl
import threading

from common import config, eventos
from common import protocolo as p

TIMEOUT_CONEXAO = 5.0       # s para conectar e receber o WELCOME


class ErroConexao(Exception):
    """Falha ao conectar, nome recusado ou conexão perdida (mensagem pronta para o usuário)."""


class ClienteRede:
    def __init__(self, fila: queue.Queue):
        self.fila = fila
        self.nome: str | None = None
        self.canal: str | None = None            # "TCP :5000" | "TLS :5001"
        self.sessao_tls: str | None = None       # ex.: "TLSv1.3 · TLS_AES_256_GCM_SHA384"
        self._sock: socket.socket | None = None
        self._lock_envio = threading.Lock()
        self._conectado = False
        self._motivo_saida: str | None = None    # preenchido por BYE do servidor ou por sair()

    @property
    def conectado(self) -> bool:
        return self._conectado

    # ================================================================ conexão
    def conectar(self, nome: str, host: str = config.HOST, porta: int | None = None,
                 usar_tls: bool = False, cafile=None) -> None:
        """Conecta, faz o HELLO e só retorna depois do WELCOME. Sem `porta`,
        usa 5001 com TLS e 5000 sem."""
        if self._conectado:
            raise ErroConexao("Já conectado.")
        porta = porta or (config.PORTA_TLS if usar_tls else config.PORTA)
        sock = self._abrir_socket(host, porta, usar_tls, cafile)
        leitor = p.LeitorDeMensagens(sock)
        try:
            p.enviar(sock, p.novo_envelope(p.HELLO, nome, p.NOME_SERVIDOR, "", role="human"))
            resposta = leitor.proximo()
        except TimeoutError:
            sock.close()
            raise ErroConexao("O servidor não respondeu ao pedido de entrada.") from None
        except (OSError, p.ErroProtocolo) as e:
            sock.close()
            raise ErroConexao(f"Falha na comunicação com o servidor: {e}") from e

        if resposta is None:
            sock.close()
            raise ErroConexao("O servidor encerrou a conexão.")
        if resposta["type"] == p.ERROR:
            sock.close()
            raise ErroConexao(resposta["content"])
        if resposta["type"] != p.WELCOME:
            sock.close()
            raise ErroConexao(f"Resposta inesperada do servidor: {resposta['type']}")

        sock.settimeout(None)
        self._sock, self.nome = sock, resposta["to"]
        self.canal = f"{'TLS' if usar_tls else 'TCP'} :{porta}"
        if usar_tls:
            from common.tls import descrever
            self.sessao_tls = descrever(sock)
        self._conectado, self._motivo_saida = True, None
        self.fila.put(eventos.EnvelopeRecebido(resposta))
        threading.Thread(target=self._receber, args=(leitor,), name=f"recepcao-{nome}",
                         daemon=True).start()

    def _abrir_socket(self, host: str, porta: int, usar_tls: bool, cafile=None) -> socket.socket:
        try:
            sock = socket.create_connection((host, porta), timeout=TIMEOUT_CONEXAO)
        except OSError as e:
            raise ErroConexao(f"Não foi possível conectar a {host}:{porta}. "
                              f"O servidor está rodando? ({e.strerror or e})") from e
        if not usar_tls:
            return sock
        try:
            from common import tls
            contexto = tls.contexto_cliente(cafile) if cafile else tls.contexto_cliente()
            # server_hostname: o certificado é conferido contra este nome/IP (check_hostname).
            return contexto.wrap_socket(sock, server_hostname=host)
        except NotImplementedError as e:
            sock.close()
            raise ErroConexao("TLS ainda não está disponível neste projeto (issue #19).") from e
        except FileNotFoundError as e:
            sock.close()
            raise ErroConexao(f"Certificado da CA não encontrado: {e}") from e
        except ssl.SSLCertVerificationError as e:
            sock.close()
            raise ErroConexao(f"Certificado do servidor RECUSADO: {e.verify_message}. "
                              "A conexão não é segura.") from e
        except (ssl.SSLError, OSError) as e:
            sock.close()
            raise ErroConexao(f"Falha ao estabelecer TLS: {e}") from e

    # ================================================================ envio (thread da GUI)
    def enviar_sala(self, texto: str) -> str:
        return self._enviar_msg(p.TODOS, texto)

    def enviar_privada(self, destinatario: str, texto: str) -> str:
        return self._enviar_msg(destinatario, texto)

    def perguntar_bot(self, pergunta: str) -> str:
        """Envia '@bot <pergunta>'; devolve o id usado como `ref` na resposta."""
        return self._enviar_msg(p.TODOS, f"@bot {pergunta.strip()}")

    def _enviar_msg(self, destinatario: str, texto: str) -> str:
        env = p.novo_envelope(p.MSG, self.nome or "?", destinatario, texto)
        self._enviar(env)
        return env["id"]

    def _enviar(self, env: dict) -> None:
        if not self._conectado:
            raise ErroConexao("Sem conexão com o servidor.")
        try:
            with self._lock_envio:
                p.enviar(self._sock, env)
        except OSError as e:
            raise ErroConexao("Sem conexão com o servidor.") from e

    def sair(self) -> None:
        """Saída voluntária: BYE e fecha o socket (a thread de recepção termina sozinha)."""
        if not self._conectado:
            return
        self._motivo_saida = "Você saiu do chat."
        try:
            self._enviar(p.novo_envelope(p.BYE, self.nome, p.NOME_SERVIDOR, ""))
        except ErroConexao:
            pass
        self._fechar()

    def _fechar(self) -> None:
        self._conectado = False
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass

    # ================================================================ recepção (thread própria)
    def _receber(self, leitor: p.LeitorDeMensagens) -> None:
        """Thread de recepção: lê sem parar e entrega tudo à GUI pela fila."""
        while True:
            try:
                env = leitor.proximo()
            except p.ErroProtocolo as e:
                if e.fatal:
                    self._motivo_saida = self._motivo_saida or f"Erro de protocolo: {e}"
                    break
                continue
            except TimeoutError:
                continue
            if env is None:
                break
            if env["type"] == p.BYE:
                self._motivo_saida = {
                    "KICKED": "Você foi desconectado pelo servidor.",
                    "SERVER_SHUTDOWN": "O servidor foi encerrado.",
                }.get(env.get("code"), env.get("content") or "O servidor encerrou a conexão.")
            self.fila.put(eventos.EnvelopeRecebido(env))

        motivo = self._motivo_saida or "A conexão com o servidor caiu."
        self._fechar()
        self.fila.put(eventos.ConexaoEncerrada(motivo))
