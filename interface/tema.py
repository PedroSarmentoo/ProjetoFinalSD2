"""Paleta e estilos ttk compartilhados pelas janelas do servidor e do cliente."""

import tkinter as tk
from tkinter import ttk

CORES = {
    "fundo": "#0f1419",
    "painel": "#161b22",
    "painel2": "#1c2330",
    "borda": "#30363d",
    "texto": "#e6edf3",
    "sutil": "#8b949e",
    "destaque": "#58a6ff",
    "ok": "#3fb950",
    "aviso": "#d29922",
    "erro": "#f85149",
    "bot": "#bc8cff",
    "privado": "#f0883e",
}

FONTE = ("DejaVu Sans", 10)
FONTE_NEGRITO = ("DejaVu Sans", 10, "bold")
FONTE_TITULO = ("DejaVu Sans", 13, "bold")
FONTE_MONO = ("DejaVu Sans Mono", 9)


def aplicar_tema(root: tk.Misc) -> ttk.Style:
    c = CORES
    estilo = ttk.Style(root)
    estilo.theme_use("clam")

    estilo.configure(".", background=c["fundo"], foreground=c["texto"],
                     fieldbackground=c["painel"], bordercolor=c["borda"], font=FONTE)
    estilo.configure("TFrame", background=c["fundo"])
    estilo.configure("Painel.TFrame", background=c["painel"])
    estilo.configure("TLabel", background=c["fundo"], foreground=c["texto"])
    estilo.configure("Painel.TLabel", background=c["painel"])
    estilo.configure("Titulo.TLabel", font=FONTE_TITULO)
    estilo.configure("Sutil.TLabel", foreground=c["sutil"])
    estilo.configure("SutilPainel.TLabel", background=c["painel"], foreground=c["sutil"])
    estilo.configure("Secao.TLabel", background=c["painel"], foreground=c["sutil"],
                     font=("DejaVu Sans", 9, "bold"))

    estilo.configure("TButton", background=c["painel2"], foreground=c["texto"],
                     bordercolor=c["borda"], focusthickness=0, padding=(10, 5))
    estilo.map("TButton", background=[("active", c["borda"])])
    estilo.configure("Primario.TButton", background="#1f6feb", foreground="white")
    estilo.map("Primario.TButton", background=[("active", "#388bfd")])
    estilo.configure("Perigo.TButton", foreground=c["erro"])

    estilo.configure("Treeview", background=c["painel"], fieldbackground=c["painel"],
                     foreground=c["texto"], rowheight=24, bordercolor=c["borda"])
    estilo.configure("Treeview.Heading", background=c["painel2"], foreground=c["sutil"],
                     font=("DejaVu Sans", 9, "bold"), relief="flat")
    estilo.map("Treeview", background=[("selected", "#1f3a5f")])

    estilo.configure("TEntry", fieldbackground=c["painel2"], foreground=c["texto"],
                     insertcolor=c["texto"], padding=6)
    estilo.configure("TCombobox", fieldbackground=c["painel2"], foreground=c["texto"],
                     background=c["painel2"], arrowcolor=c["texto"])
    estilo.configure("TCheckbutton", background=c["fundo"], foreground=c["texto"])
    estilo.configure("TPanedwindow", background=c["borda"])
    estilo.map("TCombobox", fieldbackground=[("readonly", c["painel2"])],
               foreground=[("readonly", c["texto"])],
               selectbackground=[("readonly", c["painel2"])],
               selectforeground=[("readonly", c["texto"])])
    root.option_add("*TCombobox*Listbox.background", c["painel2"])
    root.option_add("*TCombobox*Listbox.foreground", c["texto"])
    return estilo


def selo(master, texto: str, cor: str) -> tk.Label:
    """Pequeno indicador colorido (ex.: '● TLS :5001')."""
    return tk.Label(master, text=f"● {texto}", fg=cor, bg=CORES["painel2"],
                    font=("DejaVu Sans", 9, "bold"), padx=8, pady=3)
