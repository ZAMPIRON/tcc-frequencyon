// Seção 4 — Módulo: Controle de acesso e segurança (CT-08 a CT-14)
import usuarios from '../fixtures/usuarios.json';

describe('Controle de acesso e segurança', () => {
  it('CT-08 [RNF01] Visitante sem login tenta abrir o painel do admin', () => {
    cy.request({ url: '/admin/dashboard', followRedirect: false }).then((res) => {
      expect(res.status).to.eq(302);
      expect(res.redirectedToUrl).to.match(/\/login\/admin$/);
    });
    cy.visit('/admin/dashboard');
    cy.location('pathname').should('eq', '/login/admin');
  });

  it('CT-09 [RNF01] Professor tenta abrir páginas do admin', () => {
    cy.entrar(usuarios.professor);
    ['/admin/alunos', '/admin/totens'].forEach((url) => {
      cy.request({ url, followRedirect: false }).then((res) => {
        expect(res.status, url).to.eq(302);
        expect(res.redirectedToUrl).to.match(/\/login\/admin$/);
      });
    });
  });

  it('CT-10 [RNF01] Aluno tenta abrir a chamada do professor', () => {
    cy.entrar(usuarios.aluno);
    cy.request({ url: '/professor/chamada', followRedirect: false }).then((res) => {
      expect(res.status).to.eq(302);
      expect(res.redirectedToUrl).to.match(/\/login\/professor$/);
    });
  });

  it('CT-11 [RNF01] Formulário enviado sem token CSRF', () => {
    cy.entrar(usuarios.admin);
    cy.request({ method: 'POST', url: '/admin/turmas', form: true, followRedirect: false, failOnStatusCode: false,
      body: { nome: 'CSRF', curso: 'Sem Token' } }).its('status').should('eq', 302);
    cy.ponte('turma', { nome: 'CSRF' }).its('existe').should('eq', false);
  });

  it('CT-12 [RNF01] Cookie de sessão protegido', () => {
    cy.visit('/login/admin');
    cy.get('#email').type(usuarios.admin.login);
    cy.get('#senhaInput').type(usuarios.admin.senha, { log: false });
    cy.contains('button', 'Entrar').click();
    cy.location('pathname').should('eq', '/admin/dashboard');
    cy.getCookie('session').then((c) => {
      expect(c, 'cookie de sessão').to.exist;
      expect(c.httpOnly, 'HttpOnly').to.eq(true);
      expect(c.secure, 'Secure (só HTTPS)').to.eq(true);
      expect(c.sameSite, 'SameSite').to.eq('lax');
    });
  });

  it('CT-13 [RNF07] Foto do rosto do aluno sem login', () => {
    cy.ponte('foto', { matricula: usuarios.aluno.login }).then(({ url }) => {
      cy.clearAllCookies();
      cy.request({ url, failOnStatusCode: false }).its('status').should('eq', 404);
      // controle: a mesma foto abre para quem está logado (o arquivo existe)
      cy.entrar(usuarios.admin);
      cy.request(url).then((res) => {
        expect(res.status).to.eq(200);
        expect(res.headers['content-type']).to.contain('image/');
      });
    });
  });

  it('CT-14 [RNF01] Senha guardada com hash', () => {
    cy.ponte('senha_hash', { email: usuarios.admin.login }).its('hash').then((hash) => {
      expect(hash).to.match(/^(scrypt|pbkdf2):/);
      expect(hash).not.to.contain(usuarios.admin.senha);
    });
  });
});
