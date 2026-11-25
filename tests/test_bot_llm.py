"""Testes da integração com a LLM e do histórico — issues #15 e #16.

Usa um servidor HTTP falso no formato da API do Groq/OpenAI, então roda
sem internet e sem gastar cota. O teste com a LLM real é o
`python -m bot.llm "pergunta"`.

    python -m unittest discover -s tests -v
"""

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bot import llm
from bot.historico import Historicos
from common import config


class ApiFalsa(BaseHTTPRequestHandler):
    """Responde conforme a última mensagem do usuário."""
    recebidos: list = []
    chamadas_cota_curta = 0

    def log_message(self, *args):
        pass

    def do_POST(self):
        corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        ApiFalsa.recebidos.append({"corpo": corpo, "auth": self.headers["Authorization"]})
        pergunta = corpo["messages"][-1]["content"]
        if self.headers["Authorization"] != "Bearer gsk_teste":
            return self._json(401, {"error": {"message": "Invalid API Key"}})
        if pergunta == "cota":
            return self._json(429, {"error": {"message": "rate limit"}})
        if pergunta == "cota_longa":
            return self._json(429, {"error": {"message": "TPM excedido"}}, {"retry-after": "30"})
        if pergunta == "cota_curta":
            ApiFalsa.chamadas_cota_curta += 1
            if ApiFalsa.chamadas_cota_curta == 1:
                return self._json(429, {"error": {"message": "TPM excedido"}}, {"retry-after": "1"})
        if pergunta == "modelo":
            return self._json(404, {"error": {"message": "model does not exist"}})
        if pergunta == "lento":
            time.sleep(1.5)
        if pergunta == "vazio":
            return self._json(200, {"choices": [{"message": {"role": "assistant", "content": ""}}]})
        if pergunta == "markdown":
            texto = "## Dica\n**Reinicie** o `roteador`.\n* passo um\n1. passo dois"
        else:
            n = sum(m["role"] == "user" for m in corpo["messages"])
            texto = f"resposta a '{pergunta}' ({n} mensagens de usuário no contexto)"
        self._json(200, {"choices": [{"message": {"role": "assistant", "content": texto}}]})

    def _json(self, codigo, obj, cabecalhos=None):
        dados = json.dumps(obj).encode()
        self.send_response(codigo)
        for k, v in (cabecalhos or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)


class TestConsultarLLM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), ApiFalsa)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.original = (config.LLM_URL, config.LLM_API_KEY, config.LLM_MODEL)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        config.LLM_URL, config.LLM_API_KEY, config.LLM_MODEL = cls.original

    def setUp(self):
        config.LLM_URL = f"http://127.0.0.1:{self.http.server_port}/openai/v1/chat/completions"
        config.LLM_API_KEY = "gsk_teste"
        config.LLM_MODEL = "openai/gpt-oss-120b"
        ApiFalsa.recebidos.clear()

    def erro(self, pergunta, **kw):
        with self.assertRaises(llm.ErroLLM) as ctx:
            llm.consultar_llm([], pergunta, **kw)
        return ctx.exception

    def test_resposta_com_instrucao_e_historico(self):
        hist = [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "olá"}]
        texto = llm.consultar_llm(hist, "e agora?")
        self.assertIn("2 mensagens de usuário", texto)
        corpo = ApiFalsa.recebidos[-1]["corpo"]
        self.assertEqual(corpo["messages"][0]["role"], "system")
        self.assertIn(config.BOT_PROVEDOR, corpo["messages"][0]["content"])
        self.assertEqual(corpo["reasoning_effort"], "low")
        self.assertEqual(ApiFalsa.recebidos[-1]["auth"], "Bearer gsk_teste")

    def test_reasoning_effort_so_para_gpt_oss(self):
        config.LLM_MODEL = "qwen/qwen3.8-27b"
        llm.consultar_llm([], "oi")
        self.assertNotIn("reasoning_effort", ApiFalsa.recebidos[-1]["corpo"])

    def test_markdown_e_removido(self):
        texto = llm.consultar_llm([], "markdown")
        self.assertEqual(texto, "Dica\nReinicie o roteador.\n- passo um\n1. passo dois")

    def test_codigos_de_erro(self):
        self.assertEqual(self.erro("cota").code, "LLM_RATE_LIMIT")
        self.assertEqual(self.erro("vazio").code, "LLM_UNAVAILABLE")
        e = self.erro("modelo")
        self.assertEqual(e.code, "LLM_UNAVAILABLE")
        self.assertIn("model does not exist", str(e))

    def test_429_com_espera_curta_tenta_de_novo_sozinho(self):
        inicio = time.time()
        texto = llm.consultar_llm([], "cota_curta")
        self.assertIn("cota_curta", texto)
        self.assertGreaterEqual(time.time() - inicio, 0.9)       # esperou o Retry-After
        self.assertEqual(ApiFalsa.chamadas_cota_curta, 2)

    def test_429_com_espera_longa_devolve_erro_na_hora(self):
        inicio = time.time()
        e = self.erro("cota_longa")
        self.assertEqual((e.code, e.detalhe), ("LLM_RATE_LIMIT", "TPM excedido"))
        self.assertLess(time.time() - inicio, 1.0)

    def test_reserva_de_tokens_da_resposta(self):
        llm.consultar_llm([], "oi")
        self.assertEqual(ApiFalsa.recebidos[-1]["corpo"]["max_tokens"], config.LLM_MAX_TOKENS)
        self.assertLessEqual(config.LLM_MAX_TOKENS, 800)

    def test_chave_invalida_e_ausente(self):
        config.LLM_API_KEY = "gsk_errada"
        self.assertEqual(self.erro("oi").code, "LLM_AUTH")
        config.LLM_API_KEY = ""
        self.assertEqual(self.erro("oi").code, "LLM_AUTH")

    def test_tempo_limite(self):
        inicio = time.time()
        e = self.erro("lento", timeout=0.5)
        self.assertEqual(e.code, "LLM_TIMEOUT")
        self.assertLess(time.time() - inicio, 1.4)

    def test_sem_rede(self):
        config.LLM_URL = "http://127.0.0.1:1/nada"
        self.assertEqual(self.erro("oi").code, "LLM_UNAVAILABLE")


