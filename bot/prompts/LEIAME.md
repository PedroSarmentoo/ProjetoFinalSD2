# Instrução de comportamento do bot (issue #3)

| Arquivo | Uso |
|---|---|
| `original/prompt_assistente_virtual_net.txt` | Prompt completo escrito pela Bruna (Virtual Net). Referência e relatório. |
| `original/base_luzes_roteador.pdf` | Base de conhecimento original "Status das Luzes do Roteador". |
| `instrucao.md` | **Versão usada pelo bot**: o prompt condensado. `{provedor}` e `{agora}` são preenchidos a cada consulta. |
| `base_luzes.md` | Base de luzes já corrigida conforme as regras do prompt. Só é enviada quando a conversa fala de luzes, roteador, fibra ou "sem internet". |

## Por que condensar

O plano gratuito do Groq para o `openai/gpt-oss-120b` permite **8 mil tokens por minuto**.
O prompt original tem cerca de 9 mil tokens e vai junto em **toda** pergunta — uma única
consulta já estouraria o limite. A versão condensada tem ~1,5 mil tokens (~2 mil com a base
de luzes), e o pior caso de uma pergunta (com histórico cheio) fica abaixo de 3,5 mil
(`tests/test_bot_llm.py::test_cabe_no_limite_do_plano_gratuito`).

## O que foi mantido do original

- Identidade de assistente virtual, sem acesso ao sistema (nunca diz "verifiquei", "gerei", "cancelei").
- Regras de segurança: nunca orientar mexer na fibra nem usar o reset; não pedir dados pessoais.
- Dados da empresa: horários, canais, pagamento, desbloqueio, vencimentos, planos e condições.
- Suporte técnico em etapas, financeiro, quando indicar cada equipe e o fluxo de cancelamento.
- Uso da data e hora atuais para dizer se a equipe está atendendo.

## O que mudou

- **Sem negrito** (`*assim*` era estilo WhatsApp; a interface do chat é texto simples).
- **Base de luzes corrigida** no próprio texto (reinício de 30 s, olhar a fibra sem tocar, sem
  painel web), em vez de pedir ao modelo para resolver as divergências.
- Exemplos e detalhes longos foram resumidos.
- Histórico de **4 trocas** por usuário, guardando só os primeiros 600 caracteres de cada
  resposta do bot.
