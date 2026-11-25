"""Ponto de entrada: python -m bot"""

import sys

from bot.rede import BotRede


def main() -> None:
    try:
        BotRede().executar()
    except NotImplementedError as e:
        sys.exit(f"[esqueleto] bot ainda não implementado: {e}")


if __name__ == "__main__":
    main()
