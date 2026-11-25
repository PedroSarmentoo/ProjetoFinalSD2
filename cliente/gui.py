"""Interface gráfica do cliente humano.

Responsável: Bruna — issue #14.
Partir do protótipo da branch `teste` (interface/cliente_gui.py).
Tela de conexão (nome, host, porta, TLS sim/não) → chat com sala,
privado e @bot. Consome a fila da ClienteRede com root.after(...).
Digitar nunca pode travar quando chega mensagem.
"""

from __future__ import annotations

import queue
import tkinter as tk


class JanelaCliente:
    def __init__(self, root: tk.Tk, rede, fila: queue.Queue):
        raise NotImplementedError("issue #14 (Bruna)")
