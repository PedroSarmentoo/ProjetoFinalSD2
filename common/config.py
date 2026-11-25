"""Configuração única do projeto: lida do arquivo .env na raiz.

Os valores do protocolo (limites e tempos) vêm do PROTOCOLO.md, seção 9.
Não coloque chaves ou senhas neste arquivo: elas ficam só no .env, que
nunca vai para o git.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _limpar_valor(valor: str) -> str:
    """'abc  # comentário' -> 'abc';  '"a # b"' -> 'a # b' (entre aspas o # vale)."""
    valor = valor.strip()
    if valor[:1] in "\"'" and len(valor) >= 2 and valor[0] in valor[1:]:
        return valor[1:valor.index(valor[0], 1)]
    return re.split(r"\s+#", valor, maxsplit=1)[0].strip()


def _carregar_env() -> Path | None:
    """Lê KEY=VALOR do .env (raiz do projeto ou pasta atual) sem dependências."""
    for caminho in (RAIZ / ".env", Path.cwd() / ".env"):
        if caminho.is_file():
            for linha in caminho.read_text(encoding="utf-8-sig").splitlines():
                linha = linha.strip()
                if linha and not linha.startswith("#") and "=" in linha:
                    chave, valor = linha.split("=", 1)
                    os.environ.setdefault(chave.strip(), _limpar_valor(valor))
            return caminho
    return None


ARQUIVO_ENV = _carregar_env()


def _int(nome: str, padrao: int) -> int:
    return int(os.getenv(nome, padrao))


def _float(nome: str, padrao: float) -> float:
    return float(os.getenv(nome, padrao))


# ------------------------------------------------------------------ rede
HOST = os.getenv("CHAT_HOST", "127.0.0.1")
PORTA = _int("CHAT_PORTA", 5000)          # sem criptografia (referência do Wireshark)
PORTA_TLS = _int("CHAT_PORTA_TLS", 5001)  # mesmo protocolo dentro de TLS

# ------------------------------------------------------------------ protocolo (PROTOCOLO.md §9)
VERSAO_PROTOCOLO = 1
TAMANHO_MAXIMO = 64 * 1024                # bytes por mensagem, contando o \n
TIMEOUT_HELLO = 10.0                      # s para o cliente enviar HELLO
TIMEOUT_BOT_SERVIDOR = 30.0               # s que o servidor espera o bot
MAX_PENDENTES_POR_USUARIO = 3

# ------------------------------------------------------------------ TLS (Fellipe)
PASTA_CERTS = RAIZ / "certs"
CERT_CA = Path(os.getenv("TLS_CA", PASTA_CERTS / "ca.crt"))
CERT_SERVIDOR = Path(os.getenv("TLS_CERT", PASTA_CERTS / "servidor.crt"))
CHAVE_SERVIDOR = Path(os.getenv("TLS_KEY", PASTA_CERTS / "servidor.key"))

# ------------------------------------------------------------------ LLM (Bruna)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_URL = os.getenv("LLM_URL", "https://api.groq.com/openai/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_TIMEOUT = _float("LLM_TIMEOUT", 15.0)
HISTORICO_TROCAS = _int("HISTORICO_TROCAS", 3)
BOT_PROVEDOR = os.getenv("BOT_PROVEDOR", "NetExemplo")  # nome FICTÍCIO do provedor
