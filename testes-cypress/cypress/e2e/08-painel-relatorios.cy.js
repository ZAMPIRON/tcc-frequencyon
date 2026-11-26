// Seção 4 — Módulo: Painel e relatórios (CT-63 a CT-65)
import usuarios from '../fixtures/usuarios.json';

describe('Painel e relatórios', () => {
  beforeEach(() => cy.entrar(usuarios.admin));

  it('CT-63 [RF07] Páginas do painel abrem sem erro', () => {
    cy.ponte('turma', { nome: 'C13', curso: 'Desenvolvimento de Sistemas 1' }).then((t) => {
      const paginas = ['/admin/dashboard', '/admin/alunos', '/admin/alunos/novo', '/admin/professores', '/admin/turmas',
        `/admin/turmas/${t.id}`, '/admin/horarios', '/admin/totens', '/admin/relatorios', '/admin/risco-evasao'];
      paginas.forEach((url) => cy.request({ url, followRedirect: false }).its('status').should('eq', 200));
      // e a navegação pelo menu lateral
      cy.visit('/admin/dashboard');
      cy.get('.nav-lateral a[data-rota]').should('have.length.at.least', 6);
    });
  });

  it('CT-64 [RF19] Exportar planilha de relatórios', () => {
    cy.visit('/admin/relatorios');
    cy.get('a[href^="/admin/relatorios/exportar"]').should('be.visible').invoke('attr', 'href').then((href) => {
      cy.request({ url: href, encoding: 'base64' }).then((res) => {
        expect(res.headers['content-type']).to.contain('spreadsheetml');
        cy.ponte('abas_xlsx', { base64: res.body }).its('abas')
          .should('deep.eq', ['Resumo', 'Alunos', 'Turmas', 'Professores', 'Em risco', 'Justificativas']);
      });
    });
  });

  it('CT-65 [RF07] Risco de evasão lista quem está abaixo de 75%', () => {
    cy.ponte('risco').then(({ abaixo, acima }) => {
      expect(abaixo.length, 'pré-condição: há alunos abaixo de 75%').to.be.greaterThan(0);
      cy.visit('/admin/risco-evasao');
      cy.get('tbody tr td:nth-child(2)').then(($nomes) => {
        const listados = [...$nomes].map((td) => td.textContent.trim()).sort();
        expect(listados, 'todos abaixo de 75%').to.deep.eq(abaixo);
        acima.forEach((nome) => expect(listados, `${nome} (≥ 75%) não aparece`).not.to.include(nome));
        cy.medicao('CT-65', { listados: listados.length, acima_de_75: acima.length });
      });
      cy.get('tbody tr td:nth-child(4)').each(($td) => {
        expect(parseInt($td.text(), 10)).to.be.lessThan(75);
      });
    });
  });
});
