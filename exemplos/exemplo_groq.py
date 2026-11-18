"""Exemplo de uso do Groq para o bot do chat (só biblioteca padrão).

Mostra as três coisas que o edital pede do bot:
  1. chamada HTTP/HTTPS a uma LLM real, com timeout;
  2. histórico curto e ISOLADO por usuário (perguntas de continuação);
  3. tratamento de falhas sem derrubar o programa.

Configuração:
  1. Crie a chave em https://console.groq.com/keys
  2. Crie um arquivo .env ao lado deste script (NÃO faça commit dele):
        LLM_API_KEY=gsk_sua_chave_aqui
  3. python exemplo_groq.py

Comandos no terminal:
  /usuario <nome>   troca o usuário (cada um tem o próprio histórico)
  /historico        mostra o histórico do usuário atual
  /sair             encerra
"""

import json
import os
import threading
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

URL_PADRAO = "https://api.groq.com/openai/v1/chat/completions"
MODELO_PADRAO = "llama-3.3-70b-versatile"
TROCAS_GUARDADAS = 3  # 3 perguntas + 3 respostas por usuário
PROMPT_SISTEMA = ("Você é o bot de um chat acadêmico. Responda em português, "
                  "de forma curta e direta (no máximo 5 frases).")


class ErroLLM(Exception):
    """Falha ao consultar a LLM. A mensagem já é amigável para o usuário."""


# ---------------------------------------------------------------- .env
def carregar_env(caminho=Path(__file__).with_name(".env")):
    """Lê KEY=VALOR do .env sem precisar instalar python-dotenv."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"'))


# ---------------------------------------------------------------- chamada à LLM
def consultar_llm(historico, pergunta, timeout=15):
    """Envia o histórico + pergunta ao Groq e devolve o texto da resposta.

    historico: lista de {"role": "user"|"assistant", "content": str}
    Lança ErroLLM em qualquer falha (sem chave, timeout, cota, rede...).
    """
    chave = os.getenv("LLM_API_KEY")
    if not chave:
        raise ErroLLM("Bot sem chave de API configurada (LLM_API_KEY).")

    corpo = {
        "model": os.getenv("LLM_MODEL", MODELO_PADRAO),
        "messages": [{"role": "system", "content": PROMPT_SISTEMA}]
                    + historico
                    + [{"role": "user", "content": pergunta}],
        "temperature": 0.5,
        "max_tokens": 400,
    }
    req = urllib.request.Request(
        os.getenv("LLM_URL", URL_PADRAO),
        data=json.dumps(corpo).encode("utf-8"),
        headers={"Authorization": f"Bearer {chave}",
                 "Content-Type": "application/json",
                 "User-Agent": "chat-sd2/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dados = json.load(resp)
        return dados["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise ErroLLM("Chave de API inválida.") from e
        if e.code == 429:
            raise ErroLLM("Limite de requisições da LLM atingido. Tente em alguns segundos.") from e
        raise ErroLLM(f"A LLM respondeu com erro HTTP {e.code}.") from e
    except TimeoutError as e:
        raise ErroLLM(f"A LLM não respondeu em {timeout} s.") from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise ErroLLM(f"A LLM não respondeu em {timeout} s.") from e
        raise ErroLLM("Sem conexão com o serviço da LLM.") from e
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise ErroLLM("Resposta inesperada da LLM.") from e


# ---------------------------------------------------------------- histórico por usuário
class Historicos:
    """Um deque por usuário; o lock permite uso por várias threads do bot."""

    def __init__(self, trocas=TROCAS_GUARDADAS):
        self._lock = threading.Lock()
        self._por_usuario = {}
        self._max = trocas * 2  # cada troca = pergunta + resposta

    def obter(self, usuario):
        with self._lock:
            return list(self._por_usuario.get(usuario, ()))

    def registrar(self, usuario, pergunta, resposta):
        with self._lock:
            h = self._por_usuario.setdefault(usuario, deque(maxlen=self._max))
            h.append({"role": "user", "content": pergunta})
            h.append({"role": "assistant", "content": resposta})


def perguntar(historicos, usuario, pergunta):
    """O que o bot real faz ao receber um BOT_REQ do servidor."""
    try:
        resposta = consultar_llm(historicos.obter(usuario), pergunta)
    except ErroLLM as e:
        return False, str(e)           # vira BOT_ERR; histórico não muda
    historicos.registrar(usuario, pergunta, resposta)
    return True, resposta              # vira BOT_RESP


# ---------------------------------------------------------------- teste interativo
def main():
    carregar_env()
    historicos = Historicos()
    usuario = "ana"
    print(f"Modelo: {os.getenv('LLM_MODEL', MODELO_PADRAO)}  |  usuário atual: {usuario}")
    print("Comandos: /usuario <nome>, /historico, /sair\n")
    while True:
        try:
            texto = input(f"[{usuario}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not texto:
            continue
        if texto == "/sair":
            break
        if texto.startswith("/usuario "):
            usuario = texto.split(maxsplit=1)[1]
            print(f"  (agora você é '{usuario}')\n")
            continue
        if texto == "/historico":
            for m in historicos.obter(usuario):
                print(f"  {m['role']:>9}: {m['content'][:80]}")
            print()
            continue
        ok, resposta = perguntar(historicos, usuario, texto)
        print(f"  bot {'' if ok else '(ERRO) '}→ {resposta}\n")


if __name__ == "__main__":
    main()
