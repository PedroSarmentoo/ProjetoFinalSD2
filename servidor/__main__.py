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
    try:
        servidor.iniciar()
    except OSError as e:
        sys.exit(f"Não foi possível abrir a porta {servidor.porta}: {e}")
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
    root = tk.Tk()
    janela = JanelaServidor(root, fila, servidor.expulsar)
    try:
        servidor.iniciar()
    except OSError as e:
        root.destroy()
        sys.exit(f"Não foi possível abrir a porta {servidor.porta}: {e}\n"
                 "Já existe outro servidor rodando?")
    janela.definir_portas(servidor.portas_abertas)

    def fechar():
        servidor.parar()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", fechar)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        fechar()


if __name__ == "__main__":
    modo_terminal() if "--sem-gui" in sys.argv else modo_gui()
