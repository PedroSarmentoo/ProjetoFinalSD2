"""Ponto de entrada (cada cliente é um processo separado):

    python -m cliente                      # abre a tela de conexão
    python -m cliente ana                  # já preenche o nome
    python -m cliente ana --conectar       # preenche e conecta sozinho
    python -m cliente ana --conectar --tls # idem, pela porta TLS (5001)

Opção usada pelo iniciar.py para lado a lado:  --posicao 0/3  (janela 1 de 3)
"""

import argparse
import queue
import tkinter as tk

from cliente.gui import JanelaCliente
from cliente.rede import ClienteRede


def main() -> None:
    args = argparse.ArgumentParser(description="Cliente do chat SD2")
    args.add_argument("nome", nargs="?", default="")
    args.add_argument("--conectar", action="store_true", help="conecta sem esperar o clique")
    args.add_argument("--tls", action="store_true", help="usa a porta TLS (5001)")
    args.add_argument("--posicao", default=None, help="i/n: posiciona a janela i de n lado a lado")
    opcoes = args.parse_args()

    fila = queue.Queue()
    rede = ClienteRede(fila)
    root = tk.Tk()
    janela = JanelaCliente(root, rede, fila, nome_inicial=opcoes.nome)

    if opcoes.posicao:
        i, n = (int(x) for x in opcoes.posicao.split("/"))
        largura_tela, altura_tela = root.winfo_screenwidth(), root.winfo_screenheight()
        largura = min(640, largura_tela // n)
        root.geometry(f"{largura}x520+{i * largura}+{max(0, altura_tela - 600)}")
    if opcoes.tls:
        janela.var_tls.set(True)
        janela._alternar_tls()
    if opcoes.conectar and opcoes.nome:
        root.after(200, janela._conectar)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        rede.sair()


if __name__ == "__main__":
    main()
