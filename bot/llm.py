"""Consulta à LLM (Groq, API no formato OpenAI) por HTTPS.

Responsável: Bruna — issues #3 e #15.
Baseado em exemplos/exemplo_groq.py (branch `teste`), validado com a chave
real em 25/11 usando o modelo openai/gpt-oss-120b.

Contrato com a rede do bot (Pedro):
    texto = consultar_llm(historico, pergunta)    # historico: [{"role": ..., "content": ...}]
    # em falha lança ErroLLM(code, mensagem), com code em (PROTOCOLO.md §6.2):
    #   LLM_TIMEOUT      a LLM não respondeu no prazo (config.LLM_TIMEOUT)
    #   LLM_RATE_LIMIT   limite de requisições do plano gratuito (HTTP 429)
    #   LLM_AUTH         chave ausente ou inválida (HTTP 401/403)
    #   LLM_UNAVAILABLE  sem rede, modelo inexistente, erro da API, resposta vazia

Teste rápido (precisa do .env com LLM_API_KEY):
    python -m bot.llm "minha internet cai toda noite"
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from common import config


class ErroLLM(Exception):
    def __init__(self, code: str, mensagem: str, detalhe: str = ""):
        super().__init__(mensagem)
        self.code = code
        self.detalhe = detalhe          # mensagem técnica da API (vai para o log do bot, não para o usuário)


# ------------------------------------------------------------------ instrução (issue #3)
# Baseada no prompt da Bruna (bot/prompts/original/), condensada para caber no
# limite do plano gratuito do Groq (8 mil tokens por MINUTO no gpt-oss-120b): o
# original tem ~9 mil tokens e estouraria o limite em uma única pergunta.
PASTA_PROMPTS = Path(__file__).resolve().parent / "prompts"
# Espaço reservado para a resposta. O Groq também conta essa reserva no limite por minuto,
# então não convém exagerar: 700 cabem 5 frases + o raciocínio "low" do gpt-oss.
_MAX_TOKENS = config.LLM_MAX_TOKENS
ESPERA_MAXIMA_429 = 8.0     # s: se o Groq pedir para esperar até isso, o bot espera e tenta de novo

# A base de luzes só é enviada quando a conversa fala de equipamento/luzes/sem internet.
_ASSUNTO_LUZES = re.compile(
    r"\b(luz|luzes|led|leds|los|pon|power|onu|roteador|modem|aparelho|piscando|vermelh\w*|"
    r"apagad\w*|acesa|acesas|fibra|sem internet|sem conex\w*|caiu|wps|lan)\b", re.IGNORECASE)

_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


@lru_cache(maxsize=None)
def _ler(nome: str) -> str:
    return (PASTA_PROMPTS / nome).read_text(encoding="utf-8").strip()


def agora_texto(momento: datetime | None = None) -> str:
    m = momento or datetime.now()
    return f"Agora é {_DIAS[m.weekday()]}, {m:%d/%m/%Y}, {m:%H:%M}."


def precisa_base_luzes(historico: list[dict], pergunta: str) -> bool:
    """Pergunta atual + últimas falas do cliente mencionam luzes/equipamento?"""
    falas = [pergunta] + [m["content"] for m in historico[-4:] if m.get("role") == "user"]
    return any(_ASSUNTO_LUZES.search(f) for f in falas)


def instrucao_sistema(historico: list[dict] | None = None, pergunta: str = "",
                      momento: datetime | None = None) -> str:
    texto = _ler("instrucao.md").format(provedor=config.BOT_PROVEDOR, agora=agora_texto(momento))
    if precisa_base_luzes(historico or [], pergunta):
        texto += "\n\n" + _ler("base_luzes.md")
    return texto


def estimar_tokens(texto: str) -> int:
    """Estimativa simples para português (~3,5 caracteres por token)."""
    return int(len(texto) / 3.5) + 1


def consultar_llm(historico: list[dict], pergunta: str, timeout: float | None = None) -> str:
    """Envia instrução + histórico + pergunta e devolve o texto da resposta."""
    if not config.LLM_API_KEY:
        raise ErroLLM("LLM_AUTH", "Bot sem chave da LLM configurada (LLM_API_KEY no .env).")
    timeout = config.LLM_TIMEOUT if timeout is None else timeout

    corpo = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "system", "content": instrucao_sistema(historico, pergunta)}]
                    + list(historico)
                    + [{"role": "user", "content": pergunta}],
        "temperature": 0.4,
        "max_tokens": _MAX_TOKENS,
    }
    if "gpt-oss" in config.LLM_MODEL:
        corpo["reasoning_effort"] = "low"       # mais rápido e gasta menos cota

    req = urllib.request.Request(
        config.LLM_URL,
        data=json.dumps(corpo).encode("utf-8"),
        headers={"Authorization": f"Bearer {config.LLM_API_KEY}",
                 "Content-Type": "application/json",
                 "User-Agent": "chat-sd2/1.0"},
        method="POST",
    )
    try:
        dados = _enviar(req, timeout)
    except urllib.error.HTTPError as e:
        detalhe = getattr(e, "detalhe_api", None) or _detalhe_do_erro(e)
        if e.code in (401, 403):
            raise ErroLLM("LLM_AUTH", "A chave da LLM é inválida.") from e
        if e.code == 413:
            raise ErroLLM("LLM_RATE_LIMIT", "A pergunta ficou grande demais para o limite da LLM.",
                          detalhe) from e
        if e.code == 429:
            raise ErroLLM("LLM_RATE_LIMIT",
                          "Limite de uso da LLM atingido. Tente novamente em alguns segundos.", detalhe) from e
        if e.code == 404:
            raise ErroLLM("LLM_UNAVAILABLE",
                          f"Modelo '{config.LLM_MODEL}' não encontrado na LLM ({detalhe}).") from e
        raise ErroLLM("LLM_UNAVAILABLE", f"A LLM respondeu com erro HTTP {e.code} ({detalhe}).") from e
    except TimeoutError as e:
        raise ErroLLM("LLM_TIMEOUT", f"A LLM não respondeu em {timeout:g} s. Tente novamente.") from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise ErroLLM("LLM_TIMEOUT", f"A LLM não respondeu em {timeout:g} s. Tente novamente.") from e
        raise ErroLLM("LLM_UNAVAILABLE", "Sem conexão com o serviço da LLM.") from e
    except (json.JSONDecodeError, OSError) as e:
        raise ErroLLM("LLM_UNAVAILABLE", "Resposta inválida do serviço da LLM.") from e

    try:
        texto = (dados["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError, AttributeError) as e:
        raise ErroLLM("LLM_UNAVAILABLE", "Resposta em formato inesperado da LLM.") from e
    texto = limpar_markdown(texto)
    if not texto:
        raise ErroLLM("LLM_UNAVAILABLE", "A LLM devolveu uma resposta vazia.")
    return texto


def _enviar(req: urllib.request.Request, timeout: float) -> dict:
    """POST à API. Em HTTP 429 com espera curta (Retry-After), espera e tenta mais uma vez."""
    for tentativa in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code != 429 or tentativa == 2:
                raise
            e.detalhe_api = _detalhe_do_erro(e)
            try:
                espera = float(e.headers.get("retry-after", ""))
            except (TypeError, ValueError):
                raise e from None
            if espera > ESPERA_MAXIMA_429:
                raise e from None
            time.sleep(max(espera, 0.5))
    raise AssertionError("não alcançado")


def limpar_markdown(texto: str) -> str:
    """Remove a formatação markdown que o modelo às vezes usa mesmo instruído
    a não usar (a interface mostra texto puro). Listas numeradas são mantidas."""
    texto = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), texto)
    texto = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", texto)          # títulos
    texto = re.sub(r"`([^`]*)`", r"\1", texto)                    # código inline
    texto = re.sub(r"(?m)^(\s*)[*•]\s+", r"\1- ", texto)          # marcadores * → -
    texto = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])", r"\1", texto)  # *negrito* simples
    return texto.strip()


def _detalhe_do_erro(e: urllib.error.HTTPError) -> str:
    try:
        return json.loads(e.read().decode("utf-8"))["error"]["message"]
    except Exception:
        return "sem detalhes"


if __name__ == "__main__":
    pergunta = " ".join(sys.argv[1:]) or "Minha internet está caindo toda noite, o que faço?"
    print(f"Modelo: {config.LLM_MODEL} | .env: {config.ARQUIVO_ENV or 'não encontrado'}\n")
    try:
        print(consultar_llm([], pergunta))
    except ErroLLM as erro:
        sys.exit(f"[{erro.code}] {erro}" + (f"\n  detalhe da API: {erro.detalhe}" if erro.detalhe else ""))
