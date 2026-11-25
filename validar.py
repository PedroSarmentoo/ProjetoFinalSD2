"""Validação completa do projeto + evidências para o relatório (issues #12, #17, #30).

    python validar.py            # tudo (precisa de internet para a LLM)
    python validar.py --rapido   # pula o cenário com a LLM real

Etapas:
  1. Ambiente: versão do Python, tkinter, .env, chave da LLM, biblioteca cryptography.
  2. Certificados: gera certs/ (e certs/falsos/) se ainda não existirem.
  3. Testes automáticos (python -m unittest).
  4. Cenário real em PROCESSOS SEPARADOS: servidor + bot (Groq de verdade) + 3 clientes
     (ana por TLS, bruno e carla por TCP), medindo que a conversa continua durante
     a consulta à LLM, continuação, contextos separados, falha da LLM e desconexões.

Saídas em evidencias/:
  validacao_<data>.txt         resumo de tudo (este é o arquivo para conferir)
  concorrencia_<data>.txt      linha do tempo do cenário (evidência da #12)
  servidor_<data>.log          log do servidor durante o cenário
"""

from __future__ import annotations

import argparse
import os
import platform
import queue
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
EVID = RAIZ / "evidencias"
CARIMBO = datetime.now().strftime("%Y%m%d_%H%M")
AMBIENTE_FILHOS = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}

linhas: list[str] = []


def log(texto: str = "") -> None:
    print(texto, flush=True)
    linhas.append(texto)


def titulo(texto: str) -> None:
    log()
    log("=" * 72)
    log(texto)
    log("=" * 72)


def ok(cond: bool, texto: str) -> bool:
    log(f"  [{'OK' if cond else 'FALHOU'}] {texto}")
    return cond


# =========================================================================== 1. ambiente
def verificar_ambiente() -> dict:
    titulo("1. AMBIENTE")
    from common import config
    r = {}
    log(f"  Python {platform.python_version()} ({sys.executable}) — {platform.platform()}")
    r["python"] = ok(sys.version_info >= (3, 10), "Python 3.10 ou superior")
    try:
        import tkinter
        r["tk"] = ok(True, f"tkinter disponível (Tk {tkinter.TkVersion})")
    except ImportError:
        r["tk"] = ok(False, "tkinter disponível")
    r["env"] = ok(config.ARQUIVO_ENV is not None, f".env encontrado: {config.ARQUIVO_ENV}")
    chave = config.LLM_API_KEY
    r["chave"] = ok(chave.startswith("gsk_") and len(chave) > 20,
                    f"LLM_API_KEY presente (gsk_…{chave[-4:] if chave else ''}) · modelo {config.LLM_MODEL}")
    try:
        import cryptography
        r["crypto"] = ok(True, f"cryptography {cryptography.__version__}")
    except ImportError:
        r["crypto"] = ok(False, "cryptography instalada  ->  rode:  pip install cryptography")
    return r


# =========================================================================== 2. certificados
def verificar_certificados() -> bool:
    titulo("2. CERTIFICADOS TLS")
    from common import config
    if not config.CERT_CA.is_file() or not (config.PASTA_CERTS / "falsos" / "servidor.crt").is_file():
        log("  Gerando certificados…")
        r = subprocess.run([sys.executable, "certs/gerar_certificados.py", "--falsos"], cwd=RAIZ,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=AMBIENTE_FILHOS)
        for l in (r.stdout + r.stderr).strip().splitlines():
            log(f"    {l}")
    existe = all(p.is_file() for p in (config.CERT_CA, config.CERT_SERVIDOR, config.CHAVE_SERVIDOR))
    ok(existe, "certs/ca.crt, servidor.crt e servidor.key")
    if existe:
        import ssl
        from common import tls
        try:
            tls.contexto_servidor()
            tls.contexto_cliente()
            ok(True, "contextos TLS carregam (servidor e cliente com validação estrita)")
        except (OSError, ssl.SSLError) as e:
            existe = ok(False, f"contextos TLS: {e}")
    return existe


# =========================================================================== 3. testes
def rodar_testes() -> bool:
    titulo("3. TESTES AUTOMÁTICOS (python -m unittest discover -s tests)")
    inicio = time.time()
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=RAIZ,
                       capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=AMBIENTE_FILHOS)
    saida = (r.stdout + r.stderr).strip().splitlines()
    resumo = [l for l in saida if l.startswith(("Ran ", "OK", "FAILED"))]
    for l in resumo:
        log(f"  {l}")
    if r.returncode != 0:
        log("  --- detalhes das falhas ---")
        for l in saida:
            if l.startswith(("FAIL:", "ERROR:", "AssertionError", "Traceback")) or "Error" in l:
                log(f"  {l}")
    return ok(r.returncode == 0, f"todos os testes passaram ({time.time() - inicio:.1f} s)")


