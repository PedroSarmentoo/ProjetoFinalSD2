"""Interface gráfica do servidor (obrigatória pelo edital).

Responsável: Bruna — issue #13. Baseada no protótipo da branch `teste`.

Mostra em tempo real:
  * participantes conectados (nome, papel, endereço, canal TCP/TLS, desde);
  * mensagens trafegadas (com filtro por tipo);
  * eventos (entradas, saídas, falhas, tempo limite do bot);
  * barra de status (conectados, mensagens, perguntas pendentes ao bot).

A GUI NUNCA é chamada pelas threads de rede: o núcleo publica objetos de
common/eventos.py numa queue.Queue e esta janela consome a fila a cada
100 ms com root.after() — o tkinter não é thread-safe.

Contrato (servidor/__main__.py):
    janela = JanelaServidor(root, fila_eventos, servidor.expulsar)
    servidor.iniciar()
    janela.definir_portas(servidor.portas_abertas)
"""

from __future__ import annotations

import queue
import time
import tkinter as tk
from tkinter import ttk

from common import eventos
from common.tema import CORES, FONTE_MONO, FONTE_PEQUENA, aplicar_tema, selo

INTERVALO_MS = 100
MAX_MENSAGENS = 2000          # linhas guardadas na tabela de mensagens

CORES_EVENTO = {
    "info": CORES["destaque"],
    "join": CORES["ok"],
    "leave": CORES["sutil"],
    "bot": CORES["bot"],
    "erro": CORES["erro"],
}
FILTROS = ["Todos", "MSG", "MSG (privadas)", "Bot (BOT_*)", "ERROR", "Entrada/saída"]


