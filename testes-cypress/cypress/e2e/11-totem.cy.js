// Seção 4 — Módulo: Totem, ativação e liberação (CT-66 a CT-77)
// Os casos seguem a vida de um totem e rodam nesta ordem. O CT-74 (bloqueio por senha errada)
// fica por último porque bloqueia a liberação por senha deste computador por 15 minutos.
import usuarios from '../fixtures/usuarios.json';

describe('Totem: ativação e liberação', () => {
  let codigoQA;

  it('CT-66 [Extra] Tablet sem ativação abre o totem', () => {
    cy.clearAllCookies();
    cy.visit('/totem');
    cy.contains('label', 'Código de ativação').should('be.visible');
    cy.get('#codigo').should('be.visible');
  });

  it('CT-67 [RNF01] Ativar com código inválido', () => {
    cy.intercept('POST', '/totem/ativar').as('ativar');
    cy.ativarTotem('AAAA BBBB');
    cy.wait('@ativar').its('response.statusCode').should('eq', 403);
    cy.contains('.alert-danger', 'Código inválido ou vencido').should('be.visible');
  });

  it('CT-68 [Extra] Coordenação cria o totem e o tablet ativa com o código', () => {
    cy.criarTotem('Totem QA').then((codigo) => {
      codigoQA = codigo;
      cy.intercept('POST', '/totem/ativar').as('ativar');
      cy.ativarTotem(codigo.toLowerCase());          // aceita em minúsculas
      cy.wait('@ativar').its('response.statusCode').should('eq', 302);
    });
    cy.contains('Totem bloqueado').should('be.visible');
    cy.guardarTotem('qa');
    cy.ponte('dispositivo', { nome: 'Totem QA' }).then((d) => {
      expect(d.ativado).to.eq(true);
      expect(d.liberado).to.eq(false);
    });
  });

  it('CT-69 [RNF01] Reusar o mesmo código em outro tablet', () => {
    cy.intercept('POST', '/totem/ativar').as('ativar');
    cy.ativarTotem(codigoQA);
    cy.wait('@ativar').its('response.statusCode').should('eq', 403);
    cy.contains('.alert-danger', 'Código inválido ou vencido').should('be.visible');
  });

  it('CT-70 [RNF01] Ativar com código vencido (mais de 24 h)', () => {
    cy.criarTotem('Totem Vencido').then((codigo) => {
      cy.ponte('vencer_codigo', { nome: 'Totem Vencido' });
      cy.intercept('POST', '/totem/ativar').as('ativar');
      cy.ativarTotem(codigo);
    });
    cy.wait('@ativar').its('response.statusCode').should('eq', 403);
    cy.ponte('dispositivo', { nome: 'Totem Vencido' }).its('ativado').should('eq', false);
  });

  it('CT-71 [RNF01] Totem bloqueado não registra presença', () => {
    cy.usarTotem('qa');
    cy.visit('/');
    cy.ponte('caminho_projeto', { partes: ['static', 'assets', 'logo.png'] })
      .then(({ caminho }) => cy.readFile(caminho, 'base64'))
      .then((b64) => cy.enviarFrames({ url: '/api/totem/frame', base64: b64, duracaoMs: 1, pararQuando: () => true }))
      .then(([res]) => {
        expect(res.status).to.eq(401);
        expect(res.mensagem).to.eq('O totem precisa ser liberado por um professor.');
      });
  });

  it('CT-72 [RNF01] Aluno tenta liberar o totem com e-mail e senha', () => {
    cy.usarTotem('qa');
    cy.intercept('POST', '/totem/liberar').as('liberar');
    cy.liberarTotemComSenha({ login: usuarios.aluno.email, senha: usuarios.aluno.senha });
    cy.wait('@liberar').its('response.statusCode').should('eq', 403);
    cy.contains('.alert-danger', 'E-mail ou senha incorretos.').should('be.visible');
    cy.ponte('dispositivo', { nome: 'Totem QA' }).its('liberado').should('eq', false);
  });

  it('CT-73 [Extra] Professor libera o totem com e-mail e senha (plano B)', () => {
    cy.usarTotem('qa');
    cy.liberarTotemComSenha(usuarios.professor);
    cy.contains('AO VIVO · Totem QA').should('be.visible');
    cy.ponte('dispositivo', { nome: 'Totem QA' }).then((d) => {
      expect(d.liberado).to.eq(true);
      expect(d.liberado_por).to.eq('Carlos');
      expect(d.liberado_ate, 'liberado até o fim do dia').to.eq('23:59:59');
    });
  });

  it('CT-77 [Extra] Qualquer professor libera qualquer totem', () => {
    cy.criarTotem('Totem QA 2').then((codigo) => cy.ativarTotem(codigo));
    cy.liberarTotemComSenha(usuarios.professorSemTurma);
    cy.contains('AO VIVO · Totem QA 2').should('be.visible');
    cy.ponte('dispositivo', { nome: 'Totem QA 2' }).its('liberado_por').should('eq', usuarios.professorSemTurma.nome);
  });

  it('CT-75 [RF02] Cadastro de rosto no totem com senha errada', () => {
    cy.usarTotem('qa');
    const status = [];
    Cypress._.times(6, () => {
      cy.postarJson('/api/cadastrar_foto', { matricula: '9400003', senha: 'senha-errada' })
        .then((res) => status.push(res.status));
    });
    cy.wrap(status).should('deep.eq', [403, 403, 403, 403, 403, 429]);
    cy.medicao('CT-75', { respostas: status });
    // nem a senha certa entra durante o bloqueio da matrícula
    cy.postarJson('/api/cadastrar_foto', { matricula: '9400003', senha: usuarios.senhaAlunoTeste })
      .its('status').should('eq', 429);
  });

  it('CT-76 [RNF01] Remover o totem desativa o tablet', () => {
    cy.entrar(usuarios.admin);
    cy.visit('/admin/totens');
    cy.get('tbody tr').filter((_, tr) => tr.cells[0].textContent.trim() === 'Totem QA')
      .find('button[title="Remover totem"]').click();
    cy.mensagem('Totem "Totem QA" removido.').should('be.visible');

    cy.usarTotem('qa');
    cy.visit('/');
    cy.ponte('caminho_projeto', { partes: ['static', 'assets', 'logo.png'] })
      .then(({ caminho }) => cy.readFile(caminho, 'base64'))
      .then((b64) => cy.enviarFrames({ url: '/api/totem/frame', base64: b64, duracaoMs: 1, pararQuando: () => true }))
      .its(0).its('status').should('eq', 401);
    cy.visit('/totem');
    cy.get('#codigo').should('be.visible');      // voltou para a tela de ativação
  });

  it('CT-74 [RNF01] Senha errada várias vezes na liberação', () => {
    // um tablet ativado e ainda bloqueado tenta liberar com a senha errada
    cy.criarTotem('Totem Bloqueio').then((codigo) => cy.ativarTotem(codigo));
    const status = [];
    Cypress._.times(11, () => {
      cy.postarFormulario('/totem/liberar', { email: usuarios.professor.login, senha: 'senha-errada' })
        .then((res) => status.push(res.status));
    });
    cy.wrap(status).should('have.length', 11).then(() => {
      const primeiro429 = status.indexOf(429);
      expect(primeiro429, 'bloqueia depois de no máximo 10 erros').to.be.within(0, 10);
      expect(status.slice(0, primeiro429).every((s) => s === 403), 'antes do bloqueio: 403').to.eq(true);
      expect(status.slice(primeiro429).every((s) => s === 429), 'depois: 429 (bloqueio de 15 min)').to.eq(true);
      cy.log(`Respostas: ${status.join(', ')}`);
      cy.medicao('CT-74', { respostas: status });
    });
    // nem a senha certa libera durante o bloqueio
    cy.postarFormulario('/totem/liberar', { email: usuarios.professor.login, senha: usuarios.professor.senha })
      .then((res) => {
        expect(res.status).to.eq(429);
        expect(res.body).to.contain('Muitas tentativas erradas. Aguarde 15 minutos.');
      });
    cy.ponte('dispositivo', { nome: 'Totem Bloqueio' }).its('liberado').should('eq', false);
  });
});
