"""Janela do cliente humano: chat público, mensagens privadas e perguntas ao bot."""

import queue
import time
import tkinter as tk
from tkinter import ttk

from interface.tema import CORES, FONTE, FONTE_NEGRITO, selo

TODOS = "Todos (sala)"


class JanelaCliente:
    def __init__(self, master: tk.Toplevel, nome: str, tls: bool, hub, novo_envelope):
        self.nome = nome
        self.tls = tls
        self.hub = hub
        self.novo_envelope = novo_envelope
        self.fila = queue.Queue()      # o hub (ou, no real, a thread de recepção) escreve aqui
        self.destino = "*"
        self.pendentes = {}            # id -> pergunta ao bot ainda sem resposta
        self.conectado = False

        self.janela = master
        self.janela.title(f"Chat — {nome}")
        self.janela.configure(bg=CORES["fundo"])
        self.janela.protocol("WM_DELETE_WINDOW", self._fechar)

        self._montar()
        self.janela.after(100, self._consumir_fila)
        self.conectado = self.hub.conectar(nome, self.fila, tls)

    # ---------------- layout ----------------
    def _montar(self):
        topo = ttk.Frame(self.janela, padding=(12, 10, 12, 6))
        topo.pack(fill="x")
        ttk.Label(topo, text=self.nome, style="Titulo.TLabel").pack(side="left")
        if self.tls:
            selo(topo, "TLS :5001 — cifrado", CORES["ok"]).pack(side="right")
        else:
            selo(topo, "TCP :5000 — sem criptografia", CORES["aviso"]).pack(side="right")

        corpo = ttk.Frame(self.janela, padding=(12, 0))
        corpo.pack(fill="both", expand=True)

        # área de mensagens
        caixa = ttk.Frame(corpo, style="Painel.TFrame", padding=2)
        caixa.pack(side="left", fill="both", expand=True)
        self.chat = tk.Text(caixa, bg=CORES["painel"], fg=CORES["texto"], font=FONTE,
                            relief="flat", wrap="word", padx=10, pady=8,
                            highlightthickness=0, state="disabled", spacing1=2, spacing3=4)
        rolagem = ttk.Scrollbar(caixa, orient="vertical", command=self.chat.yview)
        self.chat.configure(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y")
        self.chat.pack(fill="both", expand=True)
        t = self.chat.tag_configure
        t("hora", foreground=CORES["sutil"], font=("DejaVu Sans", 8))
        t("autor", font=FONTE_NEGRITO, foreground=CORES["destaque"])
        t("eu", font=FONTE_NEGRITO, foreground=CORES["ok"])
        t("privada", foreground=CORES["privado"])
        t("bot", foreground=CORES["bot"])
        t("bot_autor", font=FONTE_NEGRITO, foreground=CORES["bot"])
        t("sistema", foreground=CORES["sutil"], font=("DejaVu Sans", 9, "italic"))
        t("erro", foreground=CORES["erro"])

        # lista de usuários
        lado = ttk.Frame(corpo, style="Painel.TFrame", padding=8)
        lado.pack(side="right", fill="y", padx=(8, 0))
        ttk.Label(lado, text="ONLINE", style="Secao.TLabel").pack(anchor="w")
        self.lista = tk.Listbox(lado, bg=CORES["painel"], fg=CORES["texto"], width=14,
                                relief="flat", highlightthickness=0, font=FONTE,
                                selectbackground="#1f3a5f", activestyle="none")
        self.lista.pack(fill="y", expand=True, pady=(6, 4))
        self.lista.bind("<<ListboxSelect>>", self._escolher_destino)
        ttk.Label(lado, text="clique para\nconversar no privado", style="SutilPainel.TLabel",
                  justify="left", font=("DejaVu Sans", 8)).pack(anchor="w")

        # barra de envio
        base = ttk.Frame(self.janela, padding=(12, 8, 12, 4))
        base.pack(fill="x")
        self.lbl_destino = ttk.Label(base, text=f"Para: {TODOS}", style="Sutil.TLabel")
        self.lbl_destino.pack(anchor="w")
        linha = ttk.Frame(base)
        linha.pack(fill="x", pady=(4, 0))
        self.entrada = ttk.Entry(linha)
        self.entrada.pack(side="left", fill="x", expand=True)
        self.entrada.bind("<Return>", lambda e: self._enviar())
        ttk.Button(linha, text="Enviar", style="Primario.TButton",
                   command=self._enviar).pack(side="left", padx=(6, 0))
        ttk.Button(linha, text="@bot", command=self._prefixar_bot).pack(side="left", padx=(6, 0))

        rod = ttk.Frame(self.janela, padding=(12, 0, 12, 10))
        rod.pack(fill="x")
        self.lbl_pendente = ttk.Label(rod, text="", style="Sutil.TLabel")
        self.lbl_pendente.pack(side="left")
        ttk.Button(rod, text="Sair", style="Perigo.TButton", command=self._fechar).pack(side="right")
        self.entrada.focus_set()

    # ---------------- ações ----------------
    def _escolher_destino(self, _evento):
        sel = self.lista.curselection()
        if not sel:
            return
        escolhido = self.lista.get(sel[0])
        self.destino = "*" if escolhido == TODOS else escolhido
        self.lbl_destino.configure(
            text=f"Para: {TODOS}" if self.destino == "*" else f"Para: {self.destino} (privado)")

    def _prefixar_bot(self):
        if not self.entrada.get().lower().startswith("@bot"):
            self.entrada.insert(0, "@bot ")
        self.entrada.focus_set()

    def _enviar(self):
        texto = self.entrada.get().strip()
        if not texto or not self.conectado:
            return
        self.entrada.delete(0, "end")
        para_bot = texto.lower().startswith("@bot")
        env = self.novo_envelope("MSG", self.nome, "bot" if para_bot else self.destino, texto)
        if para_bot:
            self.pendentes[env["id"]] = texto
            self._escrever_linha("você → bot", texto, "eu", "bot")
        elif self.destino == "*":
            self._escrever_linha("você", texto, "eu")
        else:
            self._escrever_linha(f"você → {self.destino}", texto, "eu", "privada")
        self._atualizar_pendentes()
        # No projeto real isto é: socket.sendall((json.dumps(env) + "\n").encode())
        self.hub.enviar(env)

    def _fechar(self):
        if self.conectado:
            self.hub.desconectar(self.nome)
        self.janela.destroy()

    # ---------------- recepção (thread-safe via fila) ----------------
    def _consumir_fila(self):
        try:
            while True:
                self._tratar(self.fila.get_nowait())
        except queue.Empty:
            pass
        if self.janela.winfo_exists():
            self.janela.after(100, self._consumir_fila)

    def _tratar(self, env):
        tipo = env["type"]
        if tipo == "USERS":
            self.lista.delete(0, "end")
            self.lista.insert("end", TODOS)
            for n in env["content"]:
                if n != self.nome:
                    self.lista.insert("end", n)
        elif tipo == "MSG":
            if env["to"] == "*":
                self._escrever_linha(env["from"], env["content"], "autor")
            else:
                self._escrever_linha(f"{env['from']} (privado)", env["content"], "autor", "privada")
        elif tipo == "BOT_RESP":
            self.pendentes.pop(env["id"], None)
            self._escrever_linha(f"bot  ↩ #{env['id']}", env["content"], "bot_autor", "bot")
        elif tipo == "BOT_ERR":
            self.pendentes.pop(env["id"], None)
            self._escrever_linha(f"bot  ✕ #{env['id']}", env["content"], "bot_autor", "erro")
        elif tipo in ("JOIN", "LEAVE", "WELCOME"):
            self._escrever_sistema(env["content"])
        elif tipo == "ERROR":
            self._escrever_sistema(f"Erro: {env['content']}", "erro")
        elif tipo == "BYE":
            self.conectado = False
            self._escrever_sistema(env["content"], "erro")
            self.lista.delete(0, "end")
        self._atualizar_pendentes()

    # ---------------- escrita no chat ----------------
    def _escrever_linha(self, autor, texto, tag_autor, tag_texto=None):
        self.chat.configure(state="normal")
        self.chat.insert("end", time.strftime("%H:%M  "), "hora")
        self.chat.insert("end", f"{autor}: ", tag_autor)
        self.chat.insert("end", f"{texto}\n", tag_texto or ())
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def _escrever_sistema(self, texto, tag="sistema"):
        self.chat.configure(state="normal")
        self.chat.insert("end", f"— {texto}\n", tag)
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def _atualizar_pendentes(self):
        n = len(self.pendentes)
        if n:
            ids = ", ".join(f"#{i}" for i in self.pendentes)
            self.lbl_pendente.configure(text=f"⏳ aguardando o bot ({ids}) — você pode continuar digitando")
        else:
            self.lbl_pendente.configure(text="")
