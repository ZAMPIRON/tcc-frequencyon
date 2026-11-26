// Comandos reutilizados pelos casos de teste.
import usuarios from '../fixtures/usuarios.json';

// Ponte com o banco de teste e com as regras do sistema (apoio/ponte.py).
Cypress.Commands.add('ponte', (acao, dados = {}) => cy.task('ponte', { acao, ...dados }, { timeout: 180000, log: false }));

// Guarda um valor medido no caso (resultados/medicoes.json).
Cypress.Commands.add('medicao', (caso, dados) => cy.task('medicao', { caso, ...dados }, { log: false }));

// Login pela tela, guardado com cy.session para não repetir em todo caso.
Cypress.Commands.add('entrar', (usuario) => {
  cy.session(['login', usuario.tipo, usuario.login], () => {
    cy.visit(`/login/${usuario.tipo}`);
    cy.get('#email').type(usuario.login);
    cy.get('#senhaInput').type(usuario.senha, { log: false });
    cy.contains('button', 'Entrar').click();
    cy.location('pathname').should('eq', usuario.destino);
  }, {
    validate() {
      cy.request({ url: usuario.destino, followRedirect: false }).its('status').should('eq', 200);
    },
  });
});

// Token CSRF da sessão atual (lido de um formulário do próprio sistema).
Cypress.Commands.add('csrf', () => cy.request('/login/admin').its('body')
  .then((html) => html.match(/name="csrf_token" value="([^"]+)"/)[1]));

// Em HTTPS o Flask-WTF também confere o Referer (como o navegador manda); o cy.request não manda sozinho.
const referer = () => ({ Referer: `${Cypress.config('baseUrl')}/` });

// POST de formulário como o navegador faria (com o token CSRF da sessão).
Cypress.Commands.add('postarFormulario', (url, campos, opcoes = {}) => cy.csrf().then((token) => cy.request({
  method: 'POST', url, form: true, body: { csrf_token: token, ...campos }, headers: referer(),
  failOnStatusCode: false, ...opcoes,
})));

// POST JSON como o JavaScript das telas faz (cabeçalho X-CSRFToken).
Cypress.Commands.add('postarJson', (url, corpo, opcoes = {}) => cy.csrf().then((token) => cy.request({
  method: 'POST', url, body: corpo, headers: { 'X-CSRFToken': token, ...referer() }, failOnStatusCode: false, ...opcoes,
})));

// Mensagem do sistema (os avisos do painel viram "toast" no canto da tela).
Cypress.Commands.add('mensagem', (texto) => cy.contains('.fo-toast, .alert', texto));

// Totem: o cookie do aparelho é guardado entre os casos, como no tablet de verdade.
const totens = {};
Cypress.Commands.add('guardarTotem', (apelido) => cy.getCookie('totem_token').should('exist')
  .then((c) => { totens[apelido] = c.value; }));

Cypress.Commands.add('usarTotem', (apelido) => cy.setCookie('totem_token', totens[apelido], {
  httpOnly: true, secure: true, sameSite: 'strict',
}));

// Coordenação cria o totem no painel e devolve o código de ativação mostrado na tela.
Cypress.Commands.add('criarTotem', (nome) => {
  cy.entrar(usuarios.admin);
  cy.visit('/admin/totens');
  cy.contains('button', 'Novo totem').click();
  cy.get('#modalTotem input[name="nome"]').should('be.visible').type(nome);
  cy.contains('#modalTotem button', 'Criar e gerar código').click();
  cy.contains(`Código de ativação do "${nome}"`).should('be.visible');
  return cy.get('span.font-monospace.fs-2').invoke('text').then((t) => t.trim());
});

// Tablet novo (sem cookies) digita o código de ativação.
Cypress.Commands.add('ativarTotem', (codigo) => {
  cy.clearAllCookies();
  cy.visit('/totem');
  cy.get('#codigo').type(codigo);
  cy.contains('button', 'Ativar').click();
});

// Totem bloqueado: professor libera com e-mail e senha (plano B da tela).
Cypress.Commands.add('liberarTotemComSenha', (usuario) => {
  cy.visit('/totem');
  cy.get('details').then(($d) => { if (!$d.prop('open')) cy.wrap($d).find('summary').click(); });
  cy.get('#email').clear().type(usuario.login);
  cy.get('#senha').type(usuario.senha, { log: false });
  cy.contains('button', 'Liberar até o fim do dia').click();
});

// Envia imagens JPEG ao totem como o tablet faz (fetch do próprio navegador, com cookie e token CSRF).
// Devolve as respostas de cada envio, com o tempo (ms) desde o primeiro envio.
Cypress.Commands.add('enviarFrames', ({ url, base64, duracaoMs, intervaloMs = 200, pararQuando }) => {
  cy.csrf().then((token) => cy.window().then({ timeout: duracaoMs + 30000 }, async (win) => {
    const bytes = win.Uint8Array.from(win.atob(base64), (c) => c.charCodeAt(0));
    const respostas = [];
    const inicio = win.performance.now();
    while (win.performance.now() - inicio < duracaoMs) {
      const res = await win.fetch(url, {
        method: 'POST', body: bytes, credentials: 'same-origin',
        headers: { 'Content-Type': 'image/jpeg', 'X-CSRFToken': token },
      });
      const corpo = await res.json().catch(() => ({}));
      respostas.push({ status: res.status, ms: Math.round(win.performance.now() - inicio), ...corpo });
      if (pararQuando && pararQuando(corpo)) break;
      await new Promise((r) => win.setTimeout(r, intervaloMs));
    }
    return respostas;
  }));
});
