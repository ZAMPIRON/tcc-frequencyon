// Seção 4 — Módulo: Autenticação (CT-01 a CT-07)
import usuarios from '../fixtures/usuarios.json';

function preencherLogin(tipo, login, senha) {
  cy.visit(`/login/${tipo}`);
  if (login) cy.get('#email').type(login);
  if (senha) cy.get('#senhaInput').type(senha, { log: false });
  cy.contains('button', 'Entrar').click();
}

describe('Autenticação', () => {
  it('CT-01 [RF10] Login de administrador com credenciais válidas', () => {
    preencherLogin('admin', usuarios.admin.login, usuarios.admin.senha);
    cy.location('pathname').should('eq', '/admin/dashboard');
    cy.contains('Painel').should('be.visible');
  });

  it('CT-02 [RF10] Login de professor com credenciais válidas', () => {
    preencherLogin('professor', usuarios.professor.login, usuarios.professor.senha);
    cy.location('pathname').should('eq', '/professor/chamada');
  });

  it('CT-03 [RF18] Login de aluno usando a matrícula', () => {
    preencherLogin('aluno', usuarios.aluno.login, usuarios.aluno.senha);
    cy.location('pathname').should('eq', '/aluno/');
    cy.contains('h1', usuarios.aluno.nome).should('be.visible');
  });

  it('CT-04 [RF10] Login com senha incorreta', () => {
    preencherLogin('admin', usuarios.admin.login, 'SenhaErrada#1');
    cy.location('pathname').should('eq', '/login/admin');
    cy.contains('.alert-danger', 'E-mail/matrícula ou senha inválidos').should('be.visible');
    cy.request({ url: '/admin/dashboard', followRedirect: false }).its('status').should('eq', 302);
  });

  it('CT-05 [RF10] Login com usuário e senha em branco', () => {
    // pela tela: o navegador não deixa enviar (campos obrigatórios)
    preencherLogin('admin', '', '');
    cy.location('pathname').should('eq', '/login/admin');
    cy.get('#email').then(($c) => expect($c[0].validity.valueMissing).to.eq(true));
    // direto no servidor (sem a validação do navegador): continua sem acesso
    cy.postarFormulario('/login/admin', { email: '', senha: '' }, { followRedirect: false }).then((res) => {
      expect(res.status).to.eq(200);
      expect(res.body).to.contain('E-mail/matrícula ou senha inválidos');
    });
    cy.request({ url: '/admin/dashboard', followRedirect: false }).its('status').should('eq', 302);
  });

  it('CT-06 [RNF01] Limite de tentativas de login (força bruta)', () => {
    const conta = usuarios.adminBloqueio;
    const status = [];
    const headers = { Referer: `${Cypress.config('baseUrl')}/` };   // o navegador manda; o cy.request não
    cy.csrf().then((token) => {
      Cypress._.times(30, () => {
        cy.request({ method: 'POST', url: '/login/admin', form: true, failOnStatusCode: false, followRedirect: false,
          headers, body: { csrf_token: token, email: conta.login, senha: 'errada' } }).then((r) => status.push(r.status));
      });
      // logo depois, a senha certa
      cy.request({ method: 'POST', url: '/login/admin', form: true, failOnStatusCode: false, followRedirect: false,
        headers, body: { csrf_token: token, email: conta.login, senha: conta.senha } }).as('certa');
    });
    cy.get('@certa').then((res) => {
      expect(status.slice(0, 10), '10 primeiras tentativas erradas').to.deep.eq(Array(10).fill(200));
      expect(status.slice(10), 'depois de 10 erros fica bloqueado').to.deep.eq(Array(20).fill(429));
      expect(res.status, 'senha certa durante o bloqueio').to.eq(429);
      expect(res.body).to.contain('Muitas tentativas erradas. Aguarde 15 minutos');
      cy.medicao('CT-06', { respostas_erradas: status, resposta_senha_certa: res.status });
    });
  });

  it('CT-07 [RF10] Logout encerra a sessão', () => {
    cy.entrar(usuarios.admin);
    cy.visit('/admin/dashboard');
    cy.get('a[title="Sair"]').click();
    cy.location('pathname').should('eq', '/');
    cy.visit('/admin/dashboard');
    cy.location('pathname').should('eq', '/login/admin');
  });
});
