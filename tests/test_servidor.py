"""Testes do núcleo do servidor — issues #5 e #6.

Sobe um ServidorChat de verdade numa porta livre (porta 0) e conecta
clientes por socket TCP.

    python -m unittest discover -s tests -v
"""

import queue
import socket
import threading
import time
import unittest

from common import eventos
from common import protocolo as p
from servidor.nucleo import ServidorChat


class ClienteTeste:
    """Cliente mínimo usado só nos testes."""

    def __init__(self, porta: int):
        self.sock = socket.create_connection(("127.0.0.1", porta), timeout=5)
        self.leitor = p.LeitorDeMensagens(self.sock)

    def enviar(self, env: dict) -> None:
        p.enviar(self.sock, env)

    def hello(self, nome: str, papel: str = "human") -> dict:
        self.enviar(p.novo_envelope(p.HELLO, nome, p.NOME_SERVIDOR, "", role=papel))
        return self.receber()

    def receber(self) -> dict | None:
        return self.leitor.proximo()

    def receber_tipo(self, tipo: str) -> dict:
        """Lê até achar uma mensagem do tipo pedido (ignora as outras)."""
        while True:
            env = self.receber()
            if env is None:
                raise AssertionError(f"conexão fechou antes de chegar {tipo}")
            if env["type"] == tipo:
                return env

    def fechou(self) -> bool:
        """True se o servidor encerrou a conexão (lê o que sobrar até o fim)."""
        try:
            while self.receber() is not None:
                pass
            return True
        except TimeoutError:
            return False

    def fechar(self) -> None:
        self.sock.close()


class BaseServidor(unittest.TestCase):
    def setUp(self):
        self.fila = queue.Queue()
        self.servidor = ServidorChat(self.fila, porta=0, porta_tls=None, timeout_hello=0.5)
        self.servidor.iniciar()
        self.porta = next(iter(self.servidor.portas_abertas.values()))
        self.clientes = []

    def tearDown(self):
        for c in self.clientes:
            c.fechar()
        self.servidor.parar()

    def conectar(self, nome: str | None = None, papel: str = "human") -> ClienteTeste:
        c = ClienteTeste(self.porta)
        self.clientes.append(c)
        if nome is not None:
            resposta = c.hello(nome, papel)
            self.assertEqual(resposta["type"], p.WELCOME, resposta)
        return c

    def eventos(self) -> list:
        itens = []
        while True:
            try:
                itens.append(self.fila.get_nowait())
            except queue.Empty:
                return itens


class TestHandshake(BaseServidor):
    def test_hello_recebe_welcome_e_users(self):
        c = self.conectar()
        welcome = c.hello("ana")
        self.assertEqual((welcome["type"], welcome["to"]), (p.WELCOME, "ana"))
        self.assertEqual(c.receber_tipo(p.USERS)["content"], ["ana"])

    def test_nome_duplicado_sem_diferenciar_maiusculas(self):
        self.conectar("ana")
        c = self.conectar()
        erro = c.hello("ANA")
        self.assertEqual((erro["type"], erro["code"]), (p.ERROR, "NAME_TAKEN"))
        self.assertTrue(c.fechou())

    def test_nomes_invalidos_e_reservados(self):
        for nome, codigo in [("ana maria", "NAME_INVALID"), ("joão", "NAME_INVALID"),
                             ("bot", "NAME_RESERVED"), ("Servidor", "NAME_RESERVED")]:
            with self.subTest(nome=nome):
                erro = self.conectar().hello(nome)
                self.assertEqual(erro["code"], codigo)

    def test_sem_hello_no_prazo(self):
        c = self.conectar()
        erro = c.receber()
        self.assertEqual(erro["code"], "HANDSHAKE_TIMEOUT")
        self.assertTrue(c.fechou())

    def test_mensagem_antes_do_hello(self):
        c = self.conectar()
        c.enviar(p.novo_envelope(p.MSG, "ana", p.TODOS, "oi"))
        self.assertEqual(c.receber()["code"], "NOT_REGISTERED")
        self.assertTrue(c.fechou())

    def test_json_invalido_no_handshake(self):
        c = self.conectar()
        c.sock.sendall(b"isso nao e json\n")
        self.assertEqual(c.receber()["code"], "BAD_MESSAGE")
        self.assertTrue(c.fechou())

    def test_apenas_um_bot(self):
        self.conectar("bot", papel="bot")
        erro = self.conectar().hello("bot", "bot")
        self.assertEqual(erro["code"], "BOT_ALREADY_CONNECTED")

    def test_bot_aparece_na_lista_de_usuarios(self):
        ana = self.conectar("ana")
        ana.receber_tipo(p.USERS)
        self.conectar("bot", papel="bot")
        self.assertEqual(ana.receber_tipo(p.USERS)["content"], ["ana", "bot"])


