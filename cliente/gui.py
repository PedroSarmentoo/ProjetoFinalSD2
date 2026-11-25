"""Interface gráfica do cliente humano.

Responsável: Bruna — issue #14. Baseada no protótipo da branch `teste`.

Duas telas na mesma janela:
  1. Conexão — nome, host, porta e "Usar TLS".
  2. Chat — sala, mensagens privadas (clique num nome) e perguntas ao bot.

Regra do edital: digitar nunca pode travar quando chega mensagem. Por isso
a janela não lê o socket: a ClienteRede tem uma thread de recepção que põe
tudo numa fila, e aqui a fila é consumida a cada 100 ms com root.after().
A conexão (que pode demorar até 5 s) também roda em outra thread.
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from cliente.rede import ClienteRede, ErroConexao
from common import config, eventos
from common.tema import CORES, FONTE, FONTE_NEGRITO, FONTE_PEQUENA, aplicar_tema, selo

INTERVALO_MS = 100
TODOS = "Todos (sala)"


class JanelaCliente:
    def __init__(self, root: tk.Tk, rede: ClienteRede, fila: queue.Queue, nome_inicial: str = ""):
        self.root = root
        self.rede = rede
        self.fila = fila
        self.destino = "*"
        self.pendentes: dict[str, str] = {}          # id da pergunta -> texto
        self._resultado_conexao: queue.Queue = queue.Queue()

        root.title("Chat SD2")
        root.geometry("640x520")
        root.minsize(520, 420)
        root.configure(bg=CORES["fundo"])
        aplicar_tema(root)
        root.protocol("WM_DELETE_WINDOW", self._fechar_janela)

        self.tela_conexao = self._montar_tela_conexao(nome_inicial)
        self.tela_chat = self._montar_tela_chat()
        self._mostrar(self.tela_conexao)
        root.after(INTERVALO_MS, self._consumir_fila)

    # ================================================================ tela de conexão
    def _montar_tela_conexao(self, nome_inicial: str) -> ttk.Frame:
        tela = ttk.Frame(self.root, padding=30)
        caixa = ttk.Frame(tela, style="Painel.TFrame", padding=24)
        caixa.place(relx=0.5, rely=0.45, anchor="center")

        ttk.Label(caixa, text="Entrar no chat", style="Titulo.TLabel",
                  background=CORES["painel"]).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))

        self.var_nome = tk.StringVar(value=nome_inicial)
        self.var_host = tk.StringVar(value=config.HOST)
        self.var_porta = tk.StringVar(value=str(config.PORTA))
        self.var_tls = tk.BooleanVar(value=False)

        for linha, (rotulo, var) in enumerate([("Nome", self.var_nome), ("Servidor", self.var_host),
                                               ("Porta", self.var_porta)], start=1):
            ttk.Label(caixa, text=rotulo, style="SutilPainel.TLabel").grid(row=linha, column=0, sticky="w", pady=4)
            entrada = ttk.Entry(caixa, textvariable=var, width=26)
            entrada.grid(row=linha, column=1, sticky="ew", pady=4, padx=(10, 0))
            if rotulo == "Nome":
                self.entrada_nome = entrada
        ttk.Label(caixa, text="1 a 20 letras sem acento, números, _ ou -", style="SutilPainel.TLabel",
                  font=FONTE_PEQUENA).grid(row=4, column=1, sticky="w", padx=(10, 0))

        tls = tk.Checkbutton(caixa, text="Usar TLS (conexão cifrada, porta 5001)", variable=self.var_tls,
                             command=self._alternar_tls, bg=CORES["painel"], fg=CORES["texto"],
                             selectcolor=CORES["painel2"], activebackground=CORES["painel"],
                             activeforeground=CORES["texto"], highlightthickness=0, font=FONTE)
        tls.grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 4))

        self.btn_conectar = ttk.Button(caixa, text="Conectar", style="Primario.TButton", command=self._conectar)
        self.btn_conectar.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.lbl_erro_conexao = tk.Label(caixa, text="", fg=CORES["erro"], bg=CORES["painel"], font=FONTE,
                                         wraplength=320, justify="left")
        self.lbl_erro_conexao.grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))

        for e in (self.entrada_nome,):
            e.bind("<Return>", lambda _e: self._conectar())
        return tela

    def _alternar_tls(self):
        """Ao marcar/desmarcar TLS, troca a porta padrão (5000 <-> 5001)."""
        padroes = {str(config.PORTA), str(config.PORTA_TLS)}
        if self.var_porta.get() in padroes:
            self.var_porta.set(str(config.PORTA_TLS if self.var_tls.get() else config.PORTA))

    def _conectar(self):
        nome, host = self.var_nome.get().strip(), self.var_host.get().strip()
        try:
            porta = int(self.var_porta.get())
        except ValueError:
            self.lbl_erro_conexao.configure(text="Porta inválida.")
            return
        if not nome:
            self.lbl_erro_conexao.configure(text="Digite um nome.")
            return
        self.btn_conectar.configure(state="disabled", text="Conectando…")
        self.lbl_erro_conexao.configure(text="")
        usar_tls = self.var_tls.get()

        def tentar():                                # roda fora da thread da GUI
            try:
                self.rede.conectar(nome, host=host, porta=porta, usar_tls=usar_tls)
                self._resultado_conexao.put(None)
            except ErroConexao as e:
                self._resultado_conexao.put(str(e))

        threading.Thread(target=tentar, name="conectando", daemon=True).start()

    def _conexao_concluida(self, erro: str | None):
        self.btn_conectar.configure(state="normal", text="Conectar")
        if erro:
            self.lbl_erro_conexao.configure(text=erro)
            return
        self.root.title(f"Chat SD2 — {self.rede.nome}")
        self.lbl_nome.configure(text=self.rede.nome)
        cifrado = self.rede.canal.startswith("TLS")
        self.selo_canal.configure(text=f"● {self.rede.canal} — {'cifrado' if cifrado else 'sem criptografia'}",
                                  fg=CORES["ok"] if cifrado else CORES["aviso"])
        self._limpar_chat()
        self.pendentes.clear()
        self._definir_destino("*")
        self.entrada.configure(state="normal")
        self.btn_enviar.configure(state="normal")
        self.btn_bot.configure(state="normal")
        self.btn_sair.configure(text="Sair")
        self._mostrar(self.tela_chat)
        self.entrada.focus_set()

    # ================================================================ tela de chat
    def _montar_tela_chat(self) -> ttk.Frame:
        tela = ttk.Frame(self.root)

        topo = ttk.Frame(tela, padding=(12, 10, 12, 6))
        topo.pack(fill="x")
        self.lbl_nome = ttk.Label(topo, text="", style="Titulo.TLabel")
        self.lbl_nome.pack(side="left")
        self.selo_canal = selo(topo, "", CORES["sutil"])
        self.selo_canal.pack(side="right")

        # Rodapé e barra de digitação são empacotados ANTES do corpo (side="bottom"):
        # assim continuam visíveis mesmo com a janela pequena.
        rodape = ttk.Frame(tela, padding=(12, 0, 12, 10))
        rodape.pack(side="bottom", fill="x")
        base = ttk.Frame(tela, padding=(12, 8, 12, 4))
        base.pack(side="bottom", fill="x")

        corpo = ttk.Frame(tela, padding=(12, 0))
        corpo.pack(fill="both", expand=True)

        lado = ttk.Frame(corpo, style="Painel.TFrame", padding=8)
        lado.pack(side="right", fill="y", padx=(8, 0))
        caixa = ttk.Frame(corpo, style="Painel.TFrame", padding=2)
        caixa.pack(side="left", fill="both", expand=True)
        self.chat = tk.Text(caixa, bg=CORES["painel"], fg=CORES["texto"], font=FONTE, relief="flat",
                            wrap="word", padx=10, pady=8, highlightthickness=0, state="disabled",
                            spacing1=2, spacing3=4, width=40, height=10)
        rolagem = ttk.Scrollbar(caixa, orient="vertical", command=self.chat.yview)
        self.chat.configure(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y")
        self.chat.pack(fill="both", expand=True)
        t = self.chat.tag_configure
        t("hora", foreground=CORES["sutil"], font=FONTE_PEQUENA)
        t("autor", font=FONTE_NEGRITO, foreground=CORES["destaque"])
        t("eu", font=FONTE_NEGRITO, foreground=CORES["ok"])
        t("privada", foreground=CORES["privado"])
        t("bot", foreground=CORES["bot"])
        t("bot_autor", font=FONTE_NEGRITO, foreground=CORES["bot"])
        t("sistema", foreground=CORES["sutil"], font=(FONTE[0], 9, "italic"))
        t("erro", foreground=CORES["erro"])

        ttk.Label(lado, text="ONLINE", style="Secao.TLabel").pack(anchor="w")
        self.lista = tk.Listbox(lado, bg=CORES["painel"], fg=CORES["texto"], width=15, height=8, relief="flat",
                                highlightthickness=0, font=FONTE, selectbackground="#1f3a5f",
                                activestyle="none", exportselection=False)
        self.lista.pack(fill="y", expand=True, pady=(6, 4))
        self.lista.bind("<<ListboxSelect>>", self._clicou_na_lista)
        ttk.Label(lado, text="clique num nome para\nconversar no privado", style="SutilPainel.TLabel",
                  justify="left", font=FONTE_PEQUENA).pack(anchor="w")

        self.lbl_destino = ttk.Label(base, text="", style="Sutil.TLabel")
        self.lbl_destino.pack(anchor="w")
        linha = ttk.Frame(base)
        linha.pack(fill="x", pady=(4, 0))
        self.entrada = ttk.Entry(linha)
        self.entrada.pack(side="left", fill="x", expand=True)
        self.entrada.bind("<Return>", lambda _e: self._enviar())
        self.btn_enviar = ttk.Button(linha, text="Enviar", style="Primario.TButton", command=self._enviar)
        self.btn_enviar.pack(side="left", padx=(6, 0))
        self.btn_bot = ttk.Button(linha, text="@bot", command=self._prefixar_bot)
        self.btn_bot.pack(side="left", padx=(6, 0))

        self.lbl_pendentes = ttk.Label(rodape, text="", style="Sutil.TLabel")
        self.lbl_pendentes.pack(side="left")
        self.btn_sair = ttk.Button(rodape, text="Sair", style="Perigo.TButton", command=self._sair)
        self.btn_sair.pack(side="right")
        return tela

    def _mostrar(self, tela: ttk.Frame):
        for t in (self.tela_conexao, self.tela_chat):
            t.pack_forget()
        tela.pack(fill="both", expand=True)

    # ================================================================ ações do usuário
    def _clicou_na_lista(self, _evento):
        sel = self.lista.curselection()
        if sel:
            escolhido = self.lista.get(sel[0])
            self._definir_destino("*" if escolhido == TODOS else escolhido)
        self.entrada.focus_set()

    def _definir_destino(self, destino: str):
        self.destino = destino
        self.lbl_destino.configure(text=f"Para: {TODOS}" if destino == "*" else f"Para: {destino} (privado)")

    def _prefixar_bot(self):
        if not self.entrada.get().lower().startswith("@bot"):
            self.entrada.insert(0, "@bot ")
        self.entrada.focus_set()
        self.entrada.icursor("end")

    def _enviar(self):
        texto = self.entrada.get().strip()
        if not texto or not self.rede.conectado:
            return
        self.entrada.delete(0, "end")
        try:
            if texto.lower() == "@bot" or texto.lower().startswith("@bot "):
                pergunta = texto[4:].strip()
                if not pergunta:
                    self._sistema("Escreva a pergunta depois de @bot.", "erro")
                    return
                id_msg = self.rede.perguntar_bot(pergunta)
                self.pendentes[id_msg] = pergunta
                self._linha(f"você → bot #{id_msg[:6]}", pergunta, "eu", "bot")
            elif self.destino == "*":
                self.rede.enviar_sala(texto)
                self._linha("você", texto, "eu")
            else:
                self.rede.enviar_privada(self.destino, texto)
                self._linha(f"você → {self.destino}", texto, "eu", "privada")
        except ErroConexao as e:
            self._sistema(str(e), "erro")
        self._atualizar_pendentes()

    def _sair(self):
        if self.rede.conectado:
            self.rede.sair()
        else:
            self.lbl_erro_conexao.configure(text="")
            self._mostrar(self.tela_conexao)

    def _fechar_janela(self):
        if self.rede.conectado:
            self.rede.sair()
        self.root.destroy()

    # ================================================================ recepção (via fila)
    def _consumir_fila(self):
        try:
            while True:
                self._conexao_concluida(self._resultado_conexao.get_nowait())
        except queue.Empty:
            pass
        try:
            for _ in range(200):
                item = self.fila.get_nowait()
                if isinstance(item, eventos.EnvelopeRecebido):
                    self._tratar(item.envelope)
                elif isinstance(item, eventos.ConexaoEncerrada):
                    self._conexao_perdida(item.motivo)
        except queue.Empty:
            pass
        self.root.after(INTERVALO_MS, self._consumir_fila)

    def _tratar(self, env: dict):
        tipo = env["type"]
        if tipo == "WELCOME":
            self._sistema(env["content"])
        elif tipo == "USERS":
            self._atualizar_lista(env["content"])
        elif tipo == "JOIN":
            self._sistema(f"{env['content']} entrou")
        elif tipo == "LEAVE":
            motivo = {"LEFT": "saiu", "KICKED": "foi desconectado pelo servidor"}.get(env.get("code"), "caiu")
            self._sistema(f"{env['content']} {motivo}")
        elif tipo == "MSG":
            if env["to"] == "*":
                self._linha(env["from"], env["content"], "autor")
            else:
                self._linha(f"{env['from']} (privado)", env["content"], "autor", "privada")
        elif tipo == "BOT_RESP":
            self.pendentes.pop(env["ref"], None)
            self._linha(f"bot ↩ #{env['ref'][:6]}", env["content"], "bot_autor", "bot")
        elif tipo == "BOT_ERR":
            self.pendentes.pop(env["ref"], None)
            self._linha(f"bot ✕ #{env['ref'][:6]}", env["content"], "bot_autor", "erro")
        elif tipo == "ERROR":
            if env.get("ref"):
                self.pendentes.pop(env["ref"], None)
            self._sistema(f"Erro: {env['content']}", "erro")
        self._atualizar_pendentes()

    def _conexao_perdida(self, motivo: str):
        self._sistema(motivo, "erro")
        self._atualizar_lista([])
        for widget in (self.entrada, self.btn_enviar, self.btn_bot):
            widget.configure(state="disabled")
        self.btn_sair.configure(text="Voltar à tela de conexão")
        self.pendentes.clear()
        self._atualizar_pendentes()
        self.selo_canal.configure(text="● desconectado", fg=CORES["erro"])

    # ================================================================ desenho
    def _atualizar_lista(self, nomes: list[str]):
        self.lista.delete(0, "end")
        if not nomes:
            return
        self.lista.insert("end", TODOS)
        for n in nomes:
            if n != self.rede.nome:
                self.lista.insert("end", n)
                if n == "bot":
                    self.lista.itemconfigure("end", foreground=CORES["bot"])
        if self.destino != "*" and self.destino not in nomes:
            self._sistema(f"{self.destino} saiu — voltando para a sala.")
            self._definir_destino("*")

    def _linha(self, autor: str, texto: str, tag_autor: str, tag_texto: str | None = None):
        self.chat.configure(state="normal")
        self.chat.insert("end", time.strftime("%H:%M  "), "hora")
        self.chat.insert("end", f"{autor}: ", tag_autor)
        self.chat.insert("end", f"{texto}\n", tag_texto or ())
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def _sistema(self, texto: str, tag: str = "sistema"):
        self.chat.configure(state="normal")
        self.chat.insert("end", f"— {texto}\n", tag)
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def _limpar_chat(self):
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")

    def _atualizar_pendentes(self):
        if self.pendentes:
            ids = ", ".join(f"#{i[:6]}" for i in self.pendentes)
            self.lbl_pendentes.configure(text=f"⏳ aguardando o bot ({ids}) — pode continuar conversando")
        else:
            self.lbl_pendentes.configure(text="")
