"""Testes da camada de protocolo (issue #4).

Executar a partir da raiz do projeto:
    python -m unittest discover -s tests -v
"""

import json
import socket
import threading
import unittest

from common import config
from common.protocolo import (
    BOT_REQ, BOT_RESP, HELLO, MSG, USERS, TODOS,
    ErroProtocolo, LeitorDeMensagens, codificar, enviar, extrair_pergunta_bot,
    novo_envelope, validar, validar_nome,
)


class SocketFalso:
    """Simula um socket cujo recv devolve pedaços pré-definidos.

    Permite reproduzir de forma determinística o que o TCP faz na prática:
    partir uma mensagem em vários recv ou juntar várias num só.
    """

    def __init__(self, pedacos):
        self.pedacos = list(pedacos)

    def recv(self, _n):
        if not self.pedacos:
            return b""
        item = self.pedacos.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def ler_todas(leitor):
    saida = []
    while (env := leitor.proximo()) is not None:
        saida.append(env)
    return saida


class TestFraming(unittest.TestCase):
    def test_ida_e_volta(self):
        env = novo_envelope(MSG, "ana", TODOS, "olá, pessoal")
        lidos = ler_todas(LeitorDeMensagens(SocketFalso([codificar(env)])))
        self.assertEqual(lidos, [env])

    def test_mensagem_partida_byte_a_byte(self):
        env = novo_envelope(MSG, "ana", TODOS, "mensagem partida em vários recv")
        dados = codificar(env)
        pedacos = [dados[i:i + 1] for i in range(len(dados))]
        self.assertEqual(ler_todas(LeitorDeMensagens(SocketFalso(pedacos))), [env])

    def test_varias_mensagens_no_mesmo_recv(self):
        envs = [novo_envelope(MSG, "ana", TODOS, f"msg {i}") for i in range(5)]
        junto = b"".join(codificar(e) for e in envs)
        self.assertEqual(ler_todas(LeitorDeMensagens(SocketFalso([junto]))), envs)

    def test_corte_no_meio_de_um_caractere_utf8(self):
        env = novo_envelope(MSG, "ana", TODOS, "conexão ç ã é 🚀")
        dados = codificar(env)
        meio = dados.index("ç".encode()) + 1        # corta entre os 2 bytes do "ç"
        lidos = ler_todas(LeitorDeMensagens(SocketFalso([dados[:meio], dados[meio:]])))
        self.assertEqual(lidos[0]["content"], "conexão ç ã é 🚀")

    def test_quebra_de_linha_no_texto_nao_quebra_o_framing(self):
        env = novo_envelope(MSG, "ana", TODOS, "linha 1\nlinha 2")
        dados = codificar(env)
        self.assertEqual(dados.count(b"\n"), 1)      # só o delimitador final
        self.assertEqual(ler_todas(LeitorDeMensagens(SocketFalso([dados])))[0]["content"],
                         "linha 1\nlinha 2")

    def test_linhas_vazias_sao_ignoradas(self):
        env = novo_envelope(MSG, "ana", TODOS, "oi")
        lidos = ler_todas(LeitorDeMensagens(SocketFalso([b"\n\n" + codificar(env)])))
        self.assertEqual(lidos, [env])

    def test_fim_da_conexao_devolve_none(self):
        self.assertIsNone(LeitorDeMensagens(SocketFalso([])).proximo())

    def test_mensagem_incompleta_no_fechamento_e_descartada(self):
        dados = codificar(novo_envelope(MSG, "ana", TODOS, "oi"))
        self.assertIsNone(LeitorDeMensagens(SocketFalso([dados[:10]])).proximo())

    def test_reset_da_conexao_devolve_none(self):
        self.assertIsNone(LeitorDeMensagens(SocketFalso([ConnectionResetError()])).proximo())

    def test_timeout_e_repassado(self):
        leitor = LeitorDeMensagens(SocketFalso([socket.timeout()]))
        with self.assertRaises(TimeoutError):
            leitor.proximo()


