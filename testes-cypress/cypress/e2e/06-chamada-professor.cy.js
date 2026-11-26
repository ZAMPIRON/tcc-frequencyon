// Seção 4 — Módulo: Chamada do professor (CT-47 a CT-55)
// Turma de teste C97 (horário Técnico, 10 aulas), com aula todos os dias para o professor Carlos.
import usuarios from '../fixtures/usuarios.json';

describe('Chamada do professor', () => {
  let turmaId;
  let datas;
  const ids = {};

  before(() => {
    cy.ponte('hoje').then((h) => { datas = h; });
    cy.ponte('turma', { nome: 'C97' }).then((t) => { turmaId = t.id; });
    ['9200001', '9200002', '9200003'].forEach((m) => cy.ponte('aluno', { matricula: m }).then((a) => { ids[m] = a.id; }));
  });

  beforeEach(() => cy.entrar(usuarios.professor));

  const barra = (aluno, indice) => cy.contains('tbody tr', aluno).find('.bar').eq(indice);

  it('CT-47 [RF06] Abrir a chamada da turma', () => {
    cy.visit(`/professor/chamada?turma_id=${turmaId}`);
    cy.contains('th', 'Status (10 aulas)').should('be.visible');
    ['Chamada Um', 'Chamada Dois', 'Chamada Tres'].forEach((nome) => {
      cy.contains('tbody tr', nome).find('.bar').should('have.length', 10);
    });
  });

  it('CT-48 [RF15] Marcar presença/falta hoje', () => {
    cy.visit(`/professor/chamada?turma_id=${turmaId}`);
    barra('Chamada Um', 0).should('have.class', 'off').click();
    barra('Chamada Um', 0).should('have.class', 'on');
    cy.ponte('presenca', { matricula: '9200001', data: datas.hoje, aula: 0 }).then((p) => {
      expect(p.status).to.eq('presente');
      expect(p.origem).to.eq('professor');
    });
  });

  it('CT-49 [RF15] Marcar atraso numa aula da tarde', () => {
    cy.visit(`/professor/chamada?turma_id=${turmaId}`);
    barra('Chamada Um', 7).rightclick();
    barra('Chamada Um', 7).should('have.class', 'late');
    cy.ponte('presenca', { matricula: '9200001', data: datas.hoje, aula: 7 }).its('status').should('eq', 'atraso');
  });

  it('CT-50 [RNF01] Alterar chamada de dia anterior sem senha do admin', () => {
    const dia = datas.segunda_passada;
    cy.postarJson(`/professor/toggle/${ids['9200002']}/0?data=${dia}`, { data: dia }).then((res) => {
      expect(res.status).to.eq(403);
      expect(res.body.erro).to.eq('Para alterar uma chamada anterior, informe a senha de um administrador.');
    });
    cy.ponte('presenca', { matricula: '9200002', data: dia, aula: 0 }).its('existe').should('eq', false);
  });

  it('CT-51 [RF15] Alterar chamada de dia anterior com a senha do admin', () => {
    const dia = datas.segunda_passada;
    cy.visit(`/professor/chamada?turma_id=${turmaId}&data=${dia}`);
    barra('Chamada Dois', 0).click();
    cy.contains('.modal.show', 'Alterar chamada anterior').within(() => {
      cy.get('input[type="password"]').type(usuarios.admin.senha, { log: false });
      cy.contains('button', 'Liberar edição').click();
    });
    barra('Chamada Dois', 0).should('have.class', 'on');
    cy.ponte('presenca', { matricula: '9200002', data: dia, aula: 0 }).its('status').should('eq', 'presente');
  });

  it('CT-52 [RF17] Alteração manual registra quem alterou e quando', () => {
    const dia = datas.dia_regras;
    // pré-condição: o totem registrou o aluno às 08:00 (aula 3 = presente)
    cy.ponte('registrar_totem', { matricula: '9200003', quando: `${dia}T08:00` });
    cy.ponte('presenca', { matricula: '9200003', data: dia, aula: 2 }).its('origem').should('eq', 'totem');

    cy.postarJson(`/professor/toggle/${ids['9200003']}/2?data=${dia}`, { data: dia, admin_senha: usuarios.admin.senha })
      .its('body.estado').should('eq', 'falta');

    cy.ponte('alteracoes', { matricula: '9200003', data: dia, aula: 2 }).its('alteracoes').then((lista) => {
      expect(lista).to.have.length(1);
      expect(lista[0].professor, 'quem alterou').to.eq('Carlos');
      expect(lista[0].anterior, 'valor anterior').to.eq('presente');
      expect(lista[0].novo).to.eq('falta');
      expect(lista[0].com_senha_admin).to.eq(true);
      expect(lista[0].alterado_em.slice(0, 10), 'data da alteração').to.eq(datas.hoje);
    });
    // a coordenação vê a alteração na trilha de auditoria
    cy.entrar(usuarios.admin);
    cy.visit('/admin/auditoria');
    cy.contains('tr', 'Chamada Tres').should('contain', 'Carlos').and('contain', 'aula 3')
      .and('contain', 'presente → falta').and('contain', 'Sim');
  });

  it('CT-53 [RNF06] Alterar chamada de dia futuro', () => {
    cy.postarJson(`/professor/toggle/${ids['9200001']}/1?data=${datas.amanha}`,
      { data: datas.amanha, admin_senha: usuarios.admin.senha }).then((res) => {
      expect(res.status).to.eq(403);
      expect(res.body.erro).to.eq('Não é possível alterar uma chamada futura.');
    });
  });

  it('CT-54 [RNF01] Professor altera aluno de turma que não é dele', () => {
    cy.entrar(usuarios.professorSemTurma);
    cy.postarJson(`/professor/toggle/${ids['9200001']}/1?data=${datas.hoje}`, { data: datas.hoje }).then((res) => {
      expect(res.status).to.eq(403);
      expect(res.body.erro).to.eq('Aluno não pertence às suas turmas.');
    });
    cy.ponte('presenca', { matricula: '9200001', data: datas.hoje, aula: 1 }).its('existe').should('eq', false);
  });

  it('CT-55 [RNF06] Barra de aula inexistente', () => {
    cy.postarJson(`/professor/toggle/${ids['9200001']}/10?data=${datas.hoje}`, { data: datas.hoje }).then((res) => {
      expect(res.status).to.eq(400);
      expect(res.body.erro).to.eq('Aula inválida.');
    });
  });
});
