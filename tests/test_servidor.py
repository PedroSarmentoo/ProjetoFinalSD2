"""Testes do núcleo do servidor — issues #5, #6, #7 e #8.

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

    def nada_chega(self, espera: float = 0.3) -> bool:
        """True se nenhuma mensagem chegar em `espera` segundos."""
        self.sock.settimeout(espera)
        try:
            self.receber()                 # chegou algo (ou a conexão fechou)
            return False
        except TimeoutError:
            return True
        finally:
            self.sock.settimeout(5)

    def msg(self, texto: str, para: str = p.TODOS) -> dict:
        env = p.novo_envelope(p.MSG, "?", para, texto)
        self.enviar(env)
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
        self.servidor = ServidorChat(self.fila, porta=0, porta_tls=None,
                                     timeout_hello=0.5, timeout_bot=1.0)
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

    def sala(self, *nomes: str) -> list[ClienteTeste]:
        """Conecta vários usuários e consome as mensagens de entrada de todos."""
        clientes = [self.conectar(n) for n in nomes]
        time.sleep(0.2)
        for c in clientes:
            while not c.nada_chega(0.05):
                pass
        return clientes

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


class TestRoteamento(BaseServidor):
    def test_sala_chega_a_todos_menos_o_remetente(self):
        ana, bruno, carla = self.sala("ana", "bruno", "carla")
        enviada = ana.msg("bom dia")
        for c in (bruno, carla):
            recebida = c.receber_tipo(p.MSG)
            self.assertEqual((recebida["id"], recebida["from"], recebida["content"]),
                             (enviada["id"], "ana", "bom dia"))
        self.assertTrue(ana.nada_chega())

    def test_privada_chega_so_ao_destinatario(self):
        ana, bruno, carla = self.sala("ana", "bruno", "carla")
        ana.msg("segredo", para="Bruno")
        self.assertEqual(bruno.receber_tipo(p.MSG)["content"], "segredo")
        self.assertTrue(carla.nada_chega())
        self.assertTrue(ana.nada_chega())

    def test_privada_para_quem_nao_esta_online(self):
        (ana,) = self.sala("ana")
        enviada = ana.msg("oi", para="zeca")
        erro = ana.receber_tipo(p.ERROR)
        self.assertEqual((erro["code"], erro["ref"]), ("USER_NOT_FOUND", enviada["id"]))

    def test_humano_nao_pode_enviar_tipos_do_bot(self):
        (ana,) = self.sala("ana")
        ana.enviar(p.novo_envelope(p.BOT_RESP, "ana", "bruno", "falsa", ref="x"))
        self.assertEqual(ana.receber_tipo(p.ERROR)["code"], "BAD_MESSAGE")


class TestBot(BaseServidor):
    def setUp(self):
        super().setUp()
        self.bot = self.conectar("bot", papel="bot")
        time.sleep(0.1)

    def responder(self, req: dict, texto: str = "resposta", tipo: str = p.BOT_RESP, **extras) -> None:
        extras.setdefault("ref", req["ref"])
        self.bot.enviar(p.novo_envelope(tipo, "bot", req["on_behalf_of"], texto, **extras))

    def test_percurso_completo_da_pergunta(self):
        ana, bruno = self.sala("ana", "bruno")
        pergunta = ana.msg("@bot minha internet cai toda noite")

        req = self.bot.receber_tipo(p.BOT_REQ)
        self.assertEqual((req["ref"], req["on_behalf_of"], req["content"]),
                         (pergunta["id"], "ana", "minha internet cai toda noite"))
        self.assertTrue(bruno.nada_chega())            # a pergunta NÃO vai para a sala

        self.responder(req, "Reinicie o roteador.")
        resp = ana.receber_tipo(p.BOT_RESP)
        self.assertEqual((resp["ref"], resp["from"], resp["content"]),
                         (pergunta["id"], "bot", "Reinicie o roteador."))
        self.assertTrue(bruno.nada_chega())            # a resposta é só de quem perguntou

    def test_conversa_continua_enquanto_o_bot_pensa(self):
        """Cenário obrigatório: o bot demora e os outros seguem conversando."""
        ana, bruno, carla = self.sala("ana", "bruno", "carla")
        ana.msg("@bot explique DNS")
        req = self.bot.receber_tipo(p.BOT_REQ)         # bot recebeu e ainda não respondeu
        for i in range(5):
            bruno.msg(f"mensagem {i}")
            self.assertEqual(carla.receber_tipo(p.MSG)["content"], f"mensagem {i}")
        self.responder(req)
        self.assertEqual(ana.receber_tipo(p.BOT_RESP)["ref"], req["ref"])

    def test_erro_da_llm_e_repassado(self):
        (ana,) = self.sala("ana")
        ana.msg("@bot oi")
        req = self.bot.receber_tipo(p.BOT_REQ)
        self.responder(req, "A LLM não respondeu.", tipo=p.BOT_ERR, code="LLM_TIMEOUT")
        erro = ana.receber_tipo(p.BOT_ERR)
        self.assertEqual((erro["code"], erro["ref"]), ("LLM_TIMEOUT", req["ref"]))

    def test_resposta_com_destinatario_errado_e_descartada(self):
        ana, bruno = self.sala("ana", "bruno")
        ana.msg("@bot oi")
        req = self.bot.receber_tipo(p.BOT_REQ)
        self.bot.enviar(p.novo_envelope(p.BOT_RESP, "bot", "bruno", "vazou?", ref=req["ref"]))
        self.assertTrue(bruno.nada_chega())
        self.assertTrue(ana.nada_chega())

    def test_ref_inexistente_e_descartado(self):
        (ana,) = self.sala("ana")
        self.bot.enviar(p.novo_envelope(p.BOT_RESP, "bot", "ana", "do nada", ref="inventado"))
        self.assertTrue(ana.nada_chega())

    def test_arroba_bot_vazio(self):
        (ana,) = self.sala("ana")
        ana.msg("@bot")
        self.assertEqual(ana.receber_tipo(p.ERROR)["code"], "BAD_MESSAGE")

    def test_limite_de_perguntas_pendentes(self):
        (ana,) = self.sala("ana")
        for i in range(3):
            ana.msg(f"@bot pergunta {i}")
        ana.msg("@bot quarta")
        self.assertEqual(ana.receber_tipo(p.ERROR)["code"], "BOT_BUSY")

    def test_tempo_limite_no_servidor(self):
        (ana,) = self.sala("ana")
        pergunta = ana.msg("@bot vai demorar")
        req = self.bot.receber_tipo(p.BOT_REQ)
        erro = ana.receber_tipo(p.BOT_ERR)             # timeout_bot = 1 s nos testes
        self.assertEqual((erro["code"], erro["ref"], erro["from"]),
                         ("BOT_TIMEOUT", pergunta["id"], "servidor"))
        self.responder(req, "atrasada")                # resposta tardia é descartada
        self.assertTrue(ana.nada_chega())

    def test_bot_cai_com_pergunta_pendente(self):
        ana, bruno = self.sala("ana", "bruno")
        pa = ana.msg("@bot pergunta da ana")
        pb = bruno.msg("@bot pergunta do bruno")
        self.bot.receber_tipo(p.BOT_REQ)
        self.bot.fechar()
        for c, enviada in ((ana, pa), (bruno, pb)):
            erro = c.receber_tipo(p.BOT_ERR)
            self.assertEqual((erro["code"], erro["ref"]), ("BOT_OFFLINE", enviada["id"]))

    def test_usuario_sai_com_pergunta_pendente(self):
        ana, bruno = self.sala("ana", "bruno")
        ana.msg("@bot oi")
        req = self.bot.receber_tipo(p.BOT_REQ)
        ana.fechar()
        time.sleep(0.2)
        self.responder(req)                            # não pode derrubar nada
        bruno.msg("ainda funciona?")
        self.assertEqual(self.servidor._pendentes, {})

    def test_status_conta_pendentes(self):
        (ana,) = self.sala("ana")
        self.eventos()
        ana.msg("@bot oi")
        self.bot.receber_tipo(p.BOT_REQ)
        status = [e for e in self.eventos() if isinstance(e, eventos.StatusServidor)]
        self.assertEqual(status[-1].pendentes_bot, 1)


class TestBotAusente(BaseServidor):
    def test_pergunta_sem_bot_conectado(self):
        (ana,) = self.sala("ana")
        pergunta = ana.msg("@bot alô?")
        erro = ana.receber_tipo(p.BOT_ERR)
        self.assertEqual((erro["code"], erro["ref"]), ("BOT_OFFLINE", pergunta["id"]))

    def test_mensagem_para_bot_sem_arroba(self):
        (ana,) = self.sala("ana")
        ana.msg("oi", para="bot")
        erro = ana.receber_tipo(p.ERROR)
        self.assertEqual(erro["code"], "USER_NOT_FOUND")
        self.assertIn("@bot", erro["content"])


if __name__ == "__main__":
    unittest.main()
