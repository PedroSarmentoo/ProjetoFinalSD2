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
import urllib.error
import urllib.request

from common import config


class ErroLLM(Exception):
    def __init__(self, code: str, mensagem: str):
        super().__init__(mensagem)
        self.code = code


# Issue #3: instrução de comportamento. A Bruna pode trocar pelo prompt dela,
# mantendo as regras de "texto curto" e "sem markdown" (a GUI é texto puro).
INSTRUCAO_SISTEMA = """\
Você é o assistente virtual de suporte técnico do provedor de internet {provedor}, \
atendendo clientes residenciais por um chat.

Regras:
- Responda sempre em português do Brasil, em texto simples, SEM markdown \
(sem asteriscos, sem títulos com #, sem tabelas).
- Seja curto: no máximo 5 frases. Para procedimentos, use passos numerados (1., 2., 3.).
- Ajude com: internet lenta ou caindo, Wi-Fi (senha, alcance, canal), roteador e ONU \
(reinício, luzes, reset), teste de velocidade, DNS e cabos.
- Comece pelas soluções mais simples (reiniciar equipamentos, conferir cabos e luzes) \
e avance conforme as respostas do cliente.
- Você não tem acesso a contas, faturas, protocolos ou ao status da rede: nunca invente \
esses dados. Quando precisar deles, oriente o cliente a abrir um chamado com um técnico.
- Se a pergunta não for sobre internet ou equipamentos de rede, diga educadamente que \
só pode ajudar com suporte técnico de internet."""

_MAX_TOKENS = 1024          # modelos de raciocínio (gpt-oss) gastam parte disto "pensando"


def instrucao_sistema() -> str:
    return INSTRUCAO_SISTEMA.format(provedor=config.BOT_PROVEDOR)


def consultar_llm(historico: list[dict], pergunta: str, timeout: float | None = None) -> str:
    """Envia instrução + histórico + pergunta e devolve o texto da resposta."""
    if not config.LLM_API_KEY:
        raise ErroLLM("LLM_AUTH", "Bot sem chave da LLM configurada (LLM_API_KEY no .env).")
    timeout = config.LLM_TIMEOUT if timeout is None else timeout

    corpo = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "system", "content": instrucao_sistema()}]
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dados = json.load(resp)
    except urllib.error.HTTPError as e:
        detalhe = _detalhe_do_erro(e)
        if e.code in (401, 403):
            raise ErroLLM("LLM_AUTH", "A chave da LLM é inválida.") from e
        if e.code == 429:
            raise ErroLLM("LLM_RATE_LIMIT",
                          "Limite de uso da LLM atingido. Tente novamente em alguns segundos.") from e
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


def limpar_markdown(texto: str) -> str:
    """Remove a formatação markdown que o modelo às vezes usa mesmo instruído
    a não usar (a interface mostra texto puro). Listas numeradas são mantidas."""
    texto = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), texto)
    texto = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", texto)          # títulos
    texto = re.sub(r"`([^`]*)`", r"\1", texto)                    # código inline
    texto = re.sub(r"(?m)^(\s*)[*•]\s+", r"\1- ", texto)          # marcadores * → -
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
        sys.exit(f"[{erro.code}] {erro}")