class TestErros(unittest.TestCase):
    def ler_erro(self, pedacos):
        with self.assertRaises(ErroProtocolo) as ctx:
            LeitorDeMensagens(SocketFalso(pedacos)).proximo()
        return ctx.exception

    def test_mensagem_grande_sem_delimitador(self):
        bloco = b"x" * 4096
        e = self.ler_erro([bloco] * (config.TAMANHO_MAXIMO // 4096 + 1))
        self.assertEqual((e.code, e.fatal), ("MSG_TOO_LARGE", True))

    def test_json_invalido_e_fatal(self):
        e = self.ler_erro([b"isto nao e json\n"])
        self.assertEqual((e.code, e.fatal), ("BAD_MESSAGE", True))

    def test_bytes_que_nao_sao_utf8(self):
        e = self.ler_erro([b"\xff\xfe\xfd\n"])
        self.assertEqual((e.code, e.fatal), ("BAD_MESSAGE", True))

    def test_campo_faltando_nao_e_fatal_e_a_leitura_continua(self):
        ruim = novo_envelope(MSG, "ana", TODOS, "oi")
        del ruim["to"]
        boa = novo_envelope(MSG, "ana", TODOS, "segunda")
        leitor = LeitorDeMensagens(SocketFalso([
            (json.dumps(ruim) + "\n").encode() + codificar(boa)]))
        with self.assertRaises(ErroProtocolo) as ctx:
            leitor.proximo()
        self.assertEqual((ctx.exception.code, ctx.exception.fatal, ctx.exception.ref),
                         ("BAD_MESSAGE", False, ruim["id"]))
        self.assertEqual(leitor.proximo(), boa)

    def test_tipo_desconhecido(self):
        env = novo_envelope("FOO", "ana", TODOS, "oi")
        with self.assertRaises(ErroProtocolo) as ctx:
            validar(env)
        self.assertEqual((ctx.exception.code, ctx.exception.fatal), ("UNKNOWN_TYPE", False))

    def test_versao_errada_e_fatal(self):
        env = novo_envelope(MSG, "ana", TODOS, "oi")
        env["v"] = 2
        with self.assertRaises(ErroProtocolo) as ctx:
            validar(env)
        self.assertEqual((ctx.exception.code, ctx.exception.fatal), ("VERSION_UNSUPPORTED", True))

    def test_campos_especificos_por_tipo(self):
        casos = [
            novo_envelope(HELLO, "ana", "servidor"),                      # sem role
            novo_envelope(HELLO, "ana", "servidor", role="admin"),        # role inválido
            novo_envelope(BOT_RESP, "bot", "ana", "resposta"),            # sem ref
            novo_envelope(BOT_REQ, "servidor", "bot", "pergunta", ref="x"),  # sem on_behalf_of
            novo_envelope(MSG, "ana", TODOS, "   "),                      # MSG vazia
            novo_envelope(USERS, "servidor", TODOS, "ana"),               # USERS sem lista
        ]
        for env in casos:
            with self.subTest(env=env), self.assertRaises(ErroProtocolo):
                validar(env)

    def test_envelopes_validos_de_cada_tipo(self):
        casos = [
            novo_envelope(HELLO, "ana", "servidor", role="human"),
            novo_envelope(USERS, "servidor", TODOS, ["ana", "bot"]),
            novo_envelope(BOT_REQ, "servidor", "bot", "oi", ref="m1", on_behalf_of="ana"),
            novo_envelope(BOT_RESP, "bot", "ana", "olá", ref="m1"),
        ]
        for env in casos:
            with self.subTest(tipo=env["type"]):
                self.assertIs(validar(env), env)

    def test_codificar_recusa_mensagem_grande(self):
        env = novo_envelope(MSG, "ana", TODOS, "x" * config.TAMANHO_MAXIMO)
        with self.assertRaises(ErroProtocolo):
            codificar(env)


class TestIdentificacao(unittest.TestCase):
    def test_nomes(self):
        self.assertIsNone(validar_nome("ana"))
        self.assertIsNone(validar_nome("Bruno_2-x"))
        self.assertEqual(validar_nome(""), "NAME_INVALID")
        self.assertEqual(validar_nome("ana maria"), "NAME_INVALID")
        self.assertEqual(validar_nome("joão"), "NAME_INVALID")
        self.assertEqual(validar_nome("a" * 21), "NAME_INVALID")
        self.assertEqual(validar_nome("BOT"), "NAME_RESERVED")
        self.assertEqual(validar_nome("servidor"), "NAME_RESERVED")
        self.assertIsNone(validar_nome("bot", papel="bot"))
        self.assertEqual(validar_nome("outro", papel="bot"), "NAME_INVALID")

    def test_pergunta_ao_bot(self):
        self.assertEqual(extrair_pergunta_bot("@bot minha internet caiu"), "minha internet caiu")
        self.assertEqual(extrair_pergunta_bot("  @BOT   oi  "), "oi")
        self.assertEqual(extrair_pergunta_bot("@bot"), "")
        self.assertIsNone(extrair_pergunta_bot("@botzinho oi"))
        self.assertIsNone(extrair_pergunta_bot("oi @bot"))
        self.assertIsNone(extrair_pergunta_bot("bom dia"))


class TestSocketReal(unittest.TestCase):
    """Mesmo cenário com sockets de verdade (socketpair), em paralelo."""

    def test_200_mensagens_enviadas_por_outra_thread(self):
        a, b = socket.socketpair()
        envs = [novo_envelope(MSG, "ana", TODOS, f"mensagem número {i} " + "é" * i)
                for i in range(200)]

        def enviar_tudo():
            for env in envs:
                enviar(a, env)
            a.close()

        t = threading.Thread(target=enviar_tudo)
        t.start()
        recebidos = ler_todas(LeitorDeMensagens(b))
        t.join()
        b.close()
        self.assertEqual(recebidos, envs)


if __name__ == "__main__":
    unittest.main()
