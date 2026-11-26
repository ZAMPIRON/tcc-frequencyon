<div align="center">

# FrequencyON

**A chamada que se faz sozinha.**
Registro de presença por reconhecimento facial para escolas, com painéis que apontam os alunos em risco de evasão antes que seja tarde.

![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.1-000000?logo=flask&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-4-5C3EE8?logo=opencv&logoColor=white)
![dlib](https://img.shields.io/badge/face__recognition-dlib-0A7BBB)
![Status](https://img.shields.io/badge/fase-MVP-a26bff)

![Página inicial do FrequencyON](docs/manual/01-pagina-inicial.png)

</div>

---

## Sumário

1. [Visão geral](#1-visão-geral)
2. [Perfis de usuário](#2-perfis-de-usuário)
3. [Manual de uso (com telas)](#3-manual-de-uso)
4. [Arquitetura e funcionamento](#4-arquitetura-e-funcionamento)
5. [Regras de frequência](#5-regras-de-frequência)
6. [Tecnologias](#6-tecnologias)
7. [Instalação e execução](#7-instalação-e-execução)
8. [Configuração (variáveis de ambiente)](#8-configuração)
9. [API REST](#9-api-rest)
10. [Tarefas em segundo plano](#10-tarefas-em-segundo-plano)
11. [Estrutura do projeto](#11-estrutura-do-projeto)
12. [Privacidade e segurança](#12-privacidade-e-segurança)
13. [Próximos passos](#13-próximos-passos)

---

## 1. Visão geral

A chamada feita à mão consome tempo de toda aula e a lista de papel raramente vira informação. Quando a escola percebe que um aluno parou de vir, muitas vezes ele já evadiu.

O FrequencyON resolve as duas pontas:

1. **Registrar**: o aluno passa em frente a um tablet na entrada (o **totem**) e a presença é lançada automaticamente. Sem crachá, sem lista, sem fila.
2. **Agir**: cada registro alimenta painéis para professores e coordenação, que destacam a frequência baixa por aluno, turma e curso, para a escola intervir cedo.

## 2. Perfis de usuário

| Perfil | O que faz no sistema |
|---|---|
| **Aluno** | Vê sua frequência, o histórico aula por aula, exporta em CSV e justifica faltas online. |
| **Professor** | Faz e corrige a chamada de cada aula com um clique, vê um calendário colorido pela frequência da turma e libera o totem todo dia. |
| **Administrador (coordenação)** | Cadastra alunos, professores, turmas, horários e totens; acompanha indicadores, relatórios, risco de evasão, auditoria e responde justificativas. |
| **Totem** | Tablet (ou qualquer aparelho com câmera) na entrada da escola, ativado pela coordenação e liberado por um professor. |

---

## 3. Manual de uso

### 3.1 Acesso

Na página inicial o usuário escolhe o perfil e entra com seu login.

| Aluno | Professor | Administrador |
|---|---|---|
| ![Login do aluno](docs/manual/02-login-aluno.png) | ![Login do professor](docs/manual/03-login-professor.png) | ![Login do administrador](docs/manual/04-login-administrador.png) |

- O **aluno** entra com a matrícula e a senha; **professor** e **administrador**, com e-mail e senha.
- Senha errada mostra um aviso na própria tela:

![Senha incorreta](docs/manual/05-login-senha-incorreta.png)

### 3.2 Administrador

#### Painel
Indicadores gerais (alunos, professores, turmas e frequência geral) e atalhos para as demais áreas.

![Painel do administrador](docs/manual/06-admin-painel.png)

#### Alunos
Lista de alunos com busca, cadastro, edição e exclusão. No cadastro pode ser enviada uma foto, usada para gerar o rosto do aluno.

| Lista | Cadastro | Detalhes |
|---|---|---|
| ![Alunos](docs/manual/07-admin-alunos.png) | ![Cadastrar aluno](docs/manual/08-admin-cadastrar-aluno.png) | ![Detalhes do aluno](docs/manual/09-admin-detalhes-do-aluno.png) |

A tela de detalhes mostra a frequência do aluno, o histórico e permite exportar os dados.

#### Professores
Cadastro de professores (nome, e-mail, departamento, senha). O rosto do professor também pode ser cadastrado, para que ele libere o totem só olhando para a câmera.

| Lista | Cadastro |
|---|---|
| ![Professores](docs/manual/10-admin-professores.png) | ![Cadastrar professor](docs/manual/11-admin-cadastrar-professor.png) |

#### Turmas
Cada turma tem um curso, um **modelo de horário** (*Admin → Horários*) e um ou mais professores. Cada professor tem **seus próprios dias da semana** na turma (ex.: Matemática ter/qui, Inglês qua/sex); os dias letivos da turma são a união dos dias dos professores.

| Lista | Nova turma |
|---|---|
| ![Turmas](docs/manual/12-admin-turmas.png) | ![Nova turma](docs/manual/13-admin-nova-turma.png) |

| Detalhes da turma | Vincular professor | Adicionar aluno |
|---|---|---|
| ![Detalhes da turma](docs/manual/14-admin-detalhes-da-turma.png) | ![Vincular professor](docs/manual/15-admin-vincular-professor.png) | ![Adicionar aluno na turma](docs/manual/16-admin-adicionar-aluno-na-turma.png) |

#### Horários
Modelos de grade por turma, por exemplo CAI com 4 aulas de 60 min ou cursos técnicos com 10 aulas de 45 min. Cada aula tem início, fim e período (manhã, tarde, noite). Cada modelo define também a tolerância de *presente*, de *atraso* e com quanta antecedência o totem abre.

![Horários](docs/manual/17-admin-horarios.png)

#### Relatórios
Tendência mensal de frequência, frequência por curso e por professor, com qualquer intervalo de datas e exportação em **Excel** e **PDF**. Também há um botão para fazer **backup do banco** na hora.

![Relatórios](docs/manual/18-admin-relatorios.png)

#### Risco de evasão
Todos os alunos abaixo de 75% de frequência em uma lista. Daqui a coordenação pode **enviar os alertas por e-mail** aos alunos com frequência baixa.

![Risco de evasão](docs/manual/19-admin-risco-de-evasao.png)

#### Totens
Cadastro dos tablets autorizados. Ao criar um totem, o sistema gera um **código de ativação de 8 letras** (válido por 24 h e de uso único), que é digitado uma vez no tablet. A tabela mostra se cada aparelho está aguardando ativação, liberado hoje (e por quem) ou bloqueado, o último uso e um aviso de **sem sinal** quando um totem liberado para de enviar imagens. O botão da chave gera um código novo (para trocar o tablet). Um tablet perdido ou trocado pode ser desativado a qualquer momento.

![Totens](docs/manual/20-admin-totens.png)

#### Justificativas e auditoria
- As justificativas enviadas pelos alunos aparecem no painel para **aceitar ou recusar**; a coordenação recebe um e-mail a cada nova justificativa.
- *Admin → Auditoria* mostra toda alteração feita no painel e toda mudança manual na chamada, com quem fez, quando e se foi usada a senha do administrador.

![Auditoria](docs/manual/21-admin-auditoria.png)

### 3.3 Professor

- Calendário do mês: os dias com aula são clicáveis e coloridos pela frequência da turma naquele dia (≥ 75%, 50–74%, < 50%, sem chamada).
- Uma barra por aula, agrupada por período: **clique** alterna presente/falta, **botão direito** marca atraso.
- Os alunos que passaram pelo totem já aparecem com presença lançada.

![Chamada do dia](docs/manual/22-professor-chamada-do-dia.png)

A chamada de **hoje** pode ser editada livremente. Dias anteriores ficam **somente leitura**; para alterar, é preciso informar a senha de um administrador.

| Dia anterior (somente leitura) | Alterar dia anterior |
|---|---|
| ![Dia anterior](docs/manual/23-professor-dia-anterior.png) | ![Alterar dia anterior](docs/manual/24-professor-alterar-dia-anterior.png) |

### 3.4 Aluno

- Anel de frequência com situação *Regular*, *Atenção* ou *Crítico*.
- Histórico de todos os dias letivos com todas as aulas, com filtro por faltas ou atrasos.
- **Exportar em CSV** (abre no Excel).
- Aviso no portal quando a frequência se aproxima do mínimo.

![Minha frequência](docs/manual/25-aluno-minha-frequencia.png)

Para **justificar uma falta**, o aluno escolhe o dia, escreve o motivo e acompanha a situação (pendente, aceita, recusada).

![Justificar falta](docs/manual/26-aluno-justificar-falta.png)

### 3.5 Totem

O totem é a página `/totem` aberta em modo quiosque num tablet. A câmera é a do próprio tablet; ele envia algumas imagens por segundo ao servidor, que faz o reconhecimento.

1. **Ativação (uma vez)**: no tablet, digite o código gerado em *Admin → Totens*.

![Ativar totem](docs/manual/27-totem-ativar.png)

2. **Liberação (todo dia)**: o totem começa bloqueado. Quando um professor chega, ele olha para a câmera (se tiver o rosto cadastrado) ou digita e-mail e senha. O totem fica liberado até **23:59** e se bloqueia sozinho à meia-noite. Qualquer professor libera qualquer totem.

![Totem bloqueado](docs/manual/28-totem-bloqueado.png)

3. **Registro**: o aluno se posiciona no centro da câmera. O sistema confere a **prova de vida** (pequenos movimentos naturais de olhos e boca, para recusar foto impressa) e registra a presença, com confete e som de confirmação. Há estados próprios para *atrasado*, *fora do horário* e *hoje não tem aula*.

| Aguardando aluno | Verificando prova de vida | Presença confirmada |
|---|---|---|
| ![Aguardando aluno](docs/manual/29-totem-aguardando-aluno.png) | ![Verificando](docs/manual/30-totem-verificando.png) | ![Presença confirmada](docs/manual/31-totem-presenca-confirmada.png) |

4. **Primeiro acesso / cadastrar face**: o aluno digita a matrícula **e a senha** no totem e o sistema captura e grava o rosto dele. Cinco senhas erradas bloqueiam aquela matrícula por 15 minutos.

![Cadastrar rosto](docs/manual/32-totem-cadastrar-rosto.png)

**Totens universais**: qualquer totem registra qualquer aluno, na turma dele, independente da sala em que a turma está hoje (as salas mudam demais para manter no sistema).

**Fila offline**: se a rede cair, o tablet guarda as imagens (só quando há movimento) no navegador e as envia quando a conexão volta; o servidor reconhece cada uma com o horário em que foi tirada.

### 3.6 E-mails

O sistema envia e-mails (quando o SMTP está configurado) para:
- nova justificativa de falta (para `EMAIL_JUSTIFICATIVAS`);
- aluno com frequência baixa (no máximo uma vez por semana por aluno) e resumo para a coordenação;
- totem liberado que parou de enviar imagens durante a aula.

| Justificativa de falta | Alerta de frequência baixa |
|---|---|
| ![E-mail de justificativa](docs/manual/33-email-de-justificativa.png) | ![E-mail de alerta de frequência](docs/manual/34-email-alerta-de-frequencia.png) |

---

## 4. Arquitetura e funcionamento

```mermaid
flowchart LR
    TAB[Tablet do totem<br/>câmera do navegador] -->|frames JPEG| API[Rotas do totem<br/>Flask]
    API --> FS[face_service.py<br/>OpenCV + face_recognition]
    FS -->|encoding 128-d + prova de vida| DB[(SQLite<br/>SQLAlchemy)]
    API -->|eventos| TAB
    DB --> APP[App Flask]
    APP --> P[Área do professor]
    APP --> A[Painel da coordenação]
    APP --> S[Página do aluno]
    APP --> R[API REST /api/v1]
    BG[tarefas.py<br/>segundo plano] --> DB
    BG -->|SMTP| MAIL[E-mails]
```

1. O tablet envia frames ao servidor. Um processo separado (`face_service.py`) detecta rostos com o detector **HOG** do dlib e transforma cada rosto em um vetor de **128 números** (encoding).
2. O encoding é comparado com o de todos os alunos cadastrados pela **distância euclidiana**. É aceito com distância ≤ **0,50** em **2 frames seguidos**. O mesmo aluno não é processado de novo por **8 segundos**.
3. **Prova de vida**: o aluno precisa piscar. Os olhos têm que estar abertos, fechar (a abertura cai pelo menos `VARIACAO_VIVO`, 30%) e abrir de novo. O totem já pede "Pisque os olhos" enquanto calcula o encoding. Uma foto impressa, parada ou tremendo na mão, varia só 10-20% por ruído e é recusada.
4. O reconhecimento grava um registro por aula do período atual (`presente` / `atraso` / `falta`) para o aluno e o dia, e devolve um evento que a tela do totem mostra.
5. Professor, aluno e coordenação leem os mesmos registros, então todas as telas mostram os mesmos números.

O reconhecimento roda **no próprio servidor da escola**; nenhuma imagem é enviada para serviços externos.

## 5. Regras de frequência

- O aluno registra presença **uma vez por período** (manhã, tarde, noite): de novo depois do almoço. Quem sai no almoço e não volta fica com falta nas aulas da tarde.
- O totem abre **30 min** antes do início do período (configurável por horário).
- Aulas do período que já terminaram ficam como **falta**. A aula é **presente** até o seu início e **atraso** até 5 min depois (configurável); depois disso é falta só naquela aula.
- Só contam presenças nos **dias da semana da turma**.
- **Frequência** = aulas assistidas (presente + atraso) ÷ (dias letivos com chamada na turma × aulas do horário da turma).
- Abaixo de **75%** o aluno entra na lista de risco de evasão; abaixo de `ALERTA_FREQUENCIA` (80%) recebe aviso no portal e por e-mail.
- Fuso horário da escola: `America/Sao_Paulo`.

## 6. Tecnologias

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.14, Flask 3.1, Flask-SQLAlchemy 3.1, Flask-WTF (CSRF) |
| Banco de dados | SQLite (qualquer URL do SQLAlchemy via `DATABASE_URL`) |
| Visão computacional | OpenCV, `face_recognition` (dlib, modelo HOG) |
| Relatórios | openpyxl (Excel), ReportLab (PDF) |
| HTTPS | `cryptography` (CA local gerada pelo próprio sistema) |
| Frontend | Templates Jinja, Bootstrap 5.3, JavaScript puro, Chart.js 4 |

## 7. Instalação e execução

### Requisitos
- Python **3.14**
- Uma câmera: a do tablet do totem (padrão) ou uma webcam no servidor (modo `camera`). O resto do sistema funciona sem câmera.
- No Windows, o repositório já inclui um `dlib` pré-compilado.

### Instalação

```bash
git clone https://github.com/ZAMPIRON/tcc-frequencyon.git
cd tcc-frequencyon

python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

# Somente no Windows: instale antes o dlib incluído
pip install dlib-20.0.99-cp314-cp314-win_amd64.whl

pip install -r requirements.txt
```

### Execução

```bash
python app.py
```

Acesse **https://localhost:5443**. O totem fica em **https://localhost:5443/totem**. O endereço antigo (`http://localhost:5000`) continua funcionando e redireciona para HTTPS. O terminal também mostra o endereço para outros aparelhos da rede (ex.: `https://192.168.0.113:5443`).

Na primeira execução o banco é criado em `instance/frequencyon.db` com um administrador. O login é `ADMIN_EMAIL` (padrão `admin@frequencyon.com`) e a senha é `ADMIN_SENHA`; se ela não estiver definida, uma senha aleatória é mostrada **uma única vez** no terminal.

Para trocar qualquer senha depois (administrador, professor ou aluno):

```bash
python trocar_senha.py <e-mail ou matrícula>
```

Ao iniciar, o servidor avisa no terminal quais contas ainda usam senha padrão ou fraca.

### HTTPS

O sistema roda em HTTPS por padrão (a câmera do navegador só funciona em conexão segura). Na primeira execução ele cria em `instance/` (nunca vai para o Git):

- uma **autoridade certificadora local** (`ca-frequencyon.pem`), restrita a `localhost`, ao nome deste computador e a IPs de rede privada, para que a chave não sirva para se passar por outros sites;
- o **certificado do servidor**, renovado sozinho quando vence ou quando o IP da máquina muda.

Enquanto a CA não for instalada, o navegador mostra o aviso de "não seguro". Instale **uma vez em cada aparelho** que acessa o sistema:

- **Windows (Chrome/Edge):** em um terminal como administrador, `certutil -addstore -f Root instance\ca-frequencyon.pem`
- **Android:** copie o arquivo para o aparelho → *Configurações → Segurança → Criptografia e credenciais → Instalar certificado → Certificado de CA*
- **Firefox:** *Configurações → Privacidade e Segurança → Certificados → Ver certificados → Autoridades → Importar*

Com um certificado real (ex.: domínio público), defina `SSL_CERT` e `SSL_KEY`; nesse caso o HSTS também é ativado.

### Dados de demonstração (opcional)

```bash
python seed.py
```

> **ATENÇÃO:** o `seed.py` **apaga todos os dados** (alunos, turmas, presenças, justificativas) antes de criar um administrador, um professor, uma turma (ter/qui) e três alunos. Todas as contas de demonstração usam a senha `SENHA_DEMO` (ou uma aleatória mostrada no final). Use apenas em um banco de demonstração.

## 8. Configuração

Todas as configurações são variáveis de ambiente. Elas também podem ficar em um arquivo `.env` na raiz do projeto (uma por linha, `NOME=valor`), que é ignorado pelo Git.

| Variável | Padrão | Para que serve |
|---|---|---|
| `SECRET_KEY` | *(gerada)* | Chave de sessão do Flask. Se não existir, uma aleatória é criada em `instance/secret_key`. |
| `ADMIN_EMAIL` / `ADMIN_SENHA` | `admin@frequencyon.com` / *(aleatória)* | Primeiro administrador, criado só com o banco vazio. |
| `SENHA_DEMO` | *(aleatória)* | Senha das contas criadas pelo `seed.py`. |
| `DATABASE_URL` | `sqlite:///frequencyon.db` | Qualquer URL de banco do SQLAlchemy. |
| `TOTEM_FONTE` | `tablet` | `tablet` usa a câmera do aparelho que abre `/totem`; `camera` usa uma webcam ligada ao servidor (desenvolvimento). |
| `TOTEM_CAMERA` | `0` | Índice da webcam do servidor (só no modo `camera`). |
| `PROVA_DE_VIDA` | `1` | `0` desliga a prova de vida (só para testes). |
| `VARIACAO_VIVO` | `0.30` | Quanto a abertura dos olhos precisa cair (piscada) para o rosto contar como vivo. |
| `FACE_TRABALHADORES` | `2` | Processos auxiliares que calculam os encodings (a parte lenta) sem travar a detecção. |
| `HTTPS` | `1` | `0` desliga o HTTPS e serve HTTP puro em `PORTA` (só para testes locais). |
| `PORTA_HTTPS` / `PORTA` | `5443` / `5000` | Porta HTTPS e porta HTTP que redireciona para ela. |
| `SSL_CERT` / `SSL_KEY` | *(CA local)* | Caminhos de um certificado e chave reais. |
| `TOLERANCIA_PRESENTE` / `TOLERANCIA_ATRASO` / `ANTECEDENCIA_TOTEM` | `0` / `5` / `30` | Valores iniciais de um novo horário (minutos de *presente*, de *atraso* e de antecedência do totem). Cada horário edita os seus em *Admin → Horários*. |
| `ALERTA_FREQUENCIA` | `80` | Abaixo disso o aluno vê um aviso no portal e recebe e-mail (no máximo uma vez por semana). |
| `FREQUENCYON_API_TOKEN` | *(vazio)* | Token da API REST. Vazio = API desligada. |
| `TOTEM_SEM_SINAL` | `10` | Minutos sem imagens para um totem liberado contar como fora do ar. |
| `BACKUPS_GUARDADOS` | `30` | Quantos backups diários manter em `instance/backups`. |
| `FREQUENCYON_DATA` | *(vazio)* | Congela "hoje" em uma data (`AAAA-MM-DD`), para testes. |
| `EMAIL_JUSTIFICATIVAS` | *(vazio)* | Endereço que recebe os e-mails de justificativa e de totem fora do ar. |
| `SMTP_SERVIDOR` / `SMTP_PORTA` | `smtp.gmail.com` / `465` | Servidor SMTP (465 = SSL, 587 = STARTTLS). |
| `SMTP_USUARIO` / `SMTP_SENHA` | *(vazio)* | Conta remetente. No Gmail, use uma senha de app. |

## 9. API REST

API **somente leitura** para integrar com o sistema de gestão da escola. Autenticação pelo cabeçalho `Authorization: Bearer <FREQUENCYON_API_TOKEN>`. Nunca devolve senha, foto ou dados biométricos.

| Método | Rota | Retorno |
|---|---|---|
| GET | `/api/v1/turmas` | Turmas |
| GET | `/api/v1/alunos` | Alunos |
| GET | `/api/v1/frequencia?inicio=AAAA-MM-DD&fim=AAAA-MM-DD` | Frequência no período |
| GET | `/api/v1/alunos/<id>/presencas` | Presenças de um aluno |
| GET | `/api/v1/saude` | Situação do banco, do reconhecimento e dos totens (HTTP 503 se algo estiver fora do ar) |

## 10. Tarefas em segundo plano

O arquivo `tarefas.py` roda junto com o servidor e cuida de:

- **Alertas de frequência**: e-mail para alunos abaixo de `ALERTA_FREQUENCIA` (no máximo um a cada 7 dias) e resumo para a coordenação.
- **Backup diário** do banco em `instance/backups`, mantendo os últimos `BACKUPS_GUARDADOS`.
- **Totem sem sinal**: e-mail quando um totem liberado para de enviar imagens durante a aula.

## 11. Estrutura do projeto

```
.
├── app.py                  # Ponto de entrada: create_app() e início do servidor
├── certificado.py          # CA local e certificado HTTPS
├── database.py             # Modelos, regras de presença e horários
├── email_service.py        # Leitura do .env e envio de e-mails
├── face_service.py         # Reconhecimento facial e prova de vida
├── tarefas.py              # Alertas, backup e monitoramento dos totens
├── trocar_senha.py         # Troca de senha pela linha de comando
├── seed.py                 # Dados de demonstração (apaga o banco!)
├── requirements.txt
├── rotas/                  # Rotas, um arquivo por área
│   ├── comum.py            # Login obrigatório, upload de foto, acesso do totem
│   ├── login.py            # Página inicial, logins e logout
│   ├── admin.py            # Alunos, professores, turmas, horários, totens, justificativas
│   ├── relatorios.py       # Relatórios, Excel e PDF
│   ├── auditoria.py        # Trilha de auditoria
│   ├── professor.py        # Chamada e calendário do professor
│   ├── aluno.py            # Página do aluno, CSV e justificativa
│   ├── totem.py            # Ativação, liberação, frames, fila offline e cadastro de rosto
│   └── api.py              # API REST e verificação de saúde
├── static/
│   ├── css/                # tema.css (design system claro/escuro) e um arquivo por área
│   ├── js/                 # efeitos.js, totem.js, reconhecimento.js, sincronizacao.js (fila offline)...
│   ├── assets/             # Logo e imagens
│   ├── manifest-totem.json # Manifesto para instalar o totem como app no tablet
│   └── uploads/            # Fotos de alunos e professores (fora do Git)
├── templates/
│   ├── componentes/        # <head>, scripts e trechos compartilhados
│   ├── admin/  professor/  aluno/  totem/
│   ├── base_login.html     # Base das telas de login
│   └── index.html          # Página inicial
└── docs/
    ├── manual/             # Capturas de tela usadas neste README
    └── Termo_Consentimento_LGPD_FrequencyON.docx
```

## 12. Privacidade e segurança

O FrequencyON trata **dados biométricos de alunos, muitos deles menores de idade**. Pela LGPD, dado biométrico é dado sensível; por isso o modo de tratá-lo importa tanto quanto as funcionalidades. O repositório inclui um modelo de **termo de consentimento** em `docs/`.

**Como funciona hoje:**
- Os rostos são guardados como vetores numéricos (128 números por pessoa) no banco. O reconhecimento roda no computador da escola, sem enviar imagens a terceiros.
- Banco, fotos e chave secreta **não** vão para o Git (`instance/`, `static/uploads/` e `.env` estão no `.gitignore`).
- Tráfego criptografado com HTTPS (TLS 1.3); o HTTP só redireciona. Todos os formulários e `POST` em JavaScript têm proteção CSRF (Flask-WTF). Cookies de sessão `Secure`, `HttpOnly` e `SameSite=Lax`.
- Prova de vida passiva contra foto impressa.
- As fotos de `static/uploads/` só abrem para usuários logados ou para um totem ativado (dado biométrico).
- Recadastrar o rosto no totem exige a senha do aluno; 5 senhas erradas bloqueiam a matrícula por 15 minutos.
- O tablet só vira totem com um código de ativação de uso único; o banco guarda apenas o hash do token.
- Toda alteração no painel e na chamada fica registrada na auditoria.

**Antes de usar com alunos reais, no mínimo:**
- [ ] Trocar todas as senhas padrão (`python trocar_senha.py ...`); o terminal lista as que ainda são fracas.
- [ ] Coletar o consentimento de alunos e responsáveis, com política de retenção e exclusão dos dados faciais.

## 13. Próximos passos

- **Produto:** interface em inglês e espanhol, avisos para os responsáveis quando a frequência cai, relatórios prontos para secretarias de educação.
- **Plataforma:** várias escolas na mesma instalação (multi-tenant), PostgreSQL, implantação com Docker.
- **Visão computacional:** anti-spoofing mais robusto (ex.: detecção de tela/vídeo).
- **Integrações:** exportação para sistemas de gestão escolar e plataformas de ensino.

## Equipe

Desenvolvido por **Gustavo Lopes Zampiron** como Trabalho de Conclusão de Curso (TCC).

## Licença

Ainda não foi escolhida uma licença; todos os direitos são reservados aos autores. Entre em contato antes de usar ou redistribuir este código.
