"""Testes da camada de rede do cliente — issue #10.

Usa o ServidorChat real numa porta livre e clientes ClienteRede de verdade.

    python -m unittest discover -s tests -v
"""

import queue
import socket
import threading
import time
import unittest

from cliente.rede import ClienteRede, ErroConexao
from common import eventos
from common import protocolo as p
from servidor.nucleo import ServidorChat


def esperar(fila: queue.Queue, condicao, timeout: float = 3.0):
    """Tira itens da fila até um satisfazer `condicao` (ou falha no tempo)."""
    limite = time.time() + timeout
    while time.time() < limite:
        try:
            item = fila.get(timeout=0.1)
        except queue.Empty:
            continue
        if condicao(item):
            return item
    raise AssertionError("o item esperado não chegou na fila")


def envelope(tipo):
    return lambda item: isinstance(item, eventos.EnvelopeRecebido) and item.envelope["type"] == tipo


def encerrada(item):
    return isinstance(item, eventos.ConexaoEncerrada)


class BotFalso:
    """Bot mínimo: responde cada BOT_REQ depois de `atraso` segundos."""

    def __init__(self, porta: int, atraso: float = 0.0):
        self.sock = socket.create_connection(("127.0.0.1", porta))
        self.atraso = atraso
        leitor = p.LeitorDeMensagens(self.sock)
        p.enviar(self.sock, p.novo_envelope(p.HELLO, "bot", "servidor", "", role="bot"))
        assert leitor.proximo()["type"] == p.WELCOME
        threading.Thread(target=self._loop, args=(leitor,), daemon=True).start()

    def _loop(self, leitor):
        while (env := leitor.proximo()) is not None:
            if env["type"] == p.BOT_REQ:
                threading.Thread(target=self._responder, args=(env,), daemon=True).start()

    def _responder(self, req):
        time.sleep(self.atraso)
        p.enviar(self.sock, p.novo_envelope(p.BOT_RESP, "bot", req["on_behalf_of"],
                                            f"resposta para: {req['content']}", ref=req["ref"]))

    def fechar(self):
        self.sock.close()


class TestClienteRede(unittest.TestCase):
    def setUp(self):
        self.servidor = ServidorChat(queue.Queue(), porta=0, porta_tls=None, timeout_bot=2.0)
        self.servidor.iniciar()
        self.porta = next(iter(self.servidor.portas_abertas.values()))
        self.redes = []

    def tearDown(self):
        for r in self.redes:
            r.sair()
        self.servidor.parar()

    def novo(self, nome: str):
        fila = queue.Queue()
        rede = ClienteRede(fila)
        rede.conectar(nome, porta=self.porta)
        self.redes.append(rede)
        return rede, fila

    def test_conectar_recebe_welcome_e_lista(self):
        rede, fila = self.novo("ana")
        self.assertTrue(rede.conectado)
        self.assertEqual((rede.nome, rede.canal), ("ana", f"TCP :{self.porta}"))
        esperar(fila, envelope(p.WELCOME))
        self.assertEqual(esperar(fila, envelope(p.USERS)).envelope["content"], ["ana"])

    def test_nome_recusado_vira_erro_legivel(self):
        self.novo("ana")
        with self.assertRaises(ErroConexao) as ctx:
            ClienteRede(queue.Queue()).conectar("Ana", porta=self.porta)
        self.assertIn("já está em uso", str(ctx.exception))

    def test_servidor_desligado(self):
        self.servidor.parar()
        with self.assertRaises(ErroConexao) as ctx:
            ClienteRede(queue.Queue()).conectar("ana", porta=self.porta)
        self.assertIn("servidor está rodando", str(ctx.exception))

    def test_tls_sem_certificado_da_ca(self):
        with self.assertRaises(ErroConexao) as ctx:
            ClienteRede(queue.Queue()).conectar("ana", porta=self.porta, usar_tls=True,
                                                cafile="pasta_que_nao_existe/ca.crt")
        self.assertIn("não encontrado", str(ctx.exception))

    def test_sala_e_privada(self):
        ana, _ = self.novo("ana")
        _, fila_bruno = self.novo("bruno")
        _, fila_carla = self.novo("carla")
        id_sala = ana.enviar_sala("bom dia")
        for fila in (fila_bruno, fila_carla):
            msg = esperar(fila, envelope(p.MSG)).envelope
            self.assertEqual((msg["id"], msg["from"], msg["content"]), (id_sala, "ana", "bom dia"))
        ana.enviar_privada("bruno", "só pra você")
        self.assertEqual(esperar(fila_bruno, envelope(p.MSG)).envelope["content"], "só pra você")
        with self.assertRaises(AssertionError):
            esperar(fila_carla, envelope(p.MSG), timeout=0.4)

    def test_pergunta_ao_bot_volta_com_o_mesmo_ref(self):
        bot = BotFalso(self.porta)
        try:
            ana, fila = self.novo("ana")
            id_pergunta = ana.perguntar_bot("minha internet caiu")
            resp = esperar(fila, envelope(p.BOT_RESP)).envelope
            self.assertEqual(resp["ref"], id_pergunta)
            self.assertEqual(resp["content"], "resposta para: minha internet caiu")
        finally:
            bot.fechar()

    def test_envio_nao_bloqueia_enquanto_o_bot_pensa(self):
        bot = BotFalso(self.porta, atraso=1.0)
        try:
            ana, fila_ana = self.novo("ana")
            bruno, fila_bruno = self.novo("bruno")
            ana.perguntar_bot("pergunta demorada")
            inicio = time.time()
            for i in range(10):
                ana.enviar_sala(f"msg {i}")
                esperar(fila_bruno, lambda it, i=i: envelope(p.MSG)(it) and it.envelope["content"] == f"msg {i}")
            self.assertLess(time.time() - inicio, 0.9)          # tudo antes da resposta do bot
            esperar(fila_ana, envelope(p.BOT_RESP))
        finally:
            bot.fechar()

    def test_saida_voluntaria(self):
        ana, fila_ana = self.novo("ana")
        _, fila_bruno = self.novo("bruno")
        ana.sair()
        self.assertFalse(ana.conectado)
        self.assertEqual(esperar(fila_ana, encerrada).motivo, "Você saiu do chat.")
        leave = esperar(fila_bruno, envelope(p.LEAVE)).envelope
        self.assertEqual((leave["content"], leave["code"]), ("ana", "LEFT"))

    def test_expulso_pelo_servidor(self):
        _, fila = self.novo("ana")
        self.servidor.expulsar("ana")
        self.assertIn("desconectado pelo servidor", esperar(fila, encerrada).motivo)

    def test_servidor_encerrado(self):
        ana, fila = self.novo("ana")
        self.servidor.parar()
        self.assertIn("servidor foi encerrado", esperar(fila, encerrada).motivo)
        with self.assertRaises(ErroConexao):
            ana.enviar_sala("alguém aí?")

    def test_queda_sem_aviso_do_servidor(self):
        _, fila = self.novo("ana")
        with self.servidor._lock:
            conexao = self.servidor._clientes["ana"]
        conexao.fechar()                                         # derruba sem BYE
        self.assertEqual(esperar(fila, encerrada).motivo, "A conexão com o servidor caiu.")


if __name__ == "__main__":
    unittest.main()
