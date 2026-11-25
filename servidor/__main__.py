"""Ponto de entrada: python -m servidor"""

import queue
import sys
import tkinter as tk

from servidor.gui import JanelaServidor
from servidor.nucleo import ServidorChat


def main() -> None:
    fila = queue.Queue()
    servidor = ServidorChat(fila)
    try:
        root = tk.Tk()
        JanelaServidor(root, fila, servidor.expulsar)
        servidor.iniciar()
    except NotImplementedError as e:
        sys.exit(f"[esqueleto] servidor ainda não implementado: {e}")
    root.protocol("WM_DELETE_WINDOW", lambda: (servidor.parar(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
