"""Núcleo de rede do servidor.

Responsável: Pedro — issues #5 (aceitação, thread por cliente, identificação)
e #6 (sincronização). Roteamento (#7), desconexões completas (#8) e TLS (#20)
entram nos pontos marcados com "→ #N".

Contrato com a GUI (Bruna):
    fila = queue.Queue()
    servidor = ServidorChat(fila)
    servidor.iniciar()          # abre as portas, sobe as threads de aceitação e retorna
    ...                         # a GUI consome a fila (common/eventos.py)
    servidor.expulsar("ana")    # botão "Desconectar selecionado"
    servidor.parar()            # ao fechar a janela

Modelo de concorrência
----------------------
* 1 thread de aceitação por porta (5000 e, se houver TLS, 5001).
* 1 thread por cliente conectado, que lê as mensagens dele em laço.
* Estado compartilhado (self._clientes, self._bot) protegido por self._lock.
* Cada conexão tem o próprio lock de envio (Conexao._lock_envio): várias
  threads podem mandar mensagens ao mesmo cliente, e sem esse lock os bytes
  de duas mensagens poderiam se intercalar no socket.
* Regra para não travar: NUNCA enviar dados segurando self._lock. Copia-se
  a lista de destinatários dentro do lock e envia-se fora dele. Assim um
  cliente lento não bloqueia o servidor inteiro.
* Única ordem de aquisição usada com os dois locks: lock de envio da conexão
  → self._lock (no registro, ver _registrar). Nunca o contrário, então não
  há deadlock.
"""

from __future__ import annotations

import os
import queue
import socket
import ssl
import threading
import time

from common import config, eventos
from common import protocolo as p


