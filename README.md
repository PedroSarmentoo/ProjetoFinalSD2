# ProjetoFinalSD2 — Chat distribuído com sockets, TLS e bot com LLM

Trabalho prático de **Sistemas Distribuídos II** (Engenharia de Sistemas — Unimontes).
Chat cliente-servidor sobre **sockets TCP** com **uma thread por cliente**, canal
**TLS**, interface gráfica no servidor e um **bot de atendimento técnico de provedor
de internet** que consulta uma LLM real (Groq).

> Estado: **esqueleto** — estrutura e contratos definidos; implementação em andamento.
> Acompanhe as tarefas nas [issues](../../issues) e no quadro do projeto.

## Arquitetura

Três componentes em **processos separados**, todos no mesmo PC (`127.0.0.1`):

```
 cliente (ana) ──┐                                   ┌── HTTPS ──► Groq (LLM)
 cliente (bruno) ├── TCP :5000 / TLS :5001 ──► SERVIDOR ◄── TCP ──── BOT
 cliente (carla) ┘                          (GUI + 1 thread/cliente)
```

O protocolo de mensagens está em **[PROTOCOLO.md](PROTOCOLO.md)**.

## Estrutura e responsáveis

| Pasta / arquivo | Conteúdo | Responsável | Issues |
|---|---|---|---|
| `PROTOCOLO.md` | Protocolo de aplicação v1 | Pedro | #1 |
| `common/config.py` | Configuração (lê o `.env`) e limites do protocolo | Pedro | #2 |
| `common/protocolo.py` | Framing, envelope, validação | Pedro | #4 |
| `common/eventos.py` | Contrato rede → interfaces (fila) | Pedro + Bruna | #9 |
| `common/tls.py` | Contextos TLS com validação do certificado | Fellipe | #19, #20 |
| `servidor/nucleo.py` | Aceitação, threads, locks, roteamento, desconexões | Pedro | #5–#9 |
| `servidor/gui.py` | Interface do servidor | Bruna | #13 |
| `cliente/rede.py` | Rede do cliente (thread de recepção) | Pedro | #10 |
| `cliente/gui.py` | Interface do cliente | Bruna | #14 |
| `bot/rede.py` | Rede do bot (pool de threads) | Pedro | #11 |
| `bot/llm.py` | Chamada ao Groq e tratamento de falhas | Bruna | #3, #15 |
| `bot/historico.py` | Histórico curto por usuário | Bruna | #16 |
| `certs/gerar_certificados.py` | CA de teste + certificado do servidor | Fellipe | #18 |
| `evidencias/` | Prints, logs e capturas do Wireshark | Trio | #30 |
| `docs/` | Relatório e material de apoio | Trio | #23 |

Cada arquivo começa dizendo quem é o responsável e qual é o contrato com os
outros módulos. Funções ainda não implementadas lançam `NotImplementedError`
com o número da issue.

## Como executar

Requer **Python 3.10+** com `tkinter` (já vem no instalador do Windows). Sem dependências externas.

1. Copie `.env.example` para `.env` e coloque a chave do Groq em `LLM_API_KEY`.
2. Gere os certificados (uma vez): `python certs/gerar_certificados.py`
3. Em terminais separados, a partir da raiz do projeto:

```bash
python -m servidor      # 1 terminal
python -m bot           # 1 terminal
python -m cliente       # 1 terminal POR usuário (ana, bruno, carla...)
```

## Como trabalhamos

- Cada integrante trabalha na **sua branch** (`Pedro`, `Bruna`, `Fellipe`) e leva para a
  `main` por **pull request**. Escreva `fecha #N` na descrição do PR para fechar a issue.
- **Nunca** faça commit do `.env` nem de arquivos `.key` (o `.gitignore` já bloqueia).
- Mudanças no `PROTOCOLO.md` só com acordo do trio.
