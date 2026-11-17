"""Janela do servidor: participantes, mensagens e eventos (requisito 2 e 3 do edital)."""

import queue
import time
import tkinter as tk
from tkinter import ttk

from interface.tema import CORES, FONTE_MONO, selo

CORES_EVENTO = {
    "info": CORES["destaque"],
    "join": CORES["ok"],
    "leave": CORES["sutil"],
    "erro": CORES["erro"],
    "bot": CORES["bot"],
}

TIPOS_FILTRO = ["Todos", "MSG", "BOT_REQ", "BOT_RESP", "BOT_ERR", "ERROR"]


class JanelaServidor:
    def __init__(self, master: tk.Misc, fila: queue.Queue, ao_alternar_bot, ao_desconectar):
        self.fila = fila
        self.ao_alternar_bot = ao_alternar_bot
        self.ao_desconectar = ao_desconectar
        self.total_msgs = 0
        self.mensagens = []  # guardadas para reaplicar o filtro

        self.janela = master
        self.janela.title("Servidor de Chat — SD2")
        self.janela.configure(bg=CORES["fundo"])

        self._montar_cabecalho()
        self._montar_corpo()
        self._montar_rodape()
        self.janela.after(100, self._consumir_fila)

    # ---------------- layout ----------------
    def _montar_cabecalho(self):
        topo = ttk.Frame(self.janela, padding=(14, 12, 14, 6))
        topo.pack(fill="x")
        ttk.Label(topo, text="Servidor de Chat", style="Titulo.TLabel").pack(side="left")
        ttk.Label(topo, text="  Sistemas Distribuídos II", style="Sutil.TLabel").pack(side="left")

        selos = ttk.Frame(topo)
        selos.pack(side="right")
        selo(selos, "TCP :5000", CORES["aviso"]).pack(side="left", padx=3)
        selo(selos, "TLS :5001", CORES["ok"]).pack(side="left", padx=3)
        self.selo_bot = selo(selos, "Bot online", CORES["bot"])
        self.selo_bot.pack(side="left", padx=3)

    def _montar_corpo(self):
        divisor = ttk.PanedWindow(self.janela, orient="horizontal")
        divisor.pack(fill="both", expand=True, padx=14, pady=6)

        # --- coluna esquerda: participantes ---
        esq = ttk.Frame(divisor, style="Painel.TFrame", padding=10)
        ttk.Label(esq, text="PARTICIPANTES", style="Secao.TLabel").pack(anchor="w")
        colunas = ("papel", "endereco", "canal", "desde")
        self.arvore_part = ttk.Treeview(esq, columns=colunas, show="tree headings", height=10)
        self.arvore_part.heading("#0", text="Nome")
        self.arvore_part.column("#0", width=70, minwidth=60)
        for col, titulo, larg in [("papel", "Papel", 68), ("endereco", "Endereço", 120),
                                  ("canal", "Canal", 78), ("desde", "Desde", 66)]:
            self.arvore_part.heading(col, text=titulo)
            self.arvore_part.column(col, width=larg, anchor="w")
        self.arvore_part.tag_configure("bot", foreground=CORES["bot"])
        self.arvore_part.tag_configure("tls", foreground=CORES["ok"])
        self.arvore_part.pack(fill="both", expand=True, pady=(6, 8))

        botoes = ttk.Frame(esq, style="Painel.TFrame")
        botoes.pack(fill="x")
        ttk.Button(botoes, text="Desconectar selecionado", style="Perigo.TButton",
                   command=self._desconectar_selecionado).pack(fill="x")
        ttk.Button(botoes, text="Simular falha do bot (timeout da LLM)",
                   command=self.ao_alternar_bot).pack(fill="x", pady=(6, 0))
        divisor.add(esq, weight=0)

        # --- coluna direita: mensagens (cima) e eventos (baixo) ---
        dir_ = ttk.PanedWindow(divisor, orient="vertical")

        msgs = ttk.Frame(dir_, style="Painel.TFrame", padding=10)
        linha = ttk.Frame(msgs, style="Painel.TFrame")
        linha.pack(fill="x")
        ttk.Label(linha, text="MENSAGENS TRAFEGADAS", style="Secao.TLabel").pack(side="left")
        self.filtro = ttk.Combobox(linha, values=TIPOS_FILTRO, state="readonly", width=11)
        self.filtro.set("Todos")
        self.filtro.bind("<<ComboboxSelected>>", lambda e: self._reaplicar_filtro())
        self.filtro.pack(side="right")
        ttk.Label(linha, text="Tipo:", style="SutilPainel.TLabel").pack(side="right", padx=4)

        colunas = ("hora", "id", "tipo", "de", "para", "conteudo")
        self.arvore_msg = ttk.Treeview(msgs, columns=colunas, show="headings", height=12)
        for col, titulo, larg in [("hora", "Hora", 70), ("id", "ID", 80), ("tipo", "Tipo", 80),
                                  ("de", "De", 70), ("para", "Para", 70), ("conteudo", "Conteúdo", 380)]:
            self.arvore_msg.heading(col, text=titulo)
            self.arvore_msg.column(col, width=larg, anchor="w", stretch=(col == "conteudo"))
        for tipo, cor in [("BOT_REQ", CORES["bot"]), ("BOT_RESP", CORES["bot"]),
                          ("BOT_ERR", CORES["erro"]), ("ERROR", CORES["erro"]),
                          ("privada", CORES["privado"])]:
            self.arvore_msg.tag_configure(tipo, foreground=cor)
        rolagem = ttk.Scrollbar(msgs, orient="vertical", command=self.arvore_msg.yview)
        self.arvore_msg.configure(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y", pady=(6, 0))
        self.arvore_msg.pack(fill="both", expand=True, pady=(6, 0))
        dir_.add(msgs, weight=3)

        evts = ttk.Frame(dir_, style="Painel.TFrame", padding=10)
        ttk.Label(evts, text="EVENTOS", style="Secao.TLabel").pack(anchor="w")
        self.texto_evt = tk.Text(evts, height=8, bg=CORES["painel"], fg=CORES["texto"],
                                 font=FONTE_MONO, relief="flat", wrap="word",
                                 highlightthickness=0, state="disabled")
        for nivel, cor in CORES_EVENTO.items():
            self.texto_evt.tag_configure(nivel, foreground=cor)
        self.texto_evt.tag_configure("hora", foreground=CORES["sutil"])
        self.texto_evt.pack(fill="both", expand=True, pady=(6, 0))
        dir_.add(evts, weight=2)

        divisor.add(dir_, weight=5)

    def _montar_rodape(self):
        rod = ttk.Frame(self.janela, padding=(14, 4, 14, 10))
        rod.pack(fill="x")
        self.lbl_status = ttk.Label(rod, style="Sutil.TLabel",
                                    text="Conectados: 0   •   Mensagens: 0   •   Pedidos ao bot pendentes: 0")
        self.lbl_status.pack(side="left")
        ttk.Label(rod, text="threads ativas: 1 por cliente + aceitação", style="Sutil.TLabel").pack(side="right")

    # ---------------- ações ----------------
    def _desconectar_selecionado(self):
        sel = self.arvore_part.selection()
        if sel and sel[0] != "bot":
            self.ao_desconectar(sel[0], "foi desconectado pelo servidor")

    # ---------------- fila (thread-safe) ----------------
    def _consumir_fila(self):
        try:
            while True:
                item = self.fila.get_nowait()
                tipo = item[0]
                if tipo == "evento":
                    self._log_evento(item[1], item[2])
                elif tipo == "participante+":
                    p = item[1]
                    tags = ("bot",) if p["papel"] == "bot" else (("tls",) if "TLS" in p["canal"] else ())
                    self.arvore_part.insert("", "end", iid=p["nome"], text=p["nome"], tags=tags,
                                            values=(p["papel"], p["endereco"], p["canal"], p["desde"]))
                elif tipo == "participante-":
                    if self.arvore_part.exists(item[1]):
                        self.arvore_part.delete(item[1])
                elif tipo == "mensagem":
                    self.total_msgs += 1
                    self.mensagens.append(item[1])
                    self._inserir_msg(item[1])
                elif tipo == "status":
                    self._atualizar_status(item[1])
        except queue.Empty:
            pass
        self.janela.after(100, self._consumir_fila)

    def _inserir_msg(self, env):
        filtro = self.filtro.get()
        if filtro != "Todos" and env["type"] != filtro:
            return
        tag = env["type"]
        if env["type"] == "MSG" and env["to"] == "bot":
            tag = "BOT_REQ"
        elif env["type"] == "MSG" and env["to"] != "*":
            tag = "privada"
        conteudo = env["content"] if isinstance(env["content"], str) else str(env["content"])
        self.arvore_msg.insert("", "end", tags=(tag,), values=(
            time.strftime("%H:%M:%S", time.localtime(env["ts"])), env["id"], env["type"],
            env["from"], "todos" if env["to"] == "*" else env["to"], conteudo))
        self.arvore_msg.yview_moveto(1)

    def _reaplicar_filtro(self):
        self.arvore_msg.delete(*self.arvore_msg.get_children())
        for env in self.mensagens:
            self._inserir_msg(env)

    def _log_evento(self, nivel, texto):
        self.texto_evt.configure(state="normal")
        self.texto_evt.insert("end", time.strftime("%H:%M:%S  "), "hora")
        self.texto_evt.insert("end", f"[{nivel.upper():5}] {texto}\n", nivel)
        self.texto_evt.see("end")
        self.texto_evt.configure(state="disabled")

    def _atualizar_status(self, st):
        self.lbl_status.configure(
            text=f"Conectados: {st['conectados']}   •   Mensagens: {self.total_msgs}"
                 f"   •   Pedidos ao bot pendentes: {st['pendentes']}")
        if st["bot"]:
            self.selo_bot.configure(text="● Bot online", fg=CORES["bot"])
        else:
            self.selo_bot.configure(text="● Bot em falha", fg=CORES["erro"])
