"""Testes da criptografia — issues #18, #19, #20 e #21.

Gera certificados numa pasta temporária (precisa de `pip install cryptography`
ou do OpenSSL), sobe o servidor com as portas TCP e TLS e confere:
  * conexão TLS funcionando junto com conexões sem criptografia;
  * cliente RECUSA certificado de outra CA e certificado com nome errado (#21);
  * bytes na rede: a mensagem aparece legível na porta TCP e NÃO aparece na TLS
    (o mesmo que o Wireshark vai mostrar — #22).

    python -m unittest discover -s tests -v
"""

import queue
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from bot.rede import BotRede
from certs.gerar_certificados import gerar
from cliente.rede import ClienteRede, ErroConexao
from common import eventos, tls
from common import protocolo as p
from servidor.nucleo import ServidorChat

SEGREDO = "SEGREDO-SD2-roteador-TP-Link"


class Interceptador:
    """Repassa uma conexão TCP e guarda os bytes que passam (um 'Wireshark' mínimo)."""

    def __init__(self, porta_destino: int):
        self.destino = porta_destino
        self.capturado = bytearray()
        self.escuta = socket.create_server(("127.0.0.1", 0))
        self.porta = self.escuta.getsockname()[1]
        threading.Thread(target=self._aceitar, daemon=True).start()

    def _aceitar(self):
        try:
            cliente, _ = self.escuta.accept()
        except OSError:
            return
        servidor = socket.create_connection(("127.0.0.1", self.destino))
        threading.Thread(target=self._repassar, args=(cliente, servidor, True), daemon=True).start()
        threading.Thread(target=self._repassar, args=(servidor, cliente, False), daemon=True).start()

    def _repassar(self, origem, destino, guardar):
        try:
            while dados := origem.recv(4096):
                if guardar:
                    self.capturado += dados
                destino.sendall(dados)
        except OSError:
            pass
        for s in (origem, destino):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()

    def fechar(self):
        self.escuta.close()


def esperar(fila, condicao, timeout=3.0):
    limite = time.time() + timeout
    while time.time() < limite:
        try:
            item = fila.get(timeout=0.1)
        except queue.Empty:
            continue
        if condicao(item):
            return item
    raise AssertionError("não chegou")


def msg_com(texto):
    return lambda it: (isinstance(it, eventos.EnvelopeRecebido) and it.envelope["type"] == p.MSG
                       and it.envelope["content"] == texto)


