"""Ponto de entrada:

    python -m servidor            # com interface gráfica (issue #13)
    python -m servidor --sem-gui  # só terminal: mostra os eventos no console
"""

import queue
import sys
import time

from common import eventos
from servidor.nucleo import ServidorChat


def modo_terminal() -> None:
    fila = queue.Queue()
    servidor = ServidorChat(fila)
    servidor.iniciar()
    print("Servidor rodando sem interface gráfica. Ctrl+C para encerrar.\n")
    try:
        while True:
            try:
                item = fila.get(timeout=0.5)
            except queue.Empty:
                continue
            hora = time.strftime("%H:%M:%S")
            if isinstance(item, eventos.EventoServidor):
                print(f"{hora} [{item.nivel.upper():5}] {item.texto}")
            elif isinstance(item, eventos.MensagemTrafegada):
                env = item.envelope
                print(f"{hora} [MSG  ] {env['type']:8} {env['from']} -> {env['to']}: {env['content']}")
    except KeyboardInterrupt:
        servidor.parar()


def modo_gui() -> None:
    import tkinter as tk
    from servidor.gui import JanelaServidor

    fila = queue.Queue()
    servidor = ServidorChat(fila)
    try:
        root = tk.Tk()
        JanelaServidor(root, fila, servidor.expulsar)
        servidor.iniciar()
    except NotImplementedError as e:
        sys.exit(f"[esqueleto] interface do servidor ainda não implementada: {e}\n"
                 "Use: python -m servidor --sem-gui")
    root.protocol("WM_DELETE_WINDOW", lambda: (servidor.parar(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    modo_terminal() if "--sem-gui" in sys.argv else modo_gui()
