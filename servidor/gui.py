"""Interface gráfica do servidor (obrigatória pelo edital).

Responsável: Bruna — issue #13.
Partir do protótipo da branch `teste` (interface/servidor_gui.py).
Painéis: participantes, mensagens trafegadas (com filtro) e eventos.
Consome a fila de eventos (common/eventos.py) com root.after(100, ...).
"""

from __future__ import annotations

import queue
import tkinter as tk


class JanelaServidor:
    def __init__(self, root: tk.Tk, fila_eventos: queue.Queue, ao_expulsar):
        raise NotImplementedError("issue #13 (Bruna)")
