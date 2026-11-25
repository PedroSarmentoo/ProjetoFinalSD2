"""Camada de rede do bot.

Responsável: Pedro — issue #11.

O bot é um processo separado que se conecta ao servidor como um cliente
comum, mas com role "bot". Para cada BOT_REQ recebido:

    BOT_REQ (ref, on_behalf_of, pergunta)
        -> pool de threads: historico.obter -> consultar_llm -> historico.registrar
        -> BOT_RESP (ou BOT_ERR com o code do ErroLLM), mesmo ref e mesmo usuário

Concorrência: a thread principal só LÊ o socket e entrega cada pergunta a
um ThreadPoolExecutor. Assim uma consulta lenta à LLM não impede o bot de
receber e atender as perguntas de outros usuários ao mesmo tempo. Os envios
de várias threads passam por um lock, para as respostas não se misturarem.
"""

from __future__ import annotations

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from bot import llm
from bot.historico import Historicos
from common import config
from common import protocolo as p


class ErroBot(Exception):
    """Falha ao conectar o bot ao servidor (mensagem pronta para o terminal)."""


class BotRede:
    def __init__(self, host: str = config.HOST, porta: int | None = None,
                 usar_tls: bool = False, max_threads: int = 4,
                 consultar=None, historicos: Historicos | None = None, log=print, cafile=None):
        self.host = host
        self.usar_tls = usar_tls
        self.porta = porta or (config.PORTA_TLS if usar_tls else config.PORTA)
        self.max_threads = max_threads
        self.consultar = consultar or llm.consultar_llm     # trocável nos testes
        self.historicos = historicos or Historicos()
        self.log = log
        self.cafile = cafile
        self._sock: socket.socket | None = None
        self._lock_envio = threading.Lock()
        self._rodando = False

    # ================================================================ conexão
    def conectar(self) -> p.LeitorDeMensagens:
        try:
            sock = socket.create_connection((self.host, self.porta), timeout=5)
        except OSError as e:
            raise ErroBot(f"Não foi possível conectar a {self.host}:{self.porta}. "
                          f"O servidor está rodando? ({e.strerror or e})") from e
        if self.usar_tls:
            try:
                from common import tls
                contexto = tls.contexto_cliente(self.cafile) if self.cafile else tls.contexto_cliente()
                sock = contexto.wrap_socket(sock, server_hostname=self.host)
            except NotImplementedError as e:
                sock.close()
                raise ErroBot("TLS ainda não está disponível (issue #19).") from e
            except OSError as e:                             # inclui ssl.SSLError
                sock.close()
                raise ErroBot(f"Falha no TLS: {e}") from e

        leitor = p.LeitorDeMensagens(sock)
        p.enviar(sock, p.novo_envelope(p.HELLO, p.NOME_BOT, p.NOME_SERVIDOR, "", role="bot"))
        resposta = leitor.proximo()
        if resposta is None or resposta["type"] != p.WELCOME:
            sock.close()
            motivo = resposta["content"] if resposta else "conexão encerrada"
            raise ErroBot(f"Servidor recusou o bot: {motivo}")
        sock.settimeout(None)
        self._sock, self._rodando = sock, True
        return leitor

    def executar(self) -> None:
        """Conecta e atende pedidos até o servidor encerrar (bloqueia)."""
        leitor = self.conectar()
        self.log(f"Bot conectado a {self.host}:{self.porta} — modelo {config.LLM_MODEL}, "
                 f"até {self.max_threads} consultas simultâneas.")
        with ThreadPoolExecutor(max_workers=self.max_threads, thread_name_prefix="llm") as pool:
            while self._rodando:
                try:
                    env = leitor.proximo()
                except p.ErroProtocolo as e:
                    self.log(f"[aviso] mensagem inválida do servidor: {e}")
                    if e.fatal:
                        break
                    continue
                if env is None:
                    break
                if env["type"] == p.BOT_REQ:
                    self.log(f"→ pergunta de {env['on_behalf_of']} (#{env['ref'][:8]}): {env['content']}")
                    pool.submit(self._atender, env)
                elif env["type"] == p.BYE:
                    self.log(f"Servidor encerrou a conexão: {env.get('content')}")
                elif env["type"] == p.PING:
                    self._enviar(p.novo_envelope(p.PONG, p.NOME_BOT, p.NOME_SERVIDOR, "", ref=env["id"]))
        self._rodando = False
        self.log("Bot desconectado.")

    def parar(self) -> None:
        self._rodando = False
        if self._sock is not None:
            for fechar in (lambda: self._sock.shutdown(socket.SHUT_RDWR), self._sock.close):
                try:
                    fechar()
                except OSError:
                    pass

    # ================================================================ atendimento (threads do pool)
    def _atender(self, req: dict) -> None:
        usuario, ref, pergunta = req["on_behalf_of"], req["ref"], req["content"]
        inicio = time.time()
        try:
            texto = self.consultar(self.historicos.obter(usuario), pergunta)
            self.historicos.registrar(usuario, pergunta, texto)
            resposta = p.novo_envelope(p.BOT_RESP, p.NOME_BOT, usuario, texto, ref=ref)
            self.log(f"← resposta para {usuario} (#{ref[:8]}) em {time.time() - inicio:.1f} s")
        except llm.ErroLLM as e:
            resposta = p.novo_envelope(p.BOT_ERR, p.NOME_BOT, usuario, str(e), ref=ref, code=e.code)
            self.log(f"✕ falha para {usuario} (#{ref[:8]}): [{e.code}] {e}"
                     + (f" — API: {e.detalhe}" if e.detalhe else ""))
        except Exception as e:                               # nunca derrubar o bot por um pedido
            resposta = p.novo_envelope(p.BOT_ERR, p.NOME_BOT, usuario,
                                       "Erro interno do bot ao consultar a LLM.", ref=ref,
                                       code="LLM_UNAVAILABLE")
            self.log(f"✕ erro interno para {usuario} (#{ref[:8]}): {e!r}")
        self._enviar(resposta)

    def _enviar(self, env: dict) -> None:
        try:
            with self._lock_envio:
                p.enviar(self._sock, env)
        except OSError:
            self.log("[aviso] não foi possível enviar: conexão com o servidor perdida.")