class TestHistoricos(unittest.TestCase):
    def test_limite_de_trocas(self):
        h = Historicos(trocas=3)
        for i in range(5):
            h.registrar("ana", f"p{i}", f"r{i}")
        conteudos = [m["content"] for m in h.obter("ana")]
        self.assertEqual(conteudos, ["p2", "r2", "p3", "r3", "p4", "r4"])

    def test_usuarios_isolados(self):
        h = Historicos()
        h.registrar("ana", "meu roteador é TP-Link", "ok")
        self.assertEqual(h.obter("bruno"), [])
        self.assertEqual(len(h.obter("Ana")), 2)          # nome sem diferenciar maiúsculas

    def test_obter_devolve_copia(self):
        h = Historicos()
        h.registrar("ana", "p", "r")
        h.obter("ana").clear()
        self.assertEqual(len(h.obter("ana")), 2)

    def test_esquecer(self):
        h = Historicos()
        h.registrar("ana", "p", "r")
        h.esquecer("ana")
        self.assertEqual(h.obter("ana"), [])

    def test_varias_threads_ao_mesmo_tempo(self):
        h = Historicos(trocas=1000)
        def registrar(nome):
            for i in range(200):
                h.registrar(nome, f"p{i}", f"r{i}")
        threads = [threading.Thread(target=registrar, args=(f"u{n}",)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(h.usuarios()), 8)
        self.assertTrue(all(len(h.obter(f"u{n}")) == 400 for n in range(8)))


class TestInstrucao(unittest.TestCase):
    """Prompt adaptado do material da Bruna (issue #3)."""

    def test_base_de_luzes_so_quando_o_assunto_e_equipamento(self):
        marca = "LOS apagada: normal"                   # trecho que só existe na base de luzes
        self.assertNotIn(marca, llm.instrucao_sistema([], "quais os planos de vocês?"))
        self.assertIn(marca, llm.instrucao_sistema([], "a luz LOS está vermelha"))
        self.assertIn(marca, llm.instrucao_sistema([], "estou sem internet"))
        hist = [{"role": "user", "content": "meu roteador está com uma luz piscando"},
                {"role": "assistant", "content": "Qual luz?"}]
        self.assertIn(marca, llm.instrucao_sistema(hist, "continua igual"))

    def test_data_e_hora_e_provedor(self):
        from datetime import datetime
        texto = llm.instrucao_sistema([], "oi", momento=datetime(2026, 11, 29, 10, 30))
        self.assertIn("domingo, 29/11/2026, 10:30", texto)
        self.assertIn(config.BOT_PROVEDOR, texto)
        self.assertNotIn("{", texto)                     # nenhum campo sem preencher

    def test_regras_essenciais_presentes(self):
        texto = llm.instrucao_sistema([], "oi").lower()
        for regra in ("fibra", "reset", "sem markdown", "não acessa o sistema", "cancelamento"):
            self.assertIn(regra, texto)

    def test_cabe_no_limite_do_plano_gratuito(self):
        """Pior caso de ENTRADA: base de luzes + histórico cheio de respostas longas + pergunta longa.
        O plano gratuito do gpt-oss-120b permite 8 mil tokens por minuto; abaixo de 3,5 mil por
        pergunta cabem ao menos 2 perguntas por minuto mesmo no pior caso.
        O prompt original da Bruna sozinho já passaria de 8 mil."""
        h = Historicos()
        for _ in range(10):
            h.registrar("ana", "x" * 300, "y" * 2000)        # respostas longas são cortadas no histórico
        hist = h.obter("ana")
        sistema = llm.instrucao_sistema(hist, "a luz LOS está vermelha")
        entrada = (llm.estimar_tokens(sistema) + sum(llm.estimar_tokens(m["content"]) for m in hist)
                   + llm.estimar_tokens("z" * 400))
        self.assertLess(entrada, 3500, entrada)
        original = (llm.PASTA_PROMPTS / "original" / "prompt_assistente_virtual_net.txt").read_text(encoding="utf-8")
        self.assertGreater(llm.estimar_tokens(original), 8000)  # por isso foi condensado

    def test_prompt_original_continua_guardado(self):
        self.assertTrue((llm.PASTA_PROMPTS / "original" / "prompt_assistente_virtual_net.txt").is_file())

    def test_negrito_de_um_asterisco_e_removido(self):
        self.assertEqual(llm.limpar_markdown("O plano *400 Mega* custa R$ 89,90"),
                         "O plano 400 Mega custa R$ 89,90")
        self.assertEqual(llm.limpar_markdown("2 * 3 = 6"), "2 * 3 = 6")


if __name__ == "__main__":
    unittest.main()
