# Criptografia — TLS sobre sockets (Fellipe · issues #18 a #22)

Base para a seção de criptografia do relatório e roteiro da parte de segurança do vídeo.

## 1. Mecanismo escolhido

**TLS (biblioteca `ssl` do Python) sobre o próprio socket TCP**, com certificado X.509.
O servidor escuta em duas portas com o **mesmo protocolo de aplicação** (PROTOCOLO.md):

| Porta | Canal | Uso |
|---|---|---|
| 5000 | TCP sem criptografia | Execução de referência para o Wireshark |
| 5001 | TCP + TLS | Canal protegido |

O TLS dá **confidencialidade** (cifra), **integridade** (qualquer alteração dos bytes é detectada) e
**autenticação do servidor** (o cliente confere o certificado).

## 2. Certificados (#18)

`python certs/gerar_certificados.py` cria uma **CA de teste** e um **certificado de servidor assinado por ela**:

| Arquivo | Quem usa | Para quê |
|---|---|---|
| `certs/ca.crt` | clientes e bot | é a única CA em que eles confiam |
| `certs/ca.key` | ninguém em execução | só assinou o certificado do servidor |
| `certs/servidor.crt` | servidor | é apresentado no handshake TLS |
| `certs/servidor.key` | servidor | prova que o servidor é o dono do certificado |

- Chaves **ECDSA P-256**, assinatura **SHA-256**, validade de 365 dias.
- **SAN** (nomes válidos): `localhost` e `127.0.0.1` — a demonstração roda toda em um PC (#29).
- Extensões conforme RFC 5280 (`basicConstraints`, `keyUsage`, `extendedKeyUsage=serverAuth`,
  identificadores de chave), exigidas pela verificação estrita.
- **Nada disso vai para o git** (`.gitignore`): cada um gera os seus. Chaves privadas nunca são versionadas.

## 3. Validação explícita do certificado (#19)

Em `common/tls.py`, o **cliente** (`contexto_cliente`) faz quatro verificações antes de enviar qualquer dado:

1. `verify_mode = CERT_REQUIRED` — o servidor é obrigado a apresentar certificado, e a cadeia precisa
   terminar na CA confiável (`ca.crt`). Outra CA → conexão **recusada**.
2. `check_hostname = True` — o endereço usado para conectar (`127.0.0.1`) precisa estar no SAN.
3. `VERIFY_X509_STRICT` — rejeita certificados fora das regras da RFC 5280.
4. `minimum_version = TLSv1_2` — na prática negocia **TLS 1.3** com `TLS_AES_256_GCM_SHA384`.

**Nunca** é usado `CERT_NONE` nem `check_hostname = False`.

## 4. Enlaces protegidos e onde ocorre a decifragem (#20)

```
ana (TLS)  ──[cifrado]──►  SERVIDOR  ──[em claro]──►  bruno (TCP :5000)
           wrap_socket          │  decifra na thread           envia sem TLS
           do cliente           │  da ana (ssl.SSLSocket)
                                └─[cifrado]──►  carla (se estiver na 5001)
```

- O TLS protege o **enlace cliente ↔ servidor** (não é criptografia ponta a ponta).
- **Cifragem:** no `wrap_socket` do cliente, a cada `sendall`.
- **Decifragem:** no servidor, dentro da **thread dedicada àquele cliente**, no `recv` do `SSLSocket`.
  O servidor precisa do texto em claro para ler o envelope e rotear.
- Cada destinatário recebe pelo seu próprio enlace: cifrado se estiver na 5001, em claro na 5000.
- O **bot** também pode usar TLS (`python -m bot --tls`, ou `python iniciar.py --tls`).
- A GUI do servidor mostra o canal de cada participante (TLS em verde) e registra, nos eventos,
  a versão e a cifra de cada sessão TLS.

## 5. Teste negativo (#21)

O cliente precisa **recusar** um servidor com certificado que não seja da CA confiável.

```bash
python certs/gerar_certificados.py --falsos      # cria certs/falsos/ (assinado por OUTRA CA)
python -m servidor --certificado-falso           # servidor apresenta o certificado falso na 5001
python -m cliente ana --conectar --tls           # o cliente RECUSA
```

Resultado esperado na tela de conexão do cliente:
`Certificado do servidor RECUSADO: unable to get local issuer certificate. A conexão não é segura.`
E nos eventos do servidor: `Handshake TLS recusado de 127.0.0.1:…`.

Também coberto por testes automáticos (`tests/test_tls.py`): CA desconhecida, nome fora do SAN,
CA ausente, cliente sem TLS na porta TLS e cliente TLS na porta sem TLS.

## 6. Comparativo no Wireshark (#22)

### Preparação (Windows)
1. Instale o **Wireshark** e, durante a instalação, o **Npcap** com a opção
   **"Support loopback traffic"** marcada. Sem ela não aparece a interface de loopback.
2. Gere os certificados: `python certs/gerar_certificados.py`.

### Captura
1. Abra o Wireshark e escolha **"Adapter for loopback traffic capture"** (ou "Npcap Loopback Adapter").
2. Filtro de exibição: `tcp.port == 5000 || tcp.port == 5001`
3. Comece a captura e rode `python iniciar.py --tls-para ana`
   (ana entra pela 5001 com TLS; bruno e carla pela 5000 sem TLS).
4. Envie a **mesma mensagem conhecida** pelos dois canais:
   - na janela do **bruno** (sem TLS): `SEGREDO-SD2-roteador-TP-Link`
   - na janela da **ana** (com TLS): `SEGREDO-SD2-roteador-TP-Link`
5. Pare a captura e salve como `evidencias/captura_tcp_vs_tls.pcapng`.

### Análise
| Execução | Filtro | O que se vê |
|---|---|---|
| Sem criptografia | `tcp.port == 5000` → botão direito → **Follow → TCP Stream** | o JSON inteiro legível: `"type":"MSG"`, `"from":"bruno"`, `"content":"SEGREDO-SD2-…"` |
| Com TLS | `tcp.port == 5001` (ou `tls`) | **Client Hello / Server Hello**, depois só **Application Data** com bytes ilegíveis; `Follow → TCP Stream` não mostra o texto |
| Busca | **Edit → Find Packet → String** `SEGREDO-SD2` | encontra só pacotes da porta 5000 |

Prints para o relatório (salvar em `evidencias/`):
1. `wireshark_5000_follow.png` — mensagem legível no TCP Stream.
2. `wireshark_5001_handshake.png` — Client Hello / Server Hello (versão TLS 1.3).
3. `wireshark_5001_appdata.png` — Application Data cifrado.

**Por que o conteúdo fica protegido:** no handshake, cliente e servidor combinam uma chave de sessão
(troca de chaves ECDHE) que nunca trafega pela rede; o servidor prova sua identidade com o certificado.
A partir daí cada registro é cifrado com AES-256-GCM, que também autentica o conteúdo. Quem captura
o tráfego vê apenas o tamanho e o horário dos pacotes, não o texto. Na porta 5000 os bytes do socket
são o próprio JSON.

O teste automático `test_com_tls_a_mensagem_nao_aparece_na_rede` faz a mesma verificação de forma
programática: intercepta os bytes e confirma que o texto aparece na porta 5000 e não aparece na 5001.
