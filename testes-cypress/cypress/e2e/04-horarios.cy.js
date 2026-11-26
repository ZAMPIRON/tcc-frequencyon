// Seção 4 — Módulo: Horários das turmas (CT-30 a CT-34)
import usuarios from '../fixtures/usuarios.json';

// formulário de um horário na tela Admin → Horários (pelo nome)
function formularioHorario(prefixo) {
  return cy.get('form').filter((_, f) => (f.querySelector('input[name="nome"]')?.value || '').startsWith(prefixo)).first();
}

describe('Horários das turmas', () => {
  beforeEach(() => cy.entrar(usuarios.admin));

  it('CT-30 [RF14] Horários padrão criados', () => {
    // banco novo: o próprio sistema cria os dois horários padrão
    cy.ponte('horarios_banco_novo').its('modelos').then((modelos) => {
      expect(modelos).to.have.length(2);
      expect(modelos[0]).to.include({ aulas: 10, resumo: '10 aulas · 07:05 às 16:40' });
      expect(modelos[0].nome).to.match(/^Técnico/);
      expect(modelos[1]).to.include({ aulas: 4, resumo: '4 aulas · 07:05 às 11:25' });
      expect(modelos[1].nome).to.match(/^CAI/);
    });
    // e a tela lista os horários
    cy.visit('/admin/horarios');
    formularioHorario('Técnico').should('contain', '10 aulas · 07:05 às 16:40');
    formularioHorario('CAI').should('contain', '4 aulas · 07:05 às 11:25');
  });

  it('CT-31 [RF14] Salvar horário com aulas sobrepostas', () => {
    cy.visit('/admin/horarios');
    formularioHorario('CAI').within(() => {
      cy.get('tbody tr').eq(0).within(() => {
        cy.get('input[name="inicio"]').clear().type('07:00');
        cy.get('input[name="fim"]').clear().type('08:00');
      });
      cy.get('tbody tr').eq(1).within(() => {
        cy.get('input[name="inicio"]').clear().type('07:30');
        cy.get('input[name="fim"]').clear().type('08:30');
      });
      cy.contains('button', 'Salvar horário').click();
    });
    cy.mensagem('se sobrepõem').should('be.visible');
    cy.ponte('modelo', { nome: 'CAI' }).its('aulas').then((aulas) => {
      expect(aulas[0], 'horário original mantido').to.deep.eq(['07:05', '08:05', 'manha']);
      expect(aulas[1]).to.deep.eq(['08:05', '09:05', 'manha']);
    });
  });

  it('CT-32 [RF14] Salvar aula que termina antes de começar', () => {
    cy.visit('/admin/horarios');
    formularioHorario('CAI').within(() => {
      cy.get('tbody tr').eq(0).within(() => {
        cy.get('input[name="inicio"]').clear().type('09:00');
        cy.get('input[name="fim"]').clear().type('08:00');
      });
      cy.contains('button', 'Salvar horário').click();
    });
    cy.mensagem('o fim precisa ser depois do início').should('be.visible');
    cy.ponte('modelo', { nome: 'CAI' }).its('aulas').its(0).should('deep.eq', ['07:05', '08:05', 'manha']);
  });

  it('CT-33 [RF14] Remover horário que está em uso', () => {
    cy.visit('/admin/horarios');
    // na tela o botão já vem desligado
    formularioHorario('Técnico').contains('button', 'Remover').should('be.disabled').and('have.attr', 'title', 'Em uso por turmas');
    // e o servidor também recusa se o pedido chegar mesmo assim
    cy.ponte('modelo', { nome: 'Técnico' }).then((m) => {
      expect(m.turmas, 'pré-condição: horário em uso').to.be.greaterThan(0);
      cy.postarFormulario(`/admin/horarios/${m.id}/remover`, {}).its('body').should('contain', 'está em uso');
      cy.ponte('modelo', { nome: 'Técnico' }).its('id').should('eq', m.id);
    });
  });

  it('CT-34 [RF14] Trocar o horário da turma', () => {
    cy.ponte('turma', { nome: 'C12' }).then((t) => {
      expect(t.aulas_por_dia, 'antes: Técnico').to.eq(10);
      cy.visit(`/admin/turmas/${t.id}`);
      cy.get('#modeloTurma').select('CAI (4 aulas de 60 min)');
      cy.mensagem('Horário da turma: CAI').should('be.visible');
      cy.ponte('turma', { nome: 'C12' }).its('aulas_por_dia').should('eq', 4);
    });
  });
});
