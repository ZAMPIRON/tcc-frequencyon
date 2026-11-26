// Configuração da suíte Cypress do FrequencyON.
// Antes dos testes: copia o banco do projeto e cria a massa de teste (apoio/ponte.py preparar)
// e sobe dois servidores do sistema sobre essa cópia:
//   rodada 1 -> https://127.0.0.1:5055 (configuração normal, com prova de vida)
//   rodada 2 -> https://127.0.0.1:5056 (PROVA_DE_VIDA=0, só para medir a identificação com foto parada)
const { defineConfig } = require('cypress');
const { execFile, spawn, spawnSync } = require('child_process');
const fs = require('fs');
const https = require('https');
const path = require('path');

const RAIZ = __dirname;
const PROJETO = path.resolve(process.env.FREQUENCYON_DIR || path.join(RAIZ, '..'));
const PYTHON = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const TMP = path.join(RAIZ, '.tmp');
const PORTA = 5055;
const PORTA_RODADA2 = 5056;

const ambiente = {
  ...process.env,
  FREQUENCYON_DIR: PROJETO,
  BANCO_TESTE: path.join(TMP, 'frequencyon-teste.db'),
  PYTHONUTF8: '1',
  PYTHONWARNINGS: 'ignore',
};

// preparação da massa de dados: python apoio/ponte.py preparar (antes de os servidores subirem)
function preparar() {
  return new Promise((resolve, reject) => {
    execFile(PYTHON, [path.join(RAIZ, 'apoio', 'ponte.py'), 'preparar'],
      { env: ambiente, maxBuffer: 10 * 1024 * 1024, timeout: 180000 },
      (erro, stdout, stderr) => (erro ? reject(new Error(`preparação falhou: ${stderr || erro.message}`)) : resolve(stdout)))
      .stdin.end('{}');
  });
}

// cy.task('ponte', { acao, ...dados }): a ação roda dentro do servidor de teste da rodada 1
// (rota /__teste__/ponte/<acao>), no mesmo processo do site
function ponte(acao, dados = {}) {
  const corpo = Buffer.from(JSON.stringify(dados));
  return new Promise((resolve, reject) => {
    const req = https.request({
      host: '127.0.0.1', port: PORTA, path: `/__teste__/ponte/${acao}`, method: 'POST', rejectUnauthorized: false,
      headers: { 'Content-Type': 'application/json', 'Content-Length': corpo.length },
    }, (res) => {
      const partes = [];
      res.on('data', (p) => partes.push(p));
      res.on('end', () => {
        const resposta = JSON.parse(Buffer.concat(partes).toString('utf-8'));
        if (res.statusCode !== 200) return reject(new Error(`ponte ${acao} falhou:\n${resposta.erro}`));
        resolve(resposta);
      });
    });
    req.on('error', reject);
    req.end(corpo);
  });
}

const servidores = [];

function subirServidor(porta, extra) {
  const log = fs.openSync(path.join(TMP, `servidor-${porta}.log`), 'w');
  const processo = spawn(PYTHON, [path.join(RAIZ, 'apoio', 'servidor_teste.py'), String(porta)],
    { env: { ...ambiente, ...extra }, stdio: ['ignore', log, log], windowsHide: true });
  servidores.push(processo);
}

function derrubarServidores() {
  while (servidores.length) {
    const p = servidores.pop();
    // no Windows o taskkill /T leva junto os processos do reconhecimento facial
    if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(p.pid), '/T', '/F']);
    else p.kill();
  }
}

// pronto = o servidor respondeu (a rota de saúde pode dizer 503 "degradado", por exemplo
// quando a cópia do banco tem totens liberados hoje que não estão mandando imagens)
function esperarServidor(porta, limite = Date.now() + 120000) {
  return new Promise((resolve, reject) => {
    const tentar = () => {
      https.get({ host: '127.0.0.1', port: porta, path: '/api/v1/saude', rejectUnauthorized: false }, (res) => {
        res.resume();
        resolve();
      }).on('error', () => {
        if (Date.now() > limite) return reject(new Error(`servidor da porta ${porta} não subiu (veja .tmp/servidor-${porta}.log)`));
        setTimeout(tentar, 500);
      });
    };
    tentar();
  });
}

module.exports = defineConfig({
  e2e: {
    baseUrl: `https://127.0.0.1:${PORTA}`,
    specPattern: 'cypress/e2e/**/*.cy.js',
    viewportWidth: 1366,
    viewportHeight: 768,
    defaultCommandTimeout: 10000,
    video: false,
    screenshotOnRunFailure: true,
    async setupNodeEvents(on, config) {
      // valores medidos pelos casos (tempos, distâncias, respostas) para a evidência do relatório
      const arquivoMedicoes = path.join(RAIZ, 'resultados', 'medicoes.json');
      fs.mkdirSync(path.dirname(arquivoMedicoes), { recursive: true });
      fs.writeFileSync(arquivoMedicoes, '{}');
      on('task', {
        ponte: ({ acao, ...dados }) => ponte(acao, dados),
        medicao({ caso, ...dados }) {
          const medicoes = JSON.parse(fs.readFileSync(arquivoMedicoes, 'utf-8'));
          medicoes[caso] = { ...medicoes[caso], ...dados };
          fs.writeFileSync(arquivoMedicoes, JSON.stringify(medicoes, null, 2));
          return null;
        },
      });

      // resumo da execução em resultados/ (evidência para o relatório de testes)
      on('after:run', (resultados) => {
        derrubarServidores();
        if (!resultados || !resultados.runs) return;
        const casos = resultados.runs.flatMap((run) => run.tests.map((t) => ({
          arquivo: run.spec.relative,
          caso: t.title.join(' > '),
          estado: t.state,
          duracao_ms: t.attempts.reduce((s, a) => s + (a.duration || 0), 0) || t.duration,
          erro: t.displayError || null,
        })));
        fs.mkdirSync(path.join(RAIZ, 'resultados'), { recursive: true });
        fs.writeFileSync(path.join(RAIZ, 'resultados', 'resultado-execucao.json'), JSON.stringify({
          inicio: resultados.startedTestsAt,
          fim: resultados.endedTestsAt,
          navegador: `${resultados.browserName} ${resultados.browserVersion}`,
          cypress: resultados.cypressVersion,
          sistema: `${resultados.osName} ${resultados.osVersion}`,
          totais: {
            testes: resultados.totalTests, aprovados: resultados.totalPassed,
            falhas: resultados.totalFailed, pendentes: resultados.totalPending, pulados: resultados.totalSkipped,
          },
          casos,
        }, null, 2));
      });
      process.on('exit', derrubarServidores);

      fs.mkdirSync(TMP, { recursive: true });
      await preparar();
      subirServidor(PORTA, { PROVA_DE_VIDA: '1' });
      subirServidor(PORTA_RODADA2, { PROVA_DE_VIDA: '0' });
      await Promise.all([esperarServidor(PORTA), esperarServidor(PORTA_RODADA2)]);
      return config;
    },
  },
});
