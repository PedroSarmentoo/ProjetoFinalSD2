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
  /modelos          lista os modelos disponíveis para a sua chave
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
MODELO_PADRAO = "openai/gpt-oss-120b"
TROCAS_GUARDADAS = 3  # 3 perguntas + 3 respostas por usuário
PROMPT_SISTEMA = ("Você é o bot de um chat acadêmico. Responda em português, "
                  "de forma curta e direta (no máximo 5 frases).")


class ErroLLM(Exception):
    """Falha ao consultar a LLM. A mensagem já é amigável para o usuário."""


# ---------------------------------------------------------------- .env
def carregar_env():
    """Lê KEY=VALOR do .env sem precisar instalar python-dotenv.

    Procura ao lado deste script, na pasta de onde foi executado e na pasta
    acima. Devolve o caminho usado (ou None, se não achou nenhum).
    """
    pasta_script = Path(__file__).resolve().parent
    candidatos = [pasta_script / ".env", Path.cwd() / ".env", pasta_script.parent / ".env"]
    for caminho in candidatos:
        if caminho.is_file():
            break
    else:
        return None
    # utf-8-sig: ignora o BOM que alguns editores do Windows colocam no início
    for linha in caminho.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))
    return caminho


# ---------------------------------------------------------------- chamada à LLM
def consultar_llm(historico, pergunta, timeout=15):
    """Envia o histórico + pergunta ao Groq e devolve o texto da resposta.

    historico: lista de {"role": "user"|"assistant", "content": str}
    Lança ErroLLM em qualquer falha (sem chave, timeout, cota, rede...).
    """
    chave = os.getenv("LLM_API_KEY")
    if not chave:
        raise ErroLLM("Bot sem chave de API configurada (LLM_API_KEY).")

    modelo = os.getenv("LLM_MODEL", MODELO_PADRAO)
    corpo = {
        "model": modelo,
        "messages": [{"role": "system", "content": PROMPT_SISTEMA}]
                    + historico
                    + [{"role": "user", "content": pergunta}],
        "temperature": 0.5,
        # Modelos de raciocínio (gpt-oss) gastam parte deste limite "pensando".
        "max_tokens": 1024,
    }
    if "gpt-oss" in modelo:
        corpo["reasoning_effort"] = "low"   # responde mais rápido e gasta menos cota
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
        texto = (dados["choices"][0]["message"].get("content") or "").strip()
        if not texto:
            raise ErroLLM("A LLM devolveu uma resposta vazia (limite de tokens atingido?).")
        return texto
    except urllib.error.HTTPError as e:
        detalhe = _mensagem_de_erro(e)
        if e.code == 401:
            raise ErroLLM("Chave de API inválida.") from e
        if e.code == 429:
            raise ErroLLM("Limite de requisições da LLM atingido. Tente em alguns segundos.") from e
        if e.code == 404:
            raise ErroLLM(f"Modelo '{corpo['model']}' ou endereço não encontrado ({detalhe}). "
                          "Use /modelos para ver os modelos disponíveis e ajuste LLM_MODEL no .env.") from e
        raise ErroLLM(f"A LLM respondeu com erro HTTP {e.code}: {detalhe}") from e
    except TimeoutError as e:
        raise ErroLLM(f"A LLM não respondeu em {timeout} s.") from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise ErroLLM(f"A LLM não respondeu em {timeout} s.") from e
        raise ErroLLM("Sem conexão com o serviço da LLM.") from e
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise ErroLLM("Resposta inesperada da LLM.") from e


def _mensagem_de_erro(e):
    """Extrai a mensagem que a API devolve no corpo do erro (formato OpenAI)."""
    try:
        return json.loads(e.read().decode("utf-8"))["error"]["message"]
    except Exception:
        return "sem detalhes"


def listar_modelos(timeout=15):
    """Lista os IDs de modelo que a chave pode usar (GET .../models)."""
    url = os.getenv("LLM_URL", URL_PADRAO).rsplit("/chat/completions", 1)[0] + "/models"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {os.getenv('LLM_API_KEY', '')}",
        "User-Agent": "chat-sd2/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dados = json.load(resp)
    except urllib.error.HTTPError as e:
        raise ErroLLM(f"Erro HTTP {e.code} ao listar modelos: {_mensagem_de_erro(e)}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise ErroLLM("Sem conexão com o serviço da LLM.") from e
    return sorted(m["id"] for m in dados.get("data", []))


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
    env = carregar_env()
    if env:
        print(f".env carregado de: {env}")
    else:
        print("AVISO: nenhum arquivo .env encontrado (procurei em exemplos/ e na pasta atual).")
    if not os.getenv("LLM_API_KEY"):
        print("AVISO: LLM_API_KEY não definida — crie um arquivo .env com LLM_API_KEY=gsk_...")
    historicos = Historicos()
    usuario = "ana"
    print(f"Modelo: {os.getenv('LLM_MODEL', MODELO_PADRAO)}  |  usuário atual: {usuario}")
    print("Comandos: /usuario <nome>, /historico, /modelos, /sair\n")
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
        if texto == "/modelos":
            try:
                for m in listar_modelos():
                    print(f"  {m}")
            except ErroLLM as e:
                print(f"  (ERRO) {e}")
            print()
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