class Conexao:
    """Um participante conectado (humano ou bot)."""

    def __init__(self, sock: socket.socket, endereco: str, canal: str):
        self.sock = sock
        self.endereco = endereco
        self.canal = canal                  # "TCP :5000" | "TLS :5001"
        self.nome: str | None = None        # definido no HELLO aceito
        self.papel: str | None = None       # "human" | "bot"
        self.desde = time.time()
        self.motivo_saida = "CONNECTION_LOST"
        self._lock_envio = threading.Lock()

    @property
    def chave(self) -> str:
        """Nome normalizado: 'Ana' e 'ana' são o mesmo participante (§6.1)."""
        return self.nome.lower()

    def enviar(self, envelope: dict) -> bool:
        """Envia uma mensagem inteira. Devolve False se a conexão já caiu
        (quem cuida da limpeza é a thread de leitura desse cliente)."""
        with self._lock_envio:
            return self._enviar_sem_lock(envelope)

    def _enviar_sem_lock(self, envelope: dict) -> bool:
        try:
            p.enviar(self.sock, envelope)
            return True
        except OSError:
            return False

    def fechar(self) -> None:
        """Fecha o socket. O shutdown acorda a thread presa no recv."""
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class ServidorChat:
    def __init__(self, fila_eventos: queue.Queue, host: str = config.HOST,
                 porta: int = config.PORTA, porta_tls: int | None = config.PORTA_TLS,
                 contexto_tls: ssl.SSLContext | None = None,
                 timeout_hello: float = config.TIMEOUT_HELLO):
        self.fila_eventos = fila_eventos
        self.host = host
        self.porta = porta
        self.porta_tls = porta_tls
        self.contexto_tls = contexto_tls
        self.timeout_hello = timeout_hello

        self._lock = threading.Lock()                 # protege _clientes e _bot
        self._clientes: dict[str, Conexao] = {}       # humanos, chave = nome.lower()
        self._bot: Conexao | None = None
        self._escutas: list[socket.socket] = []
        self._rodando = False
        self.portas_abertas: dict[str, int] = {}      # canal -> porta real (útil com porta 0 nos testes)

    # ================================================================ ciclo de vida
    def iniciar(self) -> None:
        """Abre as portas e inicia as threads de aceitação (não bloqueia).
        Lança OSError se a porta já estiver em uso."""
        self._rodando = True
        self._abrir_escuta(self.porta, tls=False)

        if self.porta_tls is not None:
            if self.contexto_tls is None:
                self.contexto_tls = self._carregar_contexto_tls()
            if self.contexto_tls is not None:
                self._abrir_escuta(self.porta_tls, tls=True)

        portas = ", ".join(f"{c} (porta {n})" for c, n in self.portas_abertas.items())
        self._evento("info", f"Servidor ouvindo em {self.host}: {portas}")
        self._publicar_status()

    def _carregar_contexto_tls(self) -> ssl.SSLContext | None:
        try:
            from common import tls
            return tls.contexto_servidor()
        except (NotImplementedError, OSError, ssl.SSLError, ImportError) as e:
            # → #20: enquanto o TLS não estiver pronto, o servidor sobe só na porta sem criptografia.
            self._evento("erro", f"TLS desativado ({type(e).__name__}: {e}) — só a porta {self.porta} está aberta")
            return None

    def _abrir_escuta(self, porta: int, tls: bool) -> None:
        escuta = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            # No Linux permite reabrir a porta logo após fechar o servidor.
            # No Windows SO_REUSEADDR deixaria DOIS processos ouvirem a mesma porta, então não usamos.
            escuta.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        escuta.bind((self.host, porta))
        escuta.listen(16)
        porta_real = escuta.getsockname()[1]
        canal = f"{'TLS' if tls else 'TCP'} :{porta_real}"
        self._escutas.append(escuta)
        self.portas_abertas[canal] = porta_real
        threading.Thread(target=self._aceitar, args=(escuta, canal, tls),
                         name=f"aceitacao-{canal}", daemon=True).start()

    def parar(self) -> None:
        """Avisa todos com BYE SERVER_SHUTDOWN e fecha os sockets."""
        self._rodando = False
        for escuta in self._escutas:
            try:
                escuta.close()
            except OSError:
                pass
        with self._lock:
            todas = list(self._clientes.values()) + ([self._bot] if self._bot else [])
        for c in todas:
            c.motivo_saida = "SERVER_SHUTDOWN"
            c.enviar(p.novo_envelope(p.BYE, p.NOME_SERVIDOR, c.nome, "Servidor encerrado",
                                     code="SERVER_SHUTDOWN"))
            c.fechar()
        self._evento("info", "Servidor encerrado")

    def expulsar(self, nome: str) -> bool:
        """Desconecta um participante (BYE KICKED). A limpeza e o aviso aos
        demais são feitos pela thread do próprio cliente, ao perceber o fechamento."""
        with self._lock:
            alvo = self._bot if nome.lower() == p.NOME_BOT else self._clientes.get(nome.lower())
        if alvo is None:
            return False
        alvo.motivo_saida = "KICKED"
        alvo.enviar(p.novo_envelope(p.BYE, p.NOME_SERVIDOR, alvo.nome,
                                    "Você foi desconectado pelo servidor", code="KICKED"))
        alvo.fechar()
        return True

    # ================================================================ aceitação
    def _aceitar(self, escuta: socket.socket, canal: str, tls: bool) -> None:
        """Thread de aceitação: para cada conexão nova, cria uma thread dedicada."""
        while self._rodando:
            try:
                sock, (ip, porta) = escuta.accept()
            except OSError:
                break                                   # socket de escuta fechado em parar()
            endereco = f"{ip}:{porta}"
            threading.Thread(target=self._atender, args=(sock, endereco, canal, tls),
                             name=f"cliente-{endereco}", daemon=True).start()

    # ================================================================ thread do cliente
    def _atender(self, sock: socket.socket, endereco: str, canal: str, tls: bool) -> None:
        """Corpo da thread dedicada a UM cliente: handshake e laço de leitura."""
        if tls:
            # O handshake TLS acontece aqui, e não na thread de aceitação,
            # para um cliente lento não atrasar a entrada dos outros.
            try:
                sock.settimeout(self.timeout_hello)
                sock = self.contexto_tls.wrap_socket(sock, server_side=True)
            except (ssl.SSLError, OSError) as e:
                self._evento("erro", f"Handshake TLS recusado de {endereco}: {e}")
                try:
                    sock.close()
                except OSError:
                    pass
                return

        conexao = Conexao(sock, endereco, canal)
        leitor = p.LeitorDeMensagens(sock)
        try:
            if not self._handshake(conexao, leitor):
                return
            while True:
                try:
                    env = leitor.proximo()
                except p.ErroProtocolo as e:
                    self._enviar_erro(conexao, e.code, str(e), ref=e.ref)
                    if e.fatal:
                        break
                    continue
                if env is None:
                    break                               # conexão encerrada
                env["from"] = conexao.nome              # nunca confiar no "from" do cliente (§3)
                self._publicar(eventos.MensagemTrafegada(env))
                if not self._tratar(conexao, env):
                    break
        finally:
            self._remover(conexao)

    def _handshake(self, conexao: Conexao, leitor: p.LeitorDeMensagens) -> bool:
        """Espera o HELLO (até timeout_hello s) e registra o participante."""
        conexao.sock.settimeout(self.timeout_hello)
        try:
            env = leitor.proximo()
        except TimeoutError:
            self._enviar_erro(conexao, "HANDSHAKE_TIMEOUT",
                              f"nenhum HELLO em {self.timeout_hello:g} s")
            return False
        except p.ErroProtocolo as e:
            self._enviar_erro(conexao, e.code, str(e), ref=e.ref)
            return False
        if env is None:
            return False
        if env["type"] != p.HELLO:
            self._enviar_erro(conexao, "NOT_REGISTERED", "a primeira mensagem precisa ser HELLO",
                              ref=env["id"])
            return False
        conexao.sock.settimeout(None)
        return self._registrar(conexao, env)

    def _registrar(self, conexao: Conexao, hello: dict) -> bool:
        nome, papel = hello["from"], hello["role"]
        codigo = p.validar_nome(nome, papel)
        if codigo == "NAME_RESERVED":
            texto = f"o nome '{nome}' é reservado"
        else:
            texto = f"nome inválido: '{nome}' (use 1 a 20 letras sem acento, números, _ ou -)"

        # Segura o lock de envio da conexão nova ANTES de torná-la visível:
        # assim nenhuma outra thread consegue mandar mensagem a ela antes do WELCOME.
        with conexao._lock_envio:
            with self._lock:
                if codigo is None and papel == "bot" and self._bot is not None:
                    codigo, texto = "BOT_ALREADY_CONNECTED", "já existe um bot conectado"
                if codigo is None and papel == "human" and nome.lower() in self._clientes:
                    codigo, texto = "NAME_TAKEN", f"o nome '{nome}' já está em uso"
                if codigo is None:
                    conexao.nome, conexao.papel = nome, papel
                    if papel == "bot":
                        self._bot = conexao
                    else:
                        self._clientes[conexao.chave] = conexao
            if codigo is not None:
                conexao._enviar_sem_lock(p.novo_envelope(
                    p.ERROR, p.NOME_SERVIDOR, nome, texto, code=codigo, ref=hello["id"]))
                self._evento("erro", f"Entrada recusada de {conexao.endereco}: {codigo} ({nome!r})")
                return False
            boas_vindas = "Bot conectado" if papel == "bot" else f"Bem-vindo(a), {nome}!"
            conexao._enviar_sem_lock(p.novo_envelope(p.WELCOME, p.NOME_SERVIDOR, nome, boas_vindas))

        self._publicar(eventos.ParticipanteEntrou(nome, papel, conexao.endereco, conexao.canal,
                                                  conexao.desde))
        self._evento("bot" if papel == "bot" else "join",
                     f"{nome} entrou ({conexao.endereco}, {conexao.canal})")
        if papel == "human":
            self._difundir(p.novo_envelope(p.JOIN, p.NOME_SERVIDOR, p.TODOS, nome), excluir=conexao)
        self._difundir_usuarios()
        self._publicar_status()
        return True

    # ================================================================ mensagens
    def _tratar(self, conexao: Conexao, env: dict) -> bool:
        """Despacha uma mensagem recebida. Devolve False para encerrar a conexão."""
        tipo = env["type"]
        if tipo == p.BYE:
            conexao.motivo_saida = "LEFT"
            return False
        if tipo == p.PING:
            conexao.enviar(p.novo_envelope(p.PONG, p.NOME_SERVIDOR, conexao.nome, "", ref=env["id"]))
            return True
        if tipo == p.PONG:
            return True
        if tipo == p.HELLO:
            self._enviar_erro(conexao, "BAD_MESSAGE", "HELLO repetido", ref=env["id"])
            return True
        return self._rotear(conexao, env)

    def _rotear(self, conexao: Conexao, env: dict) -> bool:
        """→ #7: sala, privado, @bot e respostas do bot."""
        self._enviar_erro(conexao, "UNKNOWN_TYPE",
                          f"roteamento de {env['type']} ainda não implementado (issue #7)", ref=env["id"])
        return True

    # ================================================================ saída
    def _remover(self, conexao: Conexao) -> None:
        """Retira o participante do estado compartilhado e avisa os demais.
        Chamada uma única vez, pela thread do próprio cliente."""
        conexao.fechar()
        if conexao.nome is None:
            return                                      # nunca chegou a se registrar
        with self._lock:
            if conexao.papel == "bot" and self._bot is conexao:
                self._bot = None
            elif self._clientes.get(conexao.chave) is conexao:
                del self._clientes[conexao.chave]
            else:
                return
            # → #8: descartar perguntas pendentes deste usuário / avisar pendentes se for o bot.

        motivo = conexao.motivo_saida
        self._publicar(eventos.ParticipanteSaiu(conexao.nome, motivo))
        descricao = {"LEFT": "saiu", "KICKED": "foi desconectado pelo servidor",
                     "SERVER_SHUTDOWN": "desconectado (servidor encerrado)"}.get(motivo, "perdeu a conexão")
        self._evento("leave" if motivo == "LEFT" else "erro", f"{conexao.nome} {descricao}")
        if self._rodando:
            self._difundir(p.novo_envelope(p.LEAVE, p.NOME_SERVIDOR, p.TODOS, conexao.nome, code=motivo))
            self._difundir_usuarios()
        self._publicar_status()

    # ================================================================ utilitários
    def _humanos(self, excluir: Conexao | None = None) -> list[Conexao]:
        """Cópia da lista de humanos, feita dentro do lock (envio é sempre fora dele)."""
        with self._lock:
            return [c for c in self._clientes.values() if c is not excluir]

    def _difundir(self, env: dict, excluir: Conexao | None = None) -> None:
        for c in self._humanos(excluir):
            c.enviar(env)

    def _difundir_usuarios(self) -> None:
        with self._lock:
            nomes = sorted((c.nome for c in self._clientes.values()), key=str.lower)
            if self._bot is not None:
                nomes.append(p.NOME_BOT)
        self._difundir(p.novo_envelope(p.USERS, p.NOME_SERVIDOR, p.TODOS, nomes))

    def _enviar_erro(self, conexao: Conexao, code: str, texto: str, ref: str | None = None) -> None:
        conexao.enviar(p.novo_envelope(p.ERROR, p.NOME_SERVIDOR, conexao.nome or "?", texto,
                                       code=code, ref=ref))

    def _publicar(self, item) -> None:
        self.fila_eventos.put(item)

    def _evento(self, nivel: str, texto: str) -> None:
        self._publicar(eventos.EventoServidor(nivel, texto))

    def _publicar_status(self) -> None:
        with self._lock:
            status = eventos.StatusServidor(conectados=len(self._clientes), pendentes_bot=0,
                                            bot_online=self._bot is not None)
        self._publicar(status)