# =========================================================================== 4. cenário
class Usuario:
    def __init__(self, nome: str, linha_do_tempo, t0: float, usar_tls: bool):
        from cliente.rede import ClienteRede
        self.nome = nome
        self.fila = queue.Queue()
        self.rede = ClienteRede(self.fila)
        self.rede.conectar(nome, usar_tls=usar_tls)
        self.lt, self.t0 = linha_do_tempo, t0
        self.marca(f"conectou por {self.rede.canal}" + (f" ({self.rede.sessao_tls})" if usar_tls else ""))

    def marca(self, texto: str) -> None:
        self.lt.append((time.time() - self.t0, self.nome, texto))

    def esperar(self, condicao, timeout: float):
        from common import eventos
        limite = time.time() + timeout
        while time.time() < limite:
            try:
                item = self.fila.get(timeout=0.1)
            except queue.Empty:
                continue
            if isinstance(item, eventos.EnvelopeRecebido) and condicao(item.envelope):
                return item.envelope
            if isinstance(item, eventos.ConexaoEncerrada) and condicao({"type": "_ENCERRADA", "motivo": item.motivo}):
                return {"type": "_ENCERRADA", "motivo": item.motivo}
        return None


def porta_livre(porta: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", porta), timeout=0.3):
            return False
    except OSError:
        return True


def esperar_porta(porta: int, timeout: float = 8) -> bool:
    limite = time.time() + timeout
    while time.time() < limite:
        if not porta_livre(porta):
            return True
        time.sleep(0.2)
    return False


def cenario_real(tls_ok: bool) -> bool:
    titulo("4. CENÁRIO REAL (processos separados + Groq de verdade)")
    from common import config
    if not porta_livre(config.PORTA):
        return ok(False, f"porta {config.PORTA} livre — feche o servidor que estiver aberto e rode de novo")

    arq_srv = EVID / f"servidor_{CARIMBO}.log"
    processos = []
    resultados = []

    def abrir(*args, saida=subprocess.DEVNULL):
        p = subprocess.Popen([sys.executable, *args], cwd=RAIZ, stdout=saida, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=AMBIENTE_FILHOS)
        processos.append(p)
        return p

    lt: list[tuple[float, str, str]] = []
    t0 = time.time()
    with open(arq_srv, "w", encoding="utf-8") as f_srv:
        try:
            abrir("-m", "servidor", "--sem-gui", saida=f_srv)
            if not esperar_porta(config.PORTA):
                return ok(False, "servidor subiu")
            bot = abrir("-m", "bot")
            time.sleep(1.0)
            lt.append((time.time() - t0, "sistema", f"servidor (PID {processos[0].pid}) e bot (PID {bot.pid}) iniciados"))

            ana = Usuario("ana", lt, t0, usar_tls=tls_ok)
            bruno = Usuario("bruno", lt, t0, usar_tls=False)
            carla = Usuario("carla", lt, t0, usar_tls=False)
            time.sleep(0.5)
            resultados.append(ok(not tls_ok or ana.rede.canal.startswith("TLS"),
                                 f"ana conectada por {ana.rede.canal}; bruno e carla por TCP"))

            # --- concorrência: conversa continua durante a consulta à LLM
            pergunta = "Minha internet cai toda noite por volta das 22h, o que pode ser?"
            id1 = ana.rede.perguntar_bot(pergunta)
            ana.marca(f"@bot {pergunta}  [#{id1[:6]}]")
            entregas = []
            for i in range(5):
                texto = f"mensagem {i + 1} enquanto o bot consulta a LLM"
                enviado = time.time()
                bruno.rede.enviar_sala(texto)
                recebido = carla.esperar(lambda e, t=texto: e["type"] == "MSG" and e["content"] == t, 5)
                if recebido:
                    entregas.append(time.time() - enviado)
                    carla.marca(f"recebeu de bruno: {texto} ({(time.time() - enviado) * 1000:.0f} ms)")
            resp1 = ana.esperar(lambda e: e["type"] in ("BOT_RESP", "BOT_ERR") and e.get("ref") == id1, 45)
            if resp1:
                ana.marca(f"{resp1['type']} #{id1[:6]}: {resp1['content'][:140]}")
            consulta = (lt[-1][0] - next(t for t, n, x in lt if x.startswith("@bot"))) if resp1 else None
            resultados.append(ok(len(entregas) == 5,
                                 f"5 mensagens bruno→carla entregues DURANTE a consulta "
                                 f"(média {sum(entregas) / max(len(entregas), 1) * 1000:.0f} ms cada)"))
            resultados.append(ok(resp1 is not None and resp1["type"] == "BOT_RESP",
                                 f"bot respondeu à ana em {consulta:.1f} s com o mesmo ref" if consulta
                                 else "bot respondeu à ana"))

            # --- continuação e contextos separados
            id2 = ana.rede.perguntar_bot("Já reiniciei o roteador e continua caindo. Qual o próximo passo?")
            ana.marca(f"@bot (continuação) Já reiniciei o roteador e continua caindo…  [#{id2[:6]}]")
            resp2 = ana.esperar(lambda e: e["type"] in ("BOT_RESP", "BOT_ERR") and e.get("ref") == id2, 45)
            if resp2:
                ana.marca(f"{resp2['type']} #{id2[:6]}: {resp2['content'][:140]}")
            resultados.append(ok(resp2 is not None and resp2["type"] == "BOT_RESP", "pergunta de continuação respondida"))

            id3 = bruno.rede.perguntar_bot("Qual problema eu relatei antes e em que horário?")
            bruno.marca(f"@bot Qual problema eu relatei antes e em que horário?  [#{id3[:6]}]")
            resp3 = bruno.esperar(lambda e: e["type"] in ("BOT_RESP", "BOT_ERR") and e.get("ref") == id3, 45)
            if resp3:
                bruno.marca(f"{resp3['type']} #{id3[:6]}: {resp3['content'][:140]}")
            vazou = resp3 is not None and "22" in resp3["content"]
            resultados.append(ok(resp3 is not None and not vazou,
                                 "contexto do bruno separado (o bot não conhece o problema da ana)"))
            nao_recebeu = carla.esperar(lambda e: e["type"] in ("BOT_RESP", "BOT_ERR"), 1)
            resultados.append(ok(nao_recebeu is None, "respostas do bot chegaram só a quem perguntou"))

            # --- falha real da LLM (#17)
            bot.terminate()
            bot.wait(5)
            time.sleep(0.5)
            abrir("-m", "bot", "--simular-falha", "timeout")
            time.sleep(1.5)
            lt.append((time.time() - t0, "sistema", "bot reiniciado com --simular-falha timeout"))
            id4 = ana.rede.perguntar_bot("Teste de falha: minha internet está lenta")
            ana.marca(f"@bot Teste de falha…  [#{id4[:6]}]")
            resp4 = ana.esperar(lambda e: e["type"] in ("BOT_RESP", "BOT_ERR") and e.get("ref") == id4, 20)
            if resp4:
                ana.marca(f"{resp4['type']} [{resp4.get('code')}] {resp4['content']}")
            resultados.append(ok(resp4 is not None and resp4.get("code") == "LLM_TIMEOUT",
                                 "falha da LLM vira BOT_ERR LLM_TIMEOUT e o sistema continua"))
            bruno.rede.enviar_sala("o chat continua funcionando depois da falha?")
            resultados.append(ok(carla.esperar(lambda e: e["type"] == "MSG", 5) is not None,
                                 "chat continua funcionando depois da falha"))

            # --- desconexões
            carla.rede.sair()
            carla.marca("saiu (BYE)")
            leave = ana.esperar(lambda e: e["type"] == "LEAVE" and e["content"] == "carla", 5)
            resultados.append(ok(leave is not None and leave.get("code") == "LEFT", "saída normal avisada (LEFT)"))
            bruno.rede._fechar()                                     # sem BYE: queda abrupta
            bruno.marca("conexão derrubada sem BYE")
            leave = ana.esperar(lambda e: e["type"] == "LEAVE" and e["content"] == "bruno", 5)
            resultados.append(ok(leave is not None and leave.get("code") == "CONNECTION_LOST",
                                 "queda abrupta detectada (CONNECTION_LOST)"))
            ana.rede.sair()
        except Exception as e:                                      # registra e segue para o resumo
            resultados.append(ok(False, f"cenário interrompido: {type(e).__name__}: {e}"))
        finally:
            for p in reversed(processos):
                if p.poll() is None:
                    p.terminate()
            for p in processos:
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()

    arq_lt = EVID / f"concorrencia_{CARIMBO}.txt"
    with open(arq_lt, "w", encoding="utf-8") as f:
        f.write(f"Linha do tempo do cenário real — {datetime.now():%d/%m/%Y %H:%M}\n")
        f.write("Processos separados: servidor, bot (Groq) e 3 clientes (ana TLS, bruno e carla TCP)\n\n")
        f.write(f"{'tempo':>8}  {'quem':<8} evento\n")
        for t, quem, texto in lt:
            f.write(f"{t:7.2f}s  {quem:<8} {texto}\n")
    log(f"\n  Linha do tempo salva em {arq_lt.relative_to(RAIZ)}")
    log(f"  Log do servidor salvo em {arq_srv.relative_to(RAIZ)}")
    return all(resultados)


# =========================================================================== principal
def main() -> None:
    parser = argparse.ArgumentParser(description="Valida o projeto e gera evidências")
    parser.add_argument("--rapido", action="store_true", help="pula o cenário com a LLM real")
    opcoes = parser.parse_args()
    EVID.mkdir(exist_ok=True)
    sys.path.insert(0, str(RAIZ))

    log(f"VALIDAÇÃO DO PROJETO — {datetime.now():%d/%m/%Y %H:%M:%S}")
    amb = verificar_ambiente()
    certs = verificar_certificados() if amb.get("crypto") else ok(False, "certificados (falta a cryptography)")
    testes = rodar_testes()
    cenario = None
    if not opcoes.rapido:
        cenario = cenario_real(tls_ok=certs)

    titulo("RESUMO")
    ok(all(amb.values()), "ambiente")
    ok(bool(certs), "certificados TLS")
    ok(testes, "testes automáticos")
    if cenario is not None:
        ok(cenario, "cenário real")
    arq = EVID / f"validacao_{CARIMBO}.txt"
    arq.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"\nResultado salvo em {arq.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
