"""Abre o servidor e três clientes (Ana, Bruno, Carla) para visualizar as interfaces.

Uso:
    python executar_demo.py            # você interage à vontade
    python executar_demo.py --roteiro  # roda uma conversa automática de exemplo
"""

import queue
import sys
import tkinter as tk

from interface.cliente_gui import JanelaCliente
from interface.servidor_gui import JanelaServidor
from interface.tema import aplicar_tema
from simulacao.hub_simulado import HubSimulado, novo_envelope

CLIENTES = [  # nome, usa TLS?, posição na tela
    ("Ana", True, "+1040+20"),
    ("Bruno", False, "+1040+420"),
    ("Carla", False, "+1480+220"),
]


def main():
    root = tk.Tk()
    root.geometry("1010x680+20+20")
    aplicar_tema(root)

    fila_servidor = queue.Queue()
    hub = HubSimulado(fila_servidor)
    JanelaServidor(root, fila_servidor, hub.alternar_bot, hub.desconectar)

    clientes = {}
    for nome, tls, pos in CLIENTES:
        top = tk.Toplevel(root)
        top.geometry(f"430x380{pos}")
        clientes[nome] = JanelaCliente(top, nome, tls, hub, novo_envelope)

    if "--roteiro" in sys.argv:
        roteiro(root, clientes)
    root.mainloop()


def roteiro(root, c):
    """Conversa de exemplo: mostra público, privado, bot e concorrência."""
    def digitar(nome, texto, destino="*"):
        cli = c[nome]
        cli.destino = destino
        cli.entrada.delete(0, "end")
        cli.entrada.insert(0, texto)
        cli._enviar()

    passos = [
        (800, lambda: digitar("Ana", "Bom dia, pessoal!")),
        (1600, lambda: digitar("Bruno", "Bom dia, Ana!")),
        (2400, lambda: digitar("Ana", "@bot explique a diferença entre TCP e UDP")),
        (3000, lambda: digitar("Carla", "Enquanto o bot pensa, a gente segue conversando :)")),
        (3600, lambda: digitar("Bruno", "Carla, você terminou o protocolo?", "Carla")),
        (4300, lambda: digitar("Carla", "@bot o que é um socket?")),
        (5000, lambda: digitar("Carla", "Quase! Falta o framing por \\n", "Bruno")),
        (8500, lambda: digitar("Ana", "@bot e qual dos dois é melhor para chat?")),
    ]
    for atraso, acao in passos:
        root.after(atraso, acao)


if __name__ == "__main__":
    main()
