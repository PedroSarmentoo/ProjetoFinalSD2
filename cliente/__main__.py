"""Ponto de entrada: python -m cliente   (abra um terminal para cada usuário)"""

import queue
import sys
import tkinter as tk

from cliente.gui import JanelaCliente
from cliente.rede import ClienteRede


def main() -> None:
    fila = queue.Queue()
    rede = ClienteRede(fila)
    try:
        root = tk.Tk()
        JanelaCliente(root, rede, fila)
    except NotImplementedError as e:
        sys.exit(f"[esqueleto] cliente ainda não implementado: {e}")
    root.mainloop()


if __name__ == "__main__":
    main()
