// Seção 4 — Módulo: Área do aluno e justificativas (CT-56 a CT-62)
// Turma de teste C96 (horário Técnico). Em 02/11/2026 (segunda):
//   9300001 e 9300003 passaram só de manhã (falta à tarde); 9300002 passou de manhã e à tarde.
import usuarios from '../fixtures/usuarios.json';

const DIA = '2026-11-02';
const SENHA = usuarios.senhaAlunoTeste;
const alunoTeste = (matricula) => ({ tipo: 'aluno', login: matricula, senha: SENHA, destino: '/aluno/' });

describe('Área do aluno e justificativas', () => {
  before(() => {
    ['9300001', '9300002', '9300003'].forEach((m) => cy.ponte('registrar_totem', { matricula: m, quando: `${DIA}T06:50` }));
    cy.ponte('registrar_totem', { matricula: '9300002', quando: `${DIA}T12:20` });
  });

  it('CT-56 [RF18] Aluno vê a própria frequência e o histórico', () => {
    cy.entrar(alunoTeste('9300001'));
    cy.visit('/aluno/');
    cy.contains('h1', 'Justifica Falta').should('be.visible');
    cy.contains('Frequência geral').should('be.visible');
    cy.get('.frequencia-anel').should('contain', '50%');
    cy.contains('h2', 'Histórico de aulas').should('be.visible');
  });

  it('CT-57 [RF11] Histórico guarda os dias anteriores', () => {
    cy.entrar(alunoTeste('9300001'));
    cy.visit('/aluno/');
    cy.contains('.tabela-historico tbody tr', '02/11/2026').should('be.visible');
  });

  it('CT-58 [RF19] Exportar frequência em CSV', () => {
    cy.entrar(alunoTeste('9300001'));
    cy.request('/aluno/exportar').then((res) => {
      expect(res.headers['content-type']).to.contain('text/csv');
      expect(res.headers['content-disposition']).to.contain('frequencia_9300001.csv');
      const linhas = res.body.replace(/^﻿/, '').trim().split(/\r?\n/);
      const cabecalho = linhas.find((l) => l.startsWith('Data;'));
      expect(cabecalho.split(';')).to.include.members(['Aula 1', 'Aula 10']);
      expect(linhas.find((l) => l.startsWith('02/11/2026')), 'linha do dia 02/11').to.contain('P;P;P;P;P;F;F;F;F;F');
    });
  });

  it('CT-59 [Extra] Justificar um dia com falta', () => {
    cy.entrar(alunoTeste('9300001'));
    cy.visit('/aluno/');
    cy.contains('button', 'Justificar falta').click();
    cy.get('#modalJustificar').should('be.visible').within(() => {
      cy.get('#dataFalta').select('02/11/2026');
      cy.get('#motivo').type('Consulta médica, atestado entregue na secretaria.');
      cy.contains('button', 'Enviar').click();
    });
    cy.contains('Justificativa enviada! Aguarde a análise da coordenação.').should('be.visible');
    cy.ponte('justificativa', { matricula: '9300001', data: DIA }).its('status').should('eq', 'pendente');
    // aviso para a coordenação (o e-mail fica na caixa de saída dos testes)
    cy.ponte('caixa_saida').its('emails').then((emails) => {
      const aviso = emails.find((e) => e.assunto.includes('Justifica Falta'));
      expect(aviso, 'e-mail para a coordenação').to.exist;
      expect(aviso.para).to.eq('coordenacao.teste@localhost');
      expect(aviso.assunto).to.eq('Justificativa de falta - Justifica Falta (02/11/2026)');
    });
  });

  it('CT-60 [Extra] Justificar um dia sem falta', () => {
    cy.entrar(alunoTeste('9300002'));
    cy.visit('/aluno/');
    cy.contains('button', 'Justificar falta').click();
    cy.get('#modalJustificar').should('contain', 'Você não tem faltas pendentes de justificativa.');
    // pedido enviado mesmo assim (sem passar pela tela)
    cy.postarFormulario('/aluno/justificar', { data: DIA, motivo: 'Tentando justificar dia sem falta' })
      .its('body').should('contain', 'Escolha um dia com falta que ainda não foi justificado.');
    cy.ponte('justificativa', { matricula: '9300002', data: DIA }).its('existe').should('eq', false);
  });

  it('CT-61 [Extra] Justificativa com motivo muito curto', () => {
    cy.entrar(alunoTeste('9300003'));
    cy.visit('/aluno/');
    cy.contains('button', 'Justificar falta').click();
    cy.get('#modalJustificar').should('be.visible').within(() => {
      cy.get('#dataFalta').select('02/11/2026');
      cy.get('#motivo').invoke('removeAttr', 'minlength').type('ok');
      cy.contains('button', 'Enviar').click();
    });
    cy.contains('Descreva o motivo da falta.').should('be.visible');
    cy.ponte('justificativa', { matricula: '9300003', data: DIA }).its('existe').should('eq', false);
  });

  it('CT-62 [Extra] Coordenação aceita a justificativa', () => {
    cy.entrar(usuarios.admin);
    cy.ponte('aluno', { matricula: '9300001' }).then((a) => cy.visit(`/admin/alunos/${a.id}`));
    cy.contains('button', 'Aceitar').click();
    cy.contains('Justificativa aceita').should('be.visible');
    cy.ponte('justificativa', { matricula: '9300001', data: DIA }).its('status').should('eq', 'aceita');
  });
});