class TestEntradaESaida(BaseServidor):
    def test_join_avisa_os_outros(self):
        ana = self.conectar("ana")
        ana.receber_tipo(p.USERS)
        self.conectar("bruno")
        self.assertEqual(ana.receber_tipo(p.JOIN)["content"], "bruno")
        self.assertEqual(ana.receber_tipo(p.USERS)["content"], ["ana", "bruno"])

    def test_saida_com_bye(self):
        ana = self.conectar("ana")
        bruno = self.conectar("bruno")
        ana.receber_tipo(p.JOIN)
        bruno.enviar(p.novo_envelope(p.BYE, "bruno", p.NOME_SERVIDOR, ""))
        leave = ana.receber_tipo(p.LEAVE)
        self.assertEqual((leave["content"], leave["code"]), ("bruno", "LEFT"))
        self.assertEqual(ana.receber_tipo(p.USERS)["content"], ["ana"])

    def test_queda_abrupta(self):
        ana = self.conectar("ana")
        bruno = self.conectar("bruno")
        ana.receber_tipo(p.JOIN)
        bruno.fechar()                                  # sem BYE: simula o processo sendo fechado
        leave = ana.receber_tipo(p.LEAVE)
        self.assertEqual((leave["content"], leave["code"]), ("bruno", "CONNECTION_LOST"))

    def test_nome_fica_livre_depois_da_saida(self):
        ana = self.conectar("ana")
        ana.fechar()
        time.sleep(0.2)
        self.conectar("ana")                            # não pode dar NAME_TAKEN

    def test_expulsar(self):
        ana = self.conectar("ana")
        bruno = self.conectar("bruno")
        ana.receber_tipo(p.JOIN)
        self.assertTrue(self.servidor.expulsar("Bruno"))
        self.assertEqual(bruno.receber_tipo(p.BYE)["code"], "KICKED")
        self.assertEqual(ana.receber_tipo(p.LEAVE)["code"], "KICKED")

    def test_parar_avisa_todos(self):
        ana = self.conectar("ana")
        self.servidor.parar()
        self.assertEqual(ana.receber_tipo(p.BYE)["code"], "SERVER_SHUTDOWN")


class TestConcorrencia(BaseServidor):
    def test_30_clientes_entrando_ao_mesmo_tempo(self):
        """Cada cliente é atendido pela sua própria thread no servidor."""
        n = 30
        self.servidor.timeout_hello = 5      # a barreira segura os primeiros até todos conectarem
        resultados, erros = [], []
        largada = threading.Barrier(n)

        def entrar(i):
            try:
                c = ClienteTeste(self.porta)
                self.clientes.append(c)
                largada.wait()                          # todos mandam HELLO ao mesmo tempo
                resultados.append(c.hello(f"user{i}")["type"])
            except Exception as e:                      # pragma: no cover
                erros.append(e)

        threads = [threading.Thread(target=entrar, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(erros, [])
        self.assertEqual(resultados, [p.WELCOME] * n)
        threads_cliente = [t for t in threading.enumerate() if t.name.startswith("cliente-")]
        self.assertGreaterEqual(len(threads_cliente), n)

    def test_from_falso_e_corrigido_pelo_servidor(self):
        ana = self.conectar("ana")
        ana.receber_tipo(p.USERS)
        ana.enviar(p.novo_envelope(p.PING, "bot", p.NOME_SERVIDOR, ""))   # tenta se passar pelo bot
        ana.receber_tipo(p.PONG)
        trafegadas = [e.envelope for e in self.eventos() if isinstance(e, eventos.MensagemTrafegada)]
        self.assertEqual(trafegadas[-1]["from"], "ana")


class TestEventosParaGui(BaseServidor):
    def test_entrada_e_saida_geram_eventos(self):
        ana = self.conectar("ana")
        ana.fechar()
        time.sleep(0.3)
        tipos = [type(e).__name__ for e in self.eventos()]
        for esperado in ("ParticipanteEntrou", "ParticipanteSaiu", "EventoServidor", "StatusServidor"):
            self.assertIn(esperado, tipos)

    def test_tls_indisponivel_nao_derruba_o_servidor(self):
        fila = queue.Queue()
        s = ServidorChat(fila, porta=0, porta_tls=0)     # common/tls.py ainda é stub (#19)
        s.iniciar()
        try:
            self.assertEqual(len(s.portas_abertas), 1)
            textos = []
            while not fila.empty():
                e = fila.get_nowait()
                if isinstance(e, eventos.EventoServidor):
                    textos.append(e.texto)
            self.assertTrue(any("TLS desativado" in t for t in textos), textos)
        finally:
            s.parar()


if __name__ == "__main__":
    unittest.main()
