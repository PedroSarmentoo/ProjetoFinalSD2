"""Abre o sistema inteiro com um comando — cada componente em um PROCESSO SEPARADO.

    python iniciar.py                     # servidor (GUI) + bot + ana, bruno e carla
    python iniciar.py ana bruno           # escolhe os clientes
    python iniciar.py --tls               # clientes entram pela porta TLS (5001)
    python iniciar.py --sem-bot           # sem o bot
    python iniciar.py --sem-gui-servidor  # servidor só no terminal

Equivale a abrir um terminal para cada um destes comandos:
    python -m servidor
    python -m bot
    python -m cliente ana --conectar      (um por usuário)

Ctrl+C neste terminal (ou fechar a janela do servidor) encerra tudo.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from common import config

RAIZ = Path(__file__).resolve().parent


def porta_aberta(porta: int) -> bool:
    try:
        with socket.create_connection((config.HOST, porta), timeout=0.3):
            return True
    except OSError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Inicia servidor, bot e clientes do chat SD2")
    parser.add_argument("clientes", nargs="*", default=["ana", "bruno", "carla"])
    parser.add_argument("--tls", action="store_true", help="clientes usam a porta TLS")
    parser.add_argument("--sem-bot", action="store_true")
    parser.add_argument("--sem-gui-servidor", action="store_true")
    opcoes = parser.parse_args()

    processos: list[tuple[str, subprocess.Popen]] = []

    def abrir(rotulo: str, *argumentos: str, console_proprio: bool = False) -> subprocess.Popen:
        flags = subprocess.CREATE_NEW_CONSOLE if console_proprio and os.name == "nt" else 0
        proc = subprocess.Popen([sys.executable, *argumentos], cwd=RAIZ, creationflags=flags)
        processos.append((rotulo, proc))
        print(f"  ▸ {rotulo:<10} PID {proc.pid}")
        return proc

    if porta_aberta(config.PORTA):
        sys.exit(f"Já existe algo usando a porta {config.PORTA}. Feche o servidor antigo e tente de novo.")

    print("Iniciando (cada componente é um processo separado):")
    servidor = abrir("servidor", "-m", "servidor", *(["--sem-gui"] if opcoes.sem_gui_servidor else []),
                     console_proprio=opcoes.sem_gui_servidor)
    limite = time.time() + 8
    while not porta_aberta(config.PORTA):
        if servidor.poll() is not None or time.time() > limite:
            sys.exit("O servidor não subiu. Rode 'python -m servidor' sozinho para ver o erro.")
        time.sleep(0.2)

    if not opcoes.sem_bot:
        abrir("bot", "-m", "bot", console_proprio=True)
        time.sleep(0.8)                         # o bot entra antes dos humanos

    n = len(opcoes.clientes)
    for i, nome in enumerate(opcoes.clientes):
        abrir(f"cliente {nome}", "-m", "cliente", nome, "--conectar", "--posicao", f"{i}/{n}",
              *(["--tls"] if opcoes.tls else []))

    print("\nTudo aberto. Feche a janela do servidor ou aperte Ctrl+C aqui para encerrar.")
    try:
        while servidor.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for rotulo, proc in reversed(processos):
            if proc.poll() is None:
                proc.terminate()
        print("Encerrado.")


if __name__ == "__main__":
    main()
