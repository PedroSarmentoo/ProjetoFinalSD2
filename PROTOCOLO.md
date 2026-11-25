# Protocolo de aplicação — Chat SD2 (versão 1)

Este documento define como servidor, clientes humanos e bot conversam pelos
sockets TCP. **Todos os módulos devem seguir exatamente o que está aqui.**
Qualquer mudança precisa ser combinada pelo trio, porque altera os três
componentes ao mesmo tempo.

> Status: **v1 — proposta para aprovação** (issue #1)

---

## 1. Transporte

| Item | Valor |
|---|---|
| Protocolo de transporte | TCP (API Socket direta) |
| Porta sem criptografia | **5000** (usada também como execução de referência no Wireshark) |
| Porta com TLS | **5001** (mesmo protocolo, apenas envolvido em TLS — ver #19/#20) |
| Endereço da demonstração | `127.0.0.1` (tudo em um PC — decisão da #29) |
| Codificação | UTF-8 |

O conteúdo trafegado é **idêntico** nas duas portas. A diferença é só que, na
5001, os bytes passam por TLS antes de ir para a rede.

## 2. Delimitação das mensagens (framing)

O TCP é um **fluxo de bytes**: um `send` não corresponde a um `recv`. Um
`recv` pode trazer meia mensagem, uma mensagem inteira ou várias juntas.
Por isso cada mensagem é delimitada explicitamente:

- **Uma mensagem = um objeto JSON em UTF-8 seguido de `\n`** (byte `0x0A`).
- O JSON é serializado **sem quebras de linha** (`json.dumps` padrão já
  garante isso; uma quebra de linha *dentro* do texto vira `\n` escapado).
- O receptor acumula os bytes num buffer e só processa quando encontra `\n`.
- **Tamanho máximo:** 64 KiB (65 536 bytes) por mensagem, contando o `\n`.
  Se o buffer passar disso sem encontrar `\n`, a conexão é encerrada com
  `ERROR` `MSG_TOO_LARGE`.

```
{"v":1,"type":"MSG","id":"9f1c…","from":"ana","to":"*","ts":1764072000.5,"content":"oi"}\n
```

## 3. Envelope

Toda mensagem tem estes campos:

| Campo | Tipo | Descrição |
|---|---|---|
| `v` | inteiro | Versão do protocolo. Sempre `1`. |
| `type` | texto | Tipo da mensagem (seção 4). |
| `id` | texto | Identificador **único desta mensagem**: UUID4 em hexadecimal (32 caracteres), gerado por quem envia. |
| `from` | texto | Remetente: nome do usuário, `"bot"` ou `"servidor"`. |
| `to` | texto | Destinatário: nome do usuário, `"*"` (todos), `"bot"` ou `"servidor"`. |
| `ts` | número | Instante de criação, em segundos desde a época Unix (`time.time()`). |
| `content` | texto ou lista | Conteúdo. Texto na maioria dos tipos; lista em `USERS`. |

Campos adicionais, usados só por alguns tipos:

| Campo | Usado em | Descrição |
|---|---|---|
| `ref` | `BOT_REQ`, `BOT_RESP`, `BOT_ERR`, `ERROR` | **Identificador da solicitação**: o `id` da mensagem original que esta responde. É o que liga a resposta do bot à pergunta certa. |
| `role` | `HELLO` | Papel de quem conecta: `"human"` ou `"bot"`. |
| `on_behalf_of` | `BOT_REQ` | Usuário que fez a pergunta ao bot. |
| `code` | `ERROR`, `BOT_ERR`, `BYE` | Código do erro ou do motivo (seção 6). |

### Regras do envelope

1. **O servidor não confia no campo `from` enviado pelos clientes.** Depois do
   `HELLO`, ele sobrescreve `from` com o nome associado àquela conexão. Assim
   ninguém consegue se passar por outro usuário ou pelo bot.
2. Mensagem com JSON válido mas campo obrigatório faltando, tipo errado ou
   `type` desconhecido → `ERROR` `BAD_MESSAGE` / `UNKNOWN_TYPE` (a conexão continua).
3. Bytes que não são JSON válido → `ERROR` `BAD_MESSAGE` e a conexão é
   **encerrada** (o fluxo pode ter perdido a sincronia).
4. `v` diferente de `1` → `ERROR` `VERSION_UNSUPPORTED` e a conexão é encerrada.

## 4. Tipos de mensagem

### 4.1 Cliente → servidor

| `type` | Quem envia | Campos relevantes | Efeito |
|---|---|---|---|
| `HELLO` | humano ou bot | `from` = nome desejado, `role` | Primeira mensagem obrigatória da conexão. |
| `MSG` | humano | `to` = `"*"` ou nome; `content` = texto | Mensagem para a sala ou privada. Se `content` começar com `@bot`, vira pergunta ao bot (seção 5). |
| `BOT_RESP` | bot | `to` = usuário, `ref`, `content` | Resposta da LLM. |
| `BOT_ERR` | bot | `to` = usuário, `ref`, `code`, `content` | Falha ao consultar a LLM. |
| `BYE` | humano ou bot | — | Saída voluntária. O servidor encerra a conexão. |
| `PING` / `PONG` | qualquer um | — | Opcional (seção 7). |

### 4.2 Servidor → cliente

| `type` | Para quem | Campos relevantes | Quando |
|---|---|---|---|
| `WELCOME` | quem fez `HELLO` | `to` = nome aceito, `content` = texto de boas-vindas | `HELLO` aceito. |
| `USERS` | todos os humanos | `content` = lista de nomes online (inclui `"bot"` se conectado) | Logo após o `WELCOME` e sempre que alguém entra ou sai. |
| `JOIN` | todos os humanos, menos quem entrou | `content` = nome | Alguém entrou. |
| `LEAVE` | todos os humanos | `content` = nome, `code` = motivo | Alguém saiu ou caiu. |
| `MSG` | destinatário(s) | `from` = remetente original | Repasse de mensagem da sala ou privada. |
| `BOT_REQ` | bot | `ref`, `on_behalf_of`, `content` = pergunta **sem** o `@bot` | Um humano perguntou ao bot. |
| `BOT_RESP` | **só o solicitante** | `from` = `"bot"`, `ref` | Repasse da resposta do bot. |
| `BOT_ERR` | **só o solicitante** | `from` = `"bot"` ou `"servidor"`, `ref`, `code` | Falha do bot, bot desconectado ou tempo limite. |
| `ERROR` | quem causou | `code`, `content`, `ref` (se houver) | Erro de protocolo ou de roteamento. |
| `BYE` | o cliente | `code` = motivo | O servidor vai encerrar a conexão (expulsão ou desligamento). |

## 5. Regras de roteamento

1. **Sala:** `MSG` com `to: "*"` → repassada a todos os humanos **exceto o remetente**
   (o cliente já mostra a própria mensagem localmente).
2. **Privada:** `MSG` com `to: "<nome>"` → repassada só a esse usuário. Se ele
   não existir → `ERROR` `USER_NOT_FOUND` ao remetente.
3. **Pergunta ao bot:** `MSG` cujo `content`, sem espaços no início, começa com
   `@bot` (maiúsculas ou minúsculas) seguido de espaço ou fim do texto:
   - o `to` original é ignorado e a pergunta **não vai para a sala**;
   - o servidor envia ao bot um `BOT_REQ` com `ref` = `id` da `MSG`,
     `on_behalf_of` = remetente e `content` = texto sem o prefixo `@bot`;
   - pergunta vazia (`@bot` sozinho) → `ERROR` `BAD_MESSAGE`;
   - bot não conectado → `BOT_ERR` `BOT_OFFLINE` imediato ao solicitante;
   - cada usuário pode ter **no máximo 3 perguntas pendentes**; a quarta recebe
     `ERROR` `BOT_BUSY`.
4. **Resposta do bot:** o servidor só repassa `BOT_RESP`/`BOT_ERR` se o `ref`
   estiver na tabela de pendentes **e** o `to` for o mesmo `on_behalf_of`
   registrado. Caso contrário, descarta e registra um evento. A resposta vai
   **apenas ao solicitante** (escopo mínimo do edital).
5. **Tempo limite no servidor:** se o bot não responder em **30 s**, o servidor
   remove o pendente e envia `BOT_ERR` `BOT_TIMEOUT` ao solicitante. Uma
   resposta que chegue depois é descartada.
6. Mensagens de **uma mesma conexão** são processadas na ordem em que chegaram.
   Entre conexões diferentes não há garantia de ordem global.

## 6. Identificação e códigos

### 6.1 Nomes

- Formato: 1 a 20 caracteres, só letras sem acento, números, `_` e `-`
  (`^[A-Za-z0-9_-]{1,20}$`).
- Únicos **sem diferenciar maiúsculas e minúsculas** (`Ana` e `ana` são o mesmo nome).
- Reservados para humanos: `bot`, `servidor`, `todos`, `*`.
- O bot se conecta com `from: "bot"` e `role: "bot"`. Só pode haver **um bot** conectado.

### 6.2 Códigos

| Código | Em | Fatal? | Significado |
|---|---|---|---|
| `NAME_TAKEN` | `ERROR` | sim | Nome já em uso. |
| `NAME_INVALID` | `ERROR` | sim | Nome fora do formato. |
| `NAME_RESERVED` | `ERROR` | sim | Humano tentou usar nome reservado. |
| `BOT_ALREADY_CONNECTED` | `ERROR` | sim | Já existe um bot conectado. |
| `HANDSHAKE_TIMEOUT` | `ERROR` | sim | Nenhum `HELLO` em 10 s. |
| `NOT_REGISTERED` | `ERROR` | sim | Mensagem enviada antes do `HELLO`. |
| `VERSION_UNSUPPORTED` | `ERROR` | sim | `v` diferente de 1. |
| `MSG_TOO_LARGE` | `ERROR` | sim | Mensagem acima de 64 KiB. |
| `BAD_MESSAGE` | `ERROR` | só se não for JSON | Mensagem malformada ou campo inválido. |
| `UNKNOWN_TYPE` | `ERROR` | não | `type` desconhecido. |
| `USER_NOT_FOUND` | `ERROR` | não | Destinatário da privada não está online. |
| `BOT_BUSY` | `ERROR` | não | Mais de 3 perguntas pendentes. |
| `BOT_OFFLINE` | `BOT_ERR` | não | Bot não está conectado (ou caiu com a pergunta pendente). |
| `BOT_TIMEOUT` | `BOT_ERR` | não | Bot não respondeu em 30 s. |
| `LLM_TIMEOUT` | `BOT_ERR` | não | A LLM não respondeu no tempo do bot. |
| `LLM_RATE_LIMIT` | `BOT_ERR` | não | Limite de requisições da LLM (HTTP 429). |
| `LLM_AUTH` | `BOT_ERR` | não | Chave da LLM inválida (HTTP 401). |
| `LLM_UNAVAILABLE` | `BOT_ERR` | não | Sem rede, modelo inexistente ou erro da API. |
| `LEFT` | `LEAVE` / `BYE` | — | Saída voluntária. |
| `CONNECTION_LOST` | `LEAVE` | — | Conexão caiu sem `BYE`. |
| `KICKED` | `LEAVE` / `BYE` | — | Desconectado pelo servidor. |
| `SERVER_SHUTDOWN` | `BYE` | — | Servidor sendo desligado. |

**Fatal** = depois de enviar o `ERROR`, o servidor fecha a conexão.

## 7. Conexão, saída e falhas

- **Handshake:** o primeiro envio do cliente tem de ser `HELLO` em até 10 s.
  Resposta: `WELCOME` seguido de `USERS` (sucesso) ou `ERROR` fatal.
- **Saída normal:** cliente envia `BYE` → servidor fecha a conexão, remove o
  participante e envia `LEAVE` (`LEFT`) + `USERS` aos demais.
- **Queda abrupta:** `recv` retorna vazio ou dá erro (`ConnectionResetError`
  etc.) → mesmo tratamento, com `LEAVE` `CONNECTION_LOST`. Perguntas pendentes
  desse usuário são descartadas.
- **Queda do bot:** todas as perguntas pendentes recebem `BOT_ERR` `BOT_OFFLINE`.
- **Queda do servidor:** o cliente detecta o fim da conexão, avisa o usuário e
  não trava a interface.
- **PING/PONG (opcional):** qualquer lado pode enviar `PING`; quem recebe
  responde `PONG` com `ref` = `id` do `PING`. Não é obrigatório para a
  detecção de quedas, que já acontece pelo próprio TCP.

## 8. Exemplos

### 8.1 Entrada

```
ana  → servidor  {"v":1,"type":"HELLO","id":"a1…","from":"ana","to":"servidor","ts":…,"content":"","role":"human"}
servidor → ana   {"v":1,"type":"WELCOME","id":"s1…","from":"servidor","to":"ana","ts":…,"content":"Bem-vinda, ana!"}
servidor → ana   {"v":1,"type":"USERS","id":"s2…","from":"servidor","to":"ana","ts":…,"content":["ana","bot","bruno"]}
servidor → bruno {"v":1,"type":"JOIN","id":"s3…","from":"servidor","to":"*","ts":…,"content":"ana"}
```

### 8.2 Pergunta ao bot (percurso completo)

```
ana → servidor   {"v":1,"type":"MSG","id":"m42","from":"ana","to":"*","ts":…,
                  "content":"@bot minha internet cai toda noite"}

servidor → bot   {"v":1,"type":"BOT_REQ","id":"s9","from":"servidor","to":"bot","ts":…,
                  "ref":"m42","on_behalf_of":"ana","content":"minha internet cai toda noite"}

   (o bot consulta a LLM por HTTPS com o histórico da ana — enquanto isso
    os outros usuários continuam conversando normalmente)

bot → servidor   {"v":1,"type":"BOT_RESP","id":"b7","from":"bot","to":"ana","ts":…,
                  "ref":"m42","content":"1. Verifique se há reinício agendado..."}

servidor → ana   {"v":1,"type":"BOT_RESP","id":"b7","from":"bot","to":"ana","ts":…,
                  "ref":"m42","content":"1. Verifique se há reinício agendado..."}
```

A Ana sabe que a resposta é da pergunta `m42` pelo campo `ref`. Nenhum outro
usuário recebe a pergunta nem a resposta.

### 8.3 Falha da LLM

```
bot → servidor → ana  {"v":1,"type":"BOT_ERR","id":"b8","from":"bot","to":"ana","ts":…,
                       "ref":"m43","code":"LLM_TIMEOUT",
                       "content":"A LLM não respondeu em 15 s. Tente novamente."}
```

### 8.4 Mensagem privada para alguém offline

```
ana → servidor   {"v":1,"type":"MSG","id":"m50","from":"ana","to":"carla","ts":…,"content":"oi"}
servidor → ana   {"v":1,"type":"ERROR","id":"s20","from":"servidor","to":"ana","ts":…,
                  "ref":"m50","code":"USER_NOT_FOUND","content":"carla não está online"}
```

## 9. Resumo dos tempos e limites

| Parâmetro | Valor |
|---|---|
| Tamanho máximo de mensagem | 64 KiB |
| Tempo para enviar `HELLO` | 10 s |
| Tempo limite da LLM no bot (`LLM_TIMEOUT`) | 15 s (configurável no `.env`) |
| Tempo limite do servidor para o bot | 30 s |
| Perguntas pendentes por usuário | 3 |
| Histórico da LLM por usuário | 3 trocas (pergunta + resposta) |

O tempo do servidor (30 s) é maior que o do bot (15 s) de propósito: normalmente
quem avisa a falha é o bot, com o motivo exato. O limite do servidor só atua se
o próprio bot travar ou sumir.