class JanelaServidor:
    def __init__(self, root: tk.Tk, fila_eventos: queue.Queue, ao_expulsar):
        self.root = root
        self.fila = fila_eventos
        self.ao_expulsar = ao_expulsar
        self.mensagens: list[dict] = []
        self.total_mensagens = 0
        self.ultimo_status = eventos.StatusServidor(0, 0, False)

        root.title("Servidor de Chat — SD2")
        root.geometry("1180x720")
        root.minsize(900, 560)
        root.configure(bg=CORES["fundo"])
        aplicar_tema(root)

        self._montar_cabecalho()
        self._montar_corpo()
        self._montar_rodape()
        root.after(INTERVALO_MS, self._consumir_fila)

    # ================================================================ layout
    def _montar_cabecalho(self):
        topo = ttk.Frame(self.root, padding=(14, 12, 14, 6))
        topo.pack(fill="x")
        ttk.Label(topo, text="Servidor de Chat", style="Titulo.TLabel").pack(side="left")
        ttk.Label(topo, text="   Sistemas Distribuídos II", style="Sutil.TLabel").pack(side="left")

        self.area_selos = ttk.Frame(topo)
        self.area_selos.pack(side="right")
        self.selo_portas = selo(self.area_selos, "iniciando…", CORES["sutil"])
        self.selo_portas.pack(side="left", padx=3)
        self.selo_bot = selo(self.area_selos, "Bot offline", CORES["erro"])
        self.selo_bot.pack(side="left", padx=3)

    def _montar_corpo(self):
        divisor = ttk.PanedWindow(self.root, orient="horizontal")
        divisor.pack(fill="both", expand=True, padx=14, pady=6)

        # ---------- participantes
        esq = ttk.Frame(divisor, style="Painel.TFrame", padding=10)
        ttk.Label(esq, text="PARTICIPANTES", style="Secao.TLabel").pack(anchor="w")
        colunas = ("papel", "endereco", "canal", "desde")
        self.tabela_part = ttk.Treeview(esq, columns=colunas, show="tree headings", height=12)
        self.tabela_part.heading("#0", text="Nome")
        self.tabela_part.column("#0", width=78, minwidth=60, stretch=False)
        for col, titulo, larg in [("papel", "Papel", 70), ("endereco", "Endereço", 128),
                                  ("canal", "Canal", 84), ("desde", "Desde", 76)]:
            self.tabela_part.heading(col, text=titulo)
            self.tabela_part.column(col, width=larg, minwidth=larg, anchor="w", stretch=False)
        self.tabela_part.tag_configure("bot", foreground=CORES["bot"])
        self.tabela_part.tag_configure("tls", foreground=CORES["ok"])
        self.tabela_part.pack(fill="both", expand=True, pady=(6, 8))
        ttk.Button(esq, text="Desconectar selecionado", style="Perigo.TButton",
                   command=self._desconectar_selecionado).pack(fill="x")
        ttk.Label(esq, text="Desconectar o bot simula a queda dele\n(perguntas pendentes recebem BOT_OFFLINE).",
                  style="SutilPainel.TLabel", font=FONTE_PEQUENA, justify="left").pack(anchor="w", pady=(6, 0))
        divisor.add(esq, weight=0)

        # ---------- mensagens (cima) e eventos (baixo)
        direita = ttk.PanedWindow(divisor, orient="vertical")

        msgs = ttk.Frame(direita, style="Painel.TFrame", padding=10)
        linha = ttk.Frame(msgs, style="Painel.TFrame")
        linha.pack(fill="x")
        ttk.Label(linha, text="MENSAGENS TRAFEGADAS", style="Secao.TLabel").pack(side="left")
        self.filtro = ttk.Combobox(linha, values=FILTROS, state="readonly", width=16)
        self.filtro.set("Todos")
        self.filtro.bind("<<ComboboxSelected>>", lambda _e: self._reaplicar_filtro())
        self.filtro.pack(side="right")
        ttk.Label(linha, text="Mostrar:", style="SutilPainel.TLabel").pack(side="right", padx=4)

        colunas = ("hora", "tipo", "de", "para", "ref", "conteudo")
        self.tabela_msg = ttk.Treeview(msgs, columns=colunas, show="headings", height=14)
        for col, titulo, larg in [("hora", "Hora", 76), ("tipo", "Tipo", 86), ("de", "De", 75),
                                  ("para", "Para", 75), ("ref", "Ref", 86), ("conteudo", "Conteúdo", 420)]:
            self.tabela_msg.heading(col, text=titulo)
            self.tabela_msg.column(col, width=larg, anchor="w", stretch=(col == "conteudo"))
        for tag, cor in [("bot", CORES["bot"]), ("erro", CORES["erro"]),
                         ("privada", CORES["privado"]), ("sistema", CORES["sutil"])]:
            self.tabela_msg.tag_configure(tag, foreground=cor)
        rolagem = ttk.Scrollbar(msgs, orient="vertical", command=self.tabela_msg.yview)
        self.tabela_msg.configure(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y", pady=(6, 0))
        self.tabela_msg.pack(fill="both", expand=True, pady=(6, 0))
        direita.add(msgs, weight=3)

        evts = ttk.Frame(direita, style="Painel.TFrame", padding=10)
        ttk.Label(evts, text="EVENTOS", style="Secao.TLabel").pack(anchor="w")
        self.texto_evt = tk.Text(evts, height=8, bg=CORES["painel"], fg=CORES["texto"],
                                 font=FONTE_MONO, relief="flat", wrap="word",
                                 highlightthickness=0, state="disabled")
        for nivel, cor in CORES_EVENTO.items():
            self.texto_evt.tag_configure(nivel, foreground=cor)
        self.texto_evt.tag_configure("hora", foreground=CORES["sutil"])
        self.texto_evt.pack(fill="both", expand=True, pady=(6, 0))
        direita.add(evts, weight=2)

        divisor.add(direita, weight=1)

    def _montar_rodape(self):
        rodape = ttk.Frame(self.root, padding=(14, 4, 14, 10))
        rodape.pack(fill="x")
        self.lbl_status = ttk.Label(rodape, style="Sutil.TLabel")
        self.lbl_status.pack(side="left")
        self._atualizar_status()

    # ================================================================ API usada pelo __main__
    def definir_portas(self, portas: dict[str, int]) -> None:
        """Mostra as portas abertas (ex.: {'TCP :5000': 5000, 'TLS :5001': 5001})."""
        tem_tls = any(c.startswith("TLS") for c in portas)
        texto = "  ".join(portas) + ("" if tem_tls else "   (TLS desativado)")
        self.selo_portas.configure(text=f"● {texto}", fg=CORES["ok"] if tem_tls else CORES["aviso"])

    # ================================================================ ações
    def _desconectar_selecionado(self):
        for nome in self.tabela_part.selection():
            self.ao_expulsar(nome)

    # ================================================================ fila (thread-safe)
    def _consumir_fila(self):
        try:
            for _ in range(500):                    # limita o trabalho por ciclo
                self._tratar(self.fila.get_nowait())
        except queue.Empty:
            pass
        self.root.after(INTERVALO_MS, self._consumir_fila)

    def _tratar(self, item):
        if isinstance(item, eventos.ParticipanteEntrou):
            tags = ("bot",) if item.papel == "bot" else (("tls",) if item.canal.startswith("TLS") else ())
            if self.tabela_part.exists(item.nome):
                self.tabela_part.delete(item.nome)
            self.tabela_part.insert("", "end", iid=item.nome, text=item.nome, tags=tags, values=(
                "bot" if item.papel == "bot" else "humano", item.endereco, item.canal,
                time.strftime("%H:%M:%S", time.localtime(item.desde))))
        elif isinstance(item, eventos.ParticipanteSaiu):
            if self.tabela_part.exists(item.nome):
                self.tabela_part.delete(item.nome)
        elif isinstance(item, eventos.MensagemTrafegada):
            self.total_mensagens += 1
            self.mensagens.append(item.envelope)
            if len(self.mensagens) > MAX_MENSAGENS:
                del self.mensagens[0]
                filhos = self.tabela_msg.get_children()
                if filhos:
                    self.tabela_msg.delete(filhos[0])
            self._inserir_mensagem(item.envelope)
            self._atualizar_status()
        elif isinstance(item, eventos.EventoServidor):
            self._registrar_evento(item)
        elif isinstance(item, eventos.StatusServidor):
            self.ultimo_status = item
            self._atualizar_status()

    # ================================================================ desenho
    def _passa_no_filtro(self, env: dict) -> bool:
        filtro, tipo = self.filtro.get(), env["type"]
        if filtro == "Todos":
            return True
        if filtro == "MSG":
            return tipo == "MSG"
        if filtro == "MSG (privadas)":
            return tipo == "MSG" and env["to"] not in ("*", "bot")
        if filtro == "Bot (BOT_*)":
            return tipo.startswith("BOT_") or (tipo == "MSG" and env["content"].lstrip().lower().startswith("@bot"))
        if filtro == "ERROR":
            return tipo in ("ERROR", "BOT_ERR")
        if filtro == "Entrada/saída":
            return tipo in ("HELLO", "BYE")
        return True

    def _inserir_mensagem(self, env: dict):
        if not self._passa_no_filtro(env):
            return
        tipo = env["type"]
        if tipo in ("BOT_ERR", "ERROR"):
            tag = "erro"
        elif tipo.startswith("BOT_") or (tipo == "MSG" and env["content"].lstrip().lower().startswith("@bot")):
            tag = "bot"
        elif tipo == "MSG" and env["to"] != "*":
            tag = "privada"
        elif tipo != "MSG":
            tag = "sistema"
        else:
            tag = ""
        conteudo = env.get("content", "")
        if not isinstance(conteudo, str):
            conteudo = ", ".join(map(str, conteudo))
        if env.get("code"):
            conteudo = f"[{env['code']}] {conteudo}"
        conteudo = conteudo.replace("\n", " ⏎ ")
        self.tabela_msg.insert("", "end", tags=(tag,), values=(
            time.strftime("%H:%M:%S", time.localtime(env.get("ts", time.time()))),
            tipo, env.get("from", ""), "todos" if env.get("to") == "*" else env.get("to", ""),
            (env.get("ref") or "")[:8], conteudo))
        self.tabela_msg.yview_moveto(1)

    def _reaplicar_filtro(self):
        self.tabela_msg.delete(*self.tabela_msg.get_children())
        for env in self.mensagens:
            self._inserir_mensagem(env)

    def _registrar_evento(self, evento: eventos.EventoServidor):
        self.texto_evt.configure(state="normal")
        self.texto_evt.insert("end", time.strftime("%H:%M:%S  ", time.localtime(evento.quando)), "hora")
        self.texto_evt.insert("end", f"[{evento.nivel.upper():5}] {evento.texto}\n", evento.nivel)
        self.texto_evt.see("end")
        self.texto_evt.configure(state="disabled")

    def _atualizar_status(self):
        st = self.ultimo_status
        self.lbl_status.configure(
            text=f"Conectados: {st.conectados}   •   Mensagens: {self.total_mensagens}   •   "
                 f"Perguntas pendentes ao bot: {st.pendentes_bot}")
        if st.bot_online:
            self.selo_bot.configure(text="● Bot online", fg=CORES["bot"])
        else:
            self.selo_bot.configure(text="● Bot offline", fg=CORES["erro"])
