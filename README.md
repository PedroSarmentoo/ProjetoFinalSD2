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
| `tests/` | Testes automatizados (`unittest`) | Trio | #4, #12 |
| `common/eventos.py` | Contrato rede → interfaces (fila) | Pedro + Bruna | #9 |
| `common/tls.py` | Contextos TLS com validação do certificado | Fellipe | #19, #20 |
| `docs/criptografia.md` | Mecanismo, validação, enlaces protegidos, teste negativo e roteiro do Wireshark | Fellipe | #19–#22 |
| `servidor/nucleo.py` | Aceitação, threads, locks, roteamento, desconexões | Pedro | #5–#9 |
| `servidor/gui.py` | Interface do servidor | Bruna | #13 |
| `cliente/rede.py` | Rede do cliente (thread de recepção) | Pedro | #10 |
| `cliente/gui.py` | Interface do cliente | Bruna | #14 |
| `bot/rede.py` | Rede do bot (pool de threads) | Pedro | #11 |
| `iniciar.py` | Abre servidor, bot e clientes, cada um em seu processo | Trio | — |
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

1. Copie `.env.example` para `.env` (na raiz) e coloque a chave do Groq em `LLM_API_KEY`.
2. Gere os certificados do TLS (uma vez): `pip install cryptography` e depois
   `python certs/gerar_certificados.py`. Sem certificados o servidor sobe só na porta 5000.

**Tudo de uma vez** — cada componente abre em um processo separado:

```bash
python iniciar.py                 # servidor (GUI) + bot + ana, bruno e carla
python iniciar.py ana bruno       # escolhe os clientes
python iniciar.py --tls           # clientes e bot pela porta TLS (5001)
python iniciar.py --tls-para ana  # só a ana com TLS (compara os dois canais na GUI)
python iniciar.py --sem-bot       # sem o bot
```

Ctrl+C no terminal (ou fechar a janela do servidor) encerra tudo.

**Ou manualmente** — um terminal para CADA comando (no VS Code: botão **+** do painel do terminal).
Cada comando fica rodando até a janela ser fechada, por isso não dá para rodar todos no mesmo terminal:

```bash
python -m servidor              # ou: python -m servidor --sem-gui
python -m bot                   # precisa do servidor já aberto
python -m cliente ana --conectar
python -m cliente bruno --conectar
python -m cliente carla --conectar
```

Teste rápido só da LLM (sem servidor): `python -m bot.llm "minha internet cai toda noite"`

## Testes

```bash
python -m unittest discover -s tests -v
```

| Arquivo | O que cobre |
|---|---|
| `tests/test_protocolo.py` | Framing (mensagem partida, várias num `recv`, UTF-8 cortado), limites, erros e regras de nome/`@bot` (#4) |
| `tests/test_servidor.py` | Handshake, nomes, entrada/saída/queda, expulsão, 30 clientes simultâneos, sala/privado, percurso completo do `@bot`, conversa continuando durante a consulta, tempo limite, queda do bot com perguntas pendentes (#5–#8) |
| `tests/test_bot_llm.py` | Chamada à LLM com API falsa (instrução, histórico, 401/429/404, tempo limite, sem rede, markdown) e histórico por usuário (#15, #16) |
| `tests/test_cliente.py` | Rede do cliente contra o servidor real: conexão, nome recusado, servidor fora do ar, sala/privado, `@bot` com `ref`, envio sem bloquear durante a consulta, saída, expulsão e queda (#10) |
| `tests/test_bot_rede.py` | Bot real com LLM substituída: `ref` e usuário corretos, histórico por usuário, consultas em paralelo, falha da LLM vira `BOT_ERR`, erro inesperado não derruba o bot (#11) |
| `tests/test_tls.py` | TLS com CA de teste: canal TLS junto com TCP, bot por TLS, recusa de certificado de outra CA e de nome errado, bytes capturados (legível na 5000, cifrado na 5001) (#18–#21) |

## Como trabalhamos

- Cada integrante trabalha na **sua branch** (`Pedro`, `Bruna`, `Fellipe`) e leva para a
  `main` por **pull request**. Escreva `fecha #N` na descrição do PR para fechar a issue.
- **Nunca** faça commit do `.env` nem de arquivos `.key` (o `.gitignore` já bloqueia).
- Mudanças no `PROTOCOLO.md` só com acordo do trio.
