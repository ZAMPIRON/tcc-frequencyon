# FrequencyON: suíte de testes automatizados com Cypress

Automação dos **83 casos de teste da Seção 4** (Matriz Formal de Execução de Casos de Teste) do relatório
TSR-FON-2026-01 do FrequencyON. Cada `it(...)` tem o identificador do caso (`CT-xx`) e o requisito (`[RFxx]`).

## Requisitos

- Node.js 18 ou superior
- Python 3 com as dependências do FrequencyON (`pip install -r requirements.txt` na pasta do sistema)
- O código do FrequencyON. Por padrão a suíte procura o sistema na pasta acima desta (`../`).
  Para outro lugar, defina `FREQUENCYON_DIR` com o caminho do sistema.

## Como executar

```bash
npm install
npm test               # executa tudo sem abrir janela (navegador Electron)
npm run test:chrome    # o mesmo no Google Chrome
npm run cy:open        # abre o Cypress para acompanhar os casos
```

> No terminal integrado do VS Code, se aparecer `bad option: --smoke-test`, a variável
> `ELECTRON_RUN_AS_NODE` está definida. Rode `set ELECTRON_RUN_AS_NODE=` (cmd),
> `Remove-Item Env:ELECTRON_RUN_AS_NODE` (PowerShell) ou `env -u ELECTRON_RUN_AS_NODE npm test` (bash) antes.

Ao iniciar, a configuração (`cypress.config.js`):

1. copia o banco do projeto (`instance/frequencyon.db`) para `.tmp/` e cria a massa de teste
   (`apoio/ponte.py preparar`): turmas C99, C98, C97 e C96, alunos de teste e senhas conhecidas **só na cópia**;
2. sobe dois servidores do sistema sobre essa cópia, em HTTPS:
   - **rodada 1**: `https://127.0.0.1:5055`, configuração normal (prova de vida ligada);
   - **rodada 2**: `https://127.0.0.1:5056`, com `PROVA_DE_VIDA=0`, usada só nos casos CT-82 e CT-83
     (uma foto parada não pisca, então só assim dá para medir a identificação);
3. ao terminar, grava o resumo em `resultados/resultado-execucao.json` e derruba os servidores.

O banco, as fotos e o certificado do projeto não são alterados: e-mails vão para `.tmp/caixa_saida.jsonl`,
fotos enviadas vão para `.tmp/uploads` e o HTTPS usa um certificado próprio em `.tmp/certificado`.

## Organização

| Arquivo | Módulo da Seção 4 | Casos |
|---|---|---|
| `cypress/e2e/01-autenticacao.cy.js` | Autenticação | CT-01 a CT-07 |
| `cypress/e2e/02-controle-acesso.cy.js` | Controle de acesso e segurança | CT-08 a CT-14 |
| `cypress/e2e/03-cadastros.cy.js` | Cadastros (alunos, professores, turmas) | CT-15 a CT-29 |
| `cypress/e2e/04-horarios.cy.js` | Horários das turmas | CT-30 a CT-34 |
| `cypress/e2e/05-regras-presenca.cy.js` | Regras de presença (totem) | CT-35 a CT-46 |
| `cypress/e2e/06-chamada-professor.cy.js` | Chamada do professor | CT-47 a CT-55 |
| `cypress/e2e/07-area-aluno.cy.js` | Área do aluno e justificativas | CT-56 a CT-62 |
| `cypress/e2e/08-painel-relatorios.cy.js` | Painel e relatórios | CT-63 a CT-65 |
| `cypress/e2e/09-reconhecimento-facial.cy.js` | Reconhecimento facial e prova de vida | CT-78 a CT-81 |
| `cypress/e2e/10-reconhecimento-rodada2.cy.js` | Reconhecimento, rodada 2 | CT-82 e CT-83 |
| `cypress/e2e/11-totem.cy.js` | Totem: ativação e liberação | CT-66 a CT-77 |

- `cypress/support/commands.js`: comandos reutilizados (`cy.entrar`, `cy.postarFormulario`, `cy.criarTotem`,
  `cy.ativarTotem`, `cy.enviarFrames`...).
- `cypress/fixtures/usuarios.json`: contas usadas nos testes (senhas que só existem na cópia do banco).
- `apoio/ponte.py`: `cy.task('ponte')`. Prepara a massa de dados, consulta o banco de teste e chama as regras de
  presença com um horário escolhido (ex.: "o aluno passou no totem às 07:08 de 02/11/2026").
- `apoio/servidor_teste.py`: sobe o FrequencyON para os testes.

Os casos do totem (`11-totem.cy.js`) rodam por último: o CT-74 testa o bloqueio por senha errada e deixa a
liberação por senha bloqueada por 15 minutos naquele servidor. Como os servidores são criados de novo a cada
`npm test`, isso não afeta a próxima execução.
