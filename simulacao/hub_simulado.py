"""Hub simulado: faz o papel do servidor de sockets SÓ para o protótipo visual.

No projeto real, cada cliente fala com o servidor por um socket TCP/TLS e o
servidor tem uma thread por conexão. Aqui tudo roda em um processo, mas a
lógica de roteamento é a mesma que o servidor real vai ter:

  * MSG para "*"        -> todos os outros humanos
  * MSG para "fulano"   -> só fulano (privada)
  * conteúdo "@bot ..." -> BOT_REQ ao bot -> BOT_RESP só ao solicitante

As janelas nunca são tocadas por threads de trabalho: tudo passa por
queue.Queue, e cada janela consome sua fila com after() (tkinter não é
thread-safe). Esse é o mesmo padrão que a GUI real vai usar.
"""

import queue
import random
import threading
import time
import uuid
from collections import deque

LIMITE_HISTORICO = 3  # trocas (pergunta+resposta) guardadas por usuário


def novo_envelope(tipo, remetente, destinatario, conteudo, id_req=None):
    return {
        "v": 1,
        "type": tipo,
        "id": id_req or uuid.uuid4().hex[:8],
        "from": remetente,
        "to": destinatario,
        "ts": time.time(),
        "content": conteudo,
    }


class HubSimulado:
    def __init__(self, fila_servidor: queue.Queue):
        self.fila_servidor = fila_servidor
        self._lock = threading.Lock()          # protege _clientes e _pendentes
        self._clientes = {}                     # nome -> {fila, tls, endereco}
        self._pendentes = {}                    # id -> solicitante
        self._historico = {}                    # nome -> deque de trocas
        self.bot_online = True
        self._evento("info", "Servidor iniciado — TCP :5000 (texto puro) e TLS :5001")
        self._evento("bot", "Bot conectado (llm=simulada, histórico=3 trocas/usuário)")
        self.fila_servidor.put(("participante+", {
            "nome": "bot", "papel": "bot", "endereco": "127.0.0.1:49152",
            "canal": "TCP :5000", "desde": time.strftime("%H:%M:%S")}))

    # ---------- ciclo de vida ----------
    def conectar(self, nome, fila_cliente, tls):
        endereco = f"127.0.0.1:{random.randint(50000, 60999)}"
        with self._lock:
            if nome in self._clientes:
                fila_cliente.put(novo_envelope("ERROR", "servidor", nome, "Nome já em uso"))
                return False
            self._clientes[nome] = {"fila": fila_cliente, "tls": tls, "endereco": endereco}
        canal = "TLS :5001" if tls else "TCP :5000"
        self.fila_servidor.put(("participante+", {
            "nome": nome, "papel": "humano", "endereco": endereco,
            "canal": canal, "desde": time.strftime("%H:%M:%S")}))
        self._evento("join", f"{nome} entrou ({endereco}, {canal})")
        fila_cliente.put(novo_envelope("WELCOME", "servidor", nome,
                                       f"Conectado como {nome} via {canal}"))
        self._difundir(novo_envelope("JOIN", "servidor", "*", f"{nome} entrou"), excluir=nome)
        self._difundir_usuarios()
        return True

    def desconectar(self, nome, motivo="saiu"):
        with self._lock:
            info = self._clientes.pop(nome, None)
            self._historico.pop(nome, None)
            orfaos = [i for i, s in self._pendentes.items() if s == nome]
            for i in orfaos:
                self._pendentes.pop(i)
        if not info:
            return
        info["fila"].put(novo_envelope("BYE", "servidor", nome, f"Desconectado: {motivo}"))
        self.fila_servidor.put(("participante-", nome))
        nivel = "leave" if motivo == "saiu" else "erro"
        self._evento(nivel, f"{nome} {motivo}" + (f" — {len(orfaos)} pedido(s) ao bot descartado(s)" if orfaos else ""))
        self._difundir(novo_envelope("LEAVE", "servidor", "*", f"{nome} {motivo}"))
        self._difundir_usuarios()
        self._atualizar_status()

    def alternar_bot(self):
        self.bot_online = not self.bot_online
        if self.bot_online:
            self._evento("bot", "Bot reconectado")
        else:
            self._evento("erro", "Falha simulada: bot sem resposta da LLM (timeout)")
        self._atualizar_status()

    # ---------- roteamento ----------
    def enviar(self, env):
        self.fila_servidor.put(("mensagem", env))
        texto = env["content"].strip()
        if texto.lower().startswith("@bot"):
            self._pedir_ao_bot(env, texto[4:].strip())
        elif env["to"] == "*":
            self._difundir(env, excluir=env["from"])
        else:
            with self._lock:
                destino = self._clientes.get(env["to"])
            if destino:
                destino["fila"].put(env)
            else:
                self._responder_erro(env, f"Destinatário '{env['to']}' não está online")

    def _pedir_ao_bot(self, env, pergunta):
        req = novo_envelope("BOT_REQ", "servidor", "bot", pergunta, id_req=env["id"])
        req["on_behalf_of"] = env["from"]
        self.fila_servidor.put(("mensagem", req))
        with self._lock:
            self._pendentes[env["id"]] = env["from"]
        self._atualizar_status()
        threading.Thread(target=self._trabalho_bot, args=(req,), daemon=True).start()

    def _trabalho_bot(self, req):
        """Simula o bot consultando a LLM: demora alguns segundos.

        Enquanto isso, os outros clientes continuam conversando — é
        exatamente o cenário de concorrência que a demonstração exige.
        """
        usuario = req["on_behalf_of"]
        time.sleep(random.uniform(2.0, 4.0))
        with self._lock:
            ainda_pendente = self._pendentes.pop(req["id"], None)
        if not ainda_pendente:
            return  # solicitante desconectou
        if not self.bot_online:
            resp = novo_envelope("BOT_ERR", "bot", usuario,
                                 "A LLM não respondeu dentro do tempo limite (15 s). Tente novamente.",
                                 id_req=req["id"])
        else:
            with self._lock:
                hist = self._historico.setdefault(usuario, deque(maxlen=LIMITE_HISTORICO))
                hist.append(req["content"])
                n = len(hist)
            resp = novo_envelope(
                "BOT_RESP", "bot", usuario,
                f"[resposta simulada] Você perguntou: “{req['content']}”. "
                f"Seu contexto tem {n}/{LIMITE_HISTORICO} trocas — só suas, "
                f"sem misturar com outros usuários.",
                id_req=req["id"])
        self.fila_servidor.put(("mensagem", resp))
        with self._lock:
            destino = self._clientes.get(usuario)
        if destino:
            destino["fila"].put(resp)
        self._atualizar_status()

    # ---------- utilitários ----------
    def _difundir(self, env, excluir=None):
        with self._lock:
            filas = [i["fila"] for n, i in self._clientes.items() if n != excluir]
        for f in filas:
            f.put(env)

    def _difundir_usuarios(self):
        with self._lock:
            nomes = sorted(self._clientes)
        self._difundir(novo_envelope("USERS", "servidor", "*", nomes))
        self._atualizar_status()

    def _responder_erro(self, env, texto):
        erro = novo_envelope("ERROR", "servidor", env["from"], texto, id_req=env["id"])
        self.fila_servidor.put(("mensagem", erro))
        with self._lock:
            origem = self._clientes.get(env["from"])
        if origem:
            origem["fila"].put(erro)

    def _evento(self, nivel, texto):
        self.fila_servidor.put(("evento", nivel, texto))

    def _atualizar_status(self):
        with self._lock:
            st = {"conectados": len(self._clientes), "pendentes": len(self._pendentes),
                  "bot": self.bot_online}
        self.fila_servidor.put(("status", st))