class TestTLS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.certs = base / "certs"
        gerar(cls.certs)
        cls.outra_ca = base / "outra_ca"
        gerar(cls.outra_ca, nome_ca="CA desconhecida")
        cls.nome_errado = base / "nome_errado"
        gerar(cls.nome_errado, sans_dns=["servidor-errado.local"], sans_ip=[])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def subir(self, pasta: Path):
        self.fila_srv = queue.Queue()
        ctx = tls.contexto_servidor(pasta / "servidor.crt", pasta / "servidor.key")
        self.servidor = ServidorChat(self.fila_srv, porta=0, porta_tls=0, contexto_tls=ctx)
        self.servidor.iniciar()
        portas = self.servidor.portas_abertas
        self.porta = next(v for k, v in portas.items() if k.startswith("TCP"))
        self.porta_tls = next(v for k, v in portas.items() if k.startswith("TLS"))

    def setUp(self):
        self.redes = []

    def tearDown(self):
        for r in self.redes:
            r.sair()
        self.servidor.parar()

    def cliente(self, nome, tls_=False, porta=None, cafile=None):
        fila = queue.Queue()
        rede = ClienteRede(fila)
        rede.conectar(nome, porta=porta or (self.porta_tls if tls_ else self.porta), usar_tls=tls_,
                      cafile=cafile or self.certs / "ca.crt")
        self.redes.append(rede)
        return rede, fila

    def eventos_servidor(self):
        textos = []
        while not self.fila_srv.empty():
            item = self.fila_srv.get_nowait()
            if isinstance(item, eventos.EventoServidor):
                textos.append(item.texto)
        return textos

    # ------------------------------------------------------------ canal funcionando
    def test_cliente_tls_conversa_com_cliente_sem_tls(self):
        self.subir(self.certs)
        ana, fila_ana = self.cliente("ana", tls_=True)
        bruno, fila_bruno = self.cliente("bruno")
        self.assertEqual(ana.canal, f"TLS :{self.porta_tls}")
        self.assertTrue(ana.sessao_tls.startswith("TLSv1."), ana.sessao_tls)
        ana.enviar_sala("oi pelo TLS")
        esperar(fila_bruno, msg_com("oi pelo TLS"))
        bruno.enviar_sala("oi pelo TCP")
        esperar(fila_ana, msg_com("oi pelo TCP"))
        self.assertTrue(any("Sessão TLS" in t for t in self.eventos_servidor()))

    def test_bot_por_tls(self):
        self.subir(self.certs)
        bot = BotRede(porta=self.porta_tls, usar_tls=True, cafile=self.certs / "ca.crt",
                      consultar=lambda h, q: f"ok: {q}", log=lambda *_: None)
        threading.Thread(target=bot.executar, daemon=True).start()
        try:
            time.sleep(0.3)
            ana, fila = self.cliente("ana", tls_=True)
            ana.perguntar_bot("teste")
            resp = esperar(fila, lambda it: isinstance(it, eventos.EnvelopeRecebido)
                           and it.envelope["type"] == p.BOT_RESP)
            self.assertEqual(resp.envelope["content"], "ok: teste")
        finally:
            bot.parar()

    # ------------------------------------------------------------ validação (#21)
    def test_recusa_certificado_de_outra_ca(self):
        self.subir(self.outra_ca)                    # servidor apresenta certificado de CA desconhecida
        with self.assertRaises(ErroConexao) as ctx:
            self.cliente("ana", tls_=True)           # cliente só confia na CA de self.certs
        self.assertIn("RECUSADO", str(ctx.exception))
        self.assertIn("certificate", str(ctx.exception).lower())

    def test_recusa_certificado_com_nome_errado(self):
        self.subir(self.nome_errado)                 # CA confiável, mas o certificado não vale para 127.0.0.1
        with self.assertRaises(ErroConexao) as ctx:
            self.cliente("ana", tls_=True, cafile=self.nome_errado / "ca.crt")
        self.assertIn("RECUSADO", str(ctx.exception))
        self.assertIn("127.0.0.1", str(ctx.exception))

    def test_sem_arquivo_da_ca(self):
        self.subir(self.certs)
        with self.assertRaises(ErroConexao) as ctx:
            self.cliente("ana", tls_=True, cafile=Path(self.tmp.name) / "nao_existe.crt")
        self.assertIn("não encontrado", str(ctx.exception))

    def test_cliente_sem_tls_na_porta_tls_nao_derruba_o_servidor(self):
        self.subir(self.certs)
        with self.assertRaises(ErroConexao):
            self.cliente("ana", porta=self.porta_tls)        # fala JSON puro com a porta TLS
        time.sleep(0.2)
        self.assertTrue(any("Handshake TLS recusado" in t for t in self.eventos_servidor()))
        self.cliente("bruno", tls_=True)                     # servidor continua atendendo

    def test_cliente_tls_na_porta_sem_tls(self):
        self.subir(self.certs)
        with self.assertRaises(ErroConexao):
            self.cliente("ana", tls_=True, porta=self.porta)

    # ------------------------------------------------------------ bytes na rede (#22)
    def _capturar(self, usar_tls: bool) -> bytes:
        self.subir(self.certs)
        _, fila_bruno = self.cliente("bruno")
        intercepta = Interceptador(self.porta_tls if usar_tls else self.porta)
        try:
            ana, _ = self.cliente("ana", tls_=usar_tls, porta=intercepta.porta)
            ana.enviar_sala(SEGREDO)
            esperar(fila_bruno, msg_com(SEGREDO))
            return bytes(intercepta.capturado)
        finally:
            intercepta.fechar()

    def test_sem_tls_a_mensagem_aparece_legivel_na_rede(self):
        self.assertIn(SEGREDO.encode(), self._capturar(usar_tls=False))

    def test_com_tls_a_mensagem_nao_aparece_na_rede(self):
        capturado = self._capturar(usar_tls=True)
        self.assertGreater(len(capturado), 200)               # houve tráfego...
        self.assertNotIn(SEGREDO.encode(), capturado)          # ...mas o texto não aparece
        self.assertNotIn(b'"type"', capturado)                 # nem a estrutura do JSON
        self.assertEqual(capturado[0], 0x16)                   # 0x16 = registro TLS Handshake


if __name__ == "__main__":
    unittest.main()
