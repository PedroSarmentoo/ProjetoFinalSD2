"""Consulta à LLM (Groq, formato OpenAI) por HTTPS.

Responsável: Bruna — issues #3 e #15.
Ponto de partida: exemplos/exemplo_groq.py na branch `teste` (já testado
com a chave real em 25/11, modelo openai/gpt-oss-120b).

Contrato com a rede do bot (Pedro):
    texto = consultar_llm(historico, pergunta)   # historico: [{"role": ..., "content": ...}]
    # em falha lança ErroLLM(code, mensagem) com code em:
    # LLM_TIMEOUT | LLM_RATE_LIMIT | LLM_AUTH | LLM_UNAVAILABLE  (PROTOCOLO.md §6.2)
"""

from __future__ import annotations

from common import config


class ErroLLM(Exception):
    def __init__(self, code: str, mensagem: str):
        super().__init__(mensagem)
        self.code = code


INSTRUCAO_SISTEMA = ""  # issue #3: prompt de atendimento técnico (provedor fictício config.BOT_PROVEDOR)


def consultar_llm(historico: list[dict], pergunta: str,
                  timeout: float = config.LLM_TIMEOUT) -> str:
    raise NotImplementedError("issue #15 (Bruna)")
