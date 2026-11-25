"""Testes da rede do bot — issue #11.

Servidor real + BotRede real + clientes reais. A LLM é substituída por uma
função local (sem internet), então os tempos são previsíveis.

    python -m unittest discover -s tests -v
"""

import queue
import threading
import time
import unittest

from bot.historico import Historicos
from bot.llm import ErroLLM
from bot.rede import BotRede, ErroBot
from cliente.rede import ClienteRede
from common import eventos
from common import protocolo as p
from servidor.nucleo import ServidorChat


def llm_falsa(historico, pergunta):
    if pergunta == "falha":
        raise ErroLLM("LLM_RATE_LIMIT", "Limite de uso da LLM atingido.")
    if pergunta == "quebra":
        raise RuntimeError("bug inesperado")
    if pergunta.startswith("lento"):
        time.sleep(1.0)
    anteriores = [m["content"] for m in historico if m["role"] == "user"]
    return f"resp({pergunta}) contexto={anteriores}"


def esperar_tipo(fila, tipo, timeout=4.0):
    limite = time.time() + timeout
    while time.time() < limite:
        try:
            item = fila.get(timeout=0.1)
        except queue.Empty:
            continue
        if isinstance(item, eventos.EnvelopeRecebido) and item.envelope["type"] == tipo:
            return item.envelope
    raise AssertionError(f"{tipo} não chegou")


class TestBotRede(unittest.TestCase):
    def setUp(self):
        self.servidor = ServidorChat(queue.Queue(), porta=0, porta_tls=None, timeout_bot=5)
        self.servidor.iniciar()
        self.porta = next(iter(self.servidor.portas_abertas.values()))
        self.bot = BotRede(porta=self.porta, consultar=llm_falsa, historicos=Historicos(trocas=3),
                           log=lambda *_: None)
        self.thread_bot = threading.Thread(target=self.bot.executar, daemon=True)
        self.thread_bot.start()
        time.sleep(0.3)
        self.redes = []

    def tearDown(self):
        for r in self.redes:
            r.sair()
        self.bot.parar()
        self.servidor.parar()

    def cliente(self, nome):
        fila = queue.Queue()
        rede = ClienteRede(fila)
        rede.conectar(nome, porta=self.porta)
        self.redes.append(rede)
        return rede, fila

    def test_responde_com_ref_e_usuario_corretos(self):
        ana, fila = self.cliente("ana")
        id_pergunta = ana.perguntar_bot("oi")
        resp = esperar_tipo(fila, p.BOT_RESP)
        self.assertEqual((resp["ref"], resp["from"], resp["content"]),
                         (id_pergunta, "bot", "resp(oi) contexto=[]"))

    def test_historico_por_usuario(self):
        ana, fila_ana = self.cliente("ana")
        bruno, fila_bruno = self.cliente("bruno")
        ana.perguntar_bot("meu roteador é TP-Link")
        esperar_tipo(fila_ana, p.BOT_RESP)
        ana.perguntar_bot("qual a marca?")
        self.assertIn("TP-Link", esperar_tipo(fila_ana, p.BOT_RESP)["content"])
        bruno.perguntar_bot("qual a marca?")
        self.assertEqual(esperar_tipo(fila_bruno, p.BOT_RESP)["content"], "resp(qual a marca?) contexto=[]")

    def test_consultas_em_paralelo(self):
        """Duas perguntas lentas (1 s cada) de usuários diferentes terminam em ~1 s, não 2 s."""
        ana, fila_ana = self.cliente("ana")
        bruno, fila_bruno = self.cliente("bruno")
        inicio = time.time()
        ana.perguntar_bot("lento da ana")
        bruno.perguntar_bot("lento do bruno")
        esperar_tipo(fila_ana, p.BOT_RESP)
        esperar_tipo(fila_bruno, p.BOT_RESP)
        self.assertLess(time.time() - inicio, 1.8)

    def test_falha_da_llm_vira_bot_err(self):
        ana, fila = self.cliente("ana")
        id_pergunta = ana.perguntar_bot("falha")
        erro = esperar_tipo(fila, p.BOT_ERR)
        self.assertEqual((erro["code"], erro["ref"]), ("LLM_RATE_LIMIT", id_pergunta))

    def test_erro_inesperado_nao_derruba_o_bot(self):
        ana, fila = self.cliente("ana")
        ana.perguntar_bot("quebra")
        self.assertEqual(esperar_tipo(fila, p.BOT_ERR)["code"], "LLM_UNAVAILABLE")
        ana.perguntar_bot("ainda vivo?")
        self.assertIn("ainda vivo?", esperar_tipo(fila, p.BOT_RESP)["content"])

    def test_segundo_bot_e_recusado(self):
        with self.assertRaises(ErroBot) as ctx:
            BotRede(porta=self.porta, consultar=llm_falsa, log=lambda *_: None).conectar()
        self.assertIn("já existe um bot", str(ctx.exception))

    def test_bot_sem_servidor(self):
        self.servidor.parar()
        time.sleep(0.2)
        with self.assertRaises(ErroBot):
            BotRede(porta=self.porta, consultar=llm_falsa, log=lambda *_: None).conectar()


if __name__ == "__main__":
    unittest.main()
