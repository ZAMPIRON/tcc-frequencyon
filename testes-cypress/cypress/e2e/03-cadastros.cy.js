// Seção 4 — Módulo: Cadastros de alunos, professores e turmas (CT-15 a CT-29)
import usuarios from '../fixtures/usuarios.json';

const SENHA_FORTE = 'Senha@Forte2026';

function formularioAluno({ nome, matricula, senha = SENHA_FORTE, turma, numero }) {
  cy.visit('/admin/alunos/novo');
  cy.get('input[name="nome"]').type(nome);
  cy.get('input[name="email"]').type(`${matricula}@cypress.teste`);
  cy.get('input[name="matricula"]').type(matricula);
  if (numero) cy.get('input[name="numero_chamada"]').type(String(numero));
  // o teste confere a regra do servidor, então tira a validação do navegador (minlength)
  cy.get('input[name="senha"]').invoke('removeAttr', 'minlength').type(senha, { log: false });
  if (turma) cy.get('select[name="turma_id"]').select(turma);
}

function abrirEdicaoAluno(matricula) {
  cy.visit(`/admin/alunos?busca=${matricula}`);
  cy.contains('tr', matricula).find('.btn-editar-aluno').click();
  cy.get('#modalEditarAluno').should('be.visible');
}

describe('Cadastros (alunos, professores, turmas)', () => {
  beforeEach(() => cy.entrar(usuarios.admin));

  it('CT-15 [RF01] Cadastrar aluno com dados válidos', () => {
    formularioAluno({ nome: 'Aluno Cypress', matricula: '9000001', turma: 'C13 - Desenvolvimento de Sistemas 1' });
    cy.contains('button', 'Cadastrar Aluno').click();
    cy.location('pathname').should('eq', '/admin/alunos');
    cy.mensagem('Aluno cadastrado com sucesso!').should('be.visible');
    cy.ponte('aluno', { matricula: '9000001' }).then((a) => {
      expect(a.existe).to.eq(true);
      expect(a.nome).to.eq('Aluno Cypress');
      expect(a.turma_curso).to.eq('Desenvolvimento de Sistemas 1');
    });
  });

  it('CT-16 [RF02] Cadastrar aluno com foto do rosto', () => {
    formularioAluno({ nome: 'Aluno Com Foto', matricula: '9000016' });
    // foto de um aluno do banco que não participa dos casos do totem (Nicolas Bertacin)
    cy.ponte('foto', { matricula: '2025090' }).then(({ caminho }) => {
      cy.get('input[name="foto"]').selectFile(caminho);
    });
    cy.contains('button', 'Cadastrar Aluno').click();
    cy.mensagem('Aluno cadastrado com sucesso!').should('be.visible');
    cy.ponte('aluno', { matricula: '9000016' }).then((a) => {
      expect(a.foto, 'foto salva').to.match(/^\/static\/uploads\/.+\.jpg$/);
      expect(a.tem_rosto, 'rosto (encoding de 128 números) salvo').to.eq(true);
    });
  });

  it('CT-17 [RF12] Buscar aluno por nome e por matrícula', () => {
    cy.visit('/admin/alunos');
    cy.get('input[name="busca"]').type('luciani');
    cy.contains('button', 'Buscar').click();
    cy.get('tbody tr').should('have.length', 1).first().should('contain', 'Nicolas Luciani');
    cy.get('input[name="busca"]').clear().type('2025003');
    cy.contains('button', 'Buscar').click();
    cy.get('tbody tr').should('have.length', 1).first().should('contain', 'Samuel Gustavo');
  });

  it('CT-18 [RF01] Cadastrar aluno com matrícula repetida', () => {
    formularioAluno({ nome: 'Outro Aluno', matricula: '9000001' });
    cy.contains('button', 'Cadastrar Aluno').click();
    cy.mensagem('Já existe um aluno com essa matrícula.').should('be.visible');
    cy.location('pathname').should('eq', '/admin/alunos/novo');
    cy.ponte('aluno', { matricula: '9000001' }).its('nome').should('eq', 'Aluno Cypress');
  });

  it('CT-19 [RNF01] Cadastrar aluno com senha fraca', () => {
    formularioAluno({ nome: 'Aluno Senha Fraca', matricula: '9000019', senha: '123' });
    cy.contains('button', 'Cadastrar Aluno').click();
    cy.mensagem('A senha precisa ter pelo menos 8 caracteres').should('be.visible');
    cy.ponte('aluno', { matricula: '9000019' }).its('existe').should('eq', false);
  });

  it('CT-20 [RF01] Cadastrar aluno com nome só de espaços', () => {
    formularioAluno({ nome: '   ', matricula: '9000020' });
    cy.contains('button', 'Cadastrar Aluno').click();
    cy.mensagem('Nome e matrícula são obrigatórios.').should('be.visible');
    cy.ponte('aluno', { matricula: '9000020' }).its('existe').should('eq', false);
  });

  it('CT-21 [RF08] Editar aluno com senha curta', () => {
    abrirEdicaoAluno('9000001');
    cy.get('#editarAlunoNome').clear().type('Nome Que Nao Deve Salvar');
    cy.get('#modalEditarAluno input[name="senha"]').invoke('removeAttr', 'minlength').type('abc');
    cy.contains('#modalEditarAluno button', 'Salvar alterações').click();
    cy.mensagem('Nada foi alterado').should('be.visible');
    cy.ponte('aluno', { matricula: '9000001', senha: SENHA_FORTE }).then((a) => {
      expect(a.senha_confere, 'senha antiga mantida').to.eq(true);
      expect(a.nome, 'nome mantido').to.eq('Aluno Cypress');
    });
  });

  it('CT-22 [RF08] Editar dados do aluno', () => {
    abrirEdicaoAluno('9000001');
    cy.get('#editarAlunoNome').clear().type('Aluno Editado');
    cy.get('#editarAlunoNumero').clear().type('7');
    cy.contains('#modalEditarAluno button', 'Salvar alterações').click();
    cy.mensagem('Dados de Aluno Editado atualizados.').should('be.visible');
    cy.ponte('aluno', { matricula: '9000001' }).then((a) => {
      expect(a.nome).to.eq('Aluno Editado');
      expect(a.numero_chamada).to.eq(7);
    });
  });

  function novoProfessor({ nome, email, senha, departamento = 'TI' }) {
    cy.visit('/admin/professores');
    cy.contains('button', 'Cadastrar Professor').click();
    cy.get('#modalProfessor').should('be.visible').within(() => {
      cy.get('input[name="nome"]').type(nome);
      cy.get('input[name="email"]').type(email);
      cy.get('input[name="senha"]').invoke('removeAttr', 'minlength').type(senha, { log: false });
      cy.get('input[name="departamento"]').type(departamento);
      cy.contains('button', 'Salvar Cadastro').click();
    });
  }

  it('CT-23 [RF10] Cadastrar professor com e-mail já usado (maiúsculas)', () => {
    novoProfessor({ nome: 'Carlos Duplicado', email: 'CARLOS@PROFESSOR.SENAI.COM', senha: 'Outra@Senha2026' });
    cy.mensagem('Já existe um professor com esse e-mail.').should('be.visible');
    cy.ponte('professores_com_email', { email: 'carlos@professor.senai.com' }).its('quantidade').should('eq', 1);
  });

  it('CT-24 [RNF01] Cadastrar professor com senha fraca', () => {
    novoProfessor({ nome: 'Professor Senha Fraca', email: 'prof.fraca@cypress.teste', senha: 'prof123' });
    cy.mensagem('A senha precisa ter pelo menos 8 caracteres e não pode ser uma senha fraca.').should('be.visible');
    cy.ponte('professores_com_email', { email: 'prof.fraca@cypress.teste' }).its('quantidade').should('eq', 0);
  });

  it('CT-25 [RF10] Editar professor', () => {
    cy.visit('/admin/professores');
    cy.contains('tr', 'prof.editavel@frequencyon.teste').find('[data-bs-target="#modalEditarProfessor"]').click();
    cy.get('#modalEditarProfessor').should('be.visible').within(() => {
      cy.get('#editarNome').clear().type('Prof Editado');
      cy.get('#editarDepartamento').clear().type('TI');
      cy.contains('button', 'Salvar alterações').click();
    });
    cy.mensagem('Dados de Prof Editado atualizados.').should('be.visible');
    cy.ponte('professor', { email: 'prof.editavel@frequencyon.teste' }).then((p) => {
      expect(p.nome).to.eq('Prof Editado');
      expect(p.departamento).to.eq('TI');
    });
  });

  it('CT-26 [RF09] Criar turma com nome em branco', () => {
    cy.visit('/admin/turmas');
    cy.contains('button', 'Nova Turma').click();
    cy.get('#modalTurma').should('be.visible').within(() => {
      cy.get('input[name="nome"]').type('   ');
      cy.get('input[name="curso"]').type('Turma Sem Nome');
      cy.contains('button', 'Salvar Turma').click();
    });
    cy.mensagem('Nome e curso da turma são obrigatórios.').should('be.visible');
    cy.ponte('turma', { nome: '', curso: 'Turma Sem Nome' }).its('existe').should('eq', false);
    cy.ponte('turma', { nome: '   ', curso: 'Turma Sem Nome' }).its('existe').should('eq', false);
  });

  it('CT-27 [RF09] Turmas da mesma sala aparecem juntas', () => {
    cy.visit('/admin/turmas');
    cy.get('[data-busca-item] h6').then(($titulos) => {
      const salas = [...$titulos].map((h) => h.textContent.trim());
      const primeira = salas.indexOf('C13');
      expect(primeira, 'sala C13 listada').to.be.greaterThan(-1);
      expect(salas.slice(primeira, primeira + 2), 'as duas turmas da C13 em sequência').to.deep.eq(['C13', 'C13']);
      expect(salas.filter((s) => s === 'C13')).to.have.length(2);
    });
    cy.get('[data-busca-item]').filter(':contains("C13")').should('contain', 'Desenvolvimento de Sistemas 1')
      .and('contain', 'Desenvolvimento de Sistemas 2');
  });

  it('CT-28 [RF09] Excluir turma mantém os alunos', () => {
    cy.visit('/admin/turmas');
    cy.contains('button', 'Nova Turma').click();
    cy.get('#modalTurma').should('be.visible').within(() => {
      cy.get('input[name="nome"]').type('C90');
      cy.get('input[name="curso"]').type('Turma Temporaria');
      cy.contains('button', 'Salvar Turma').click();
    });
    cy.mensagem('Turma criada!').should('be.visible');
    cy.contains('[data-busca-item]', 'Turma Temporaria').contains('a', 'Ver Alunos e Detalhes').click();
    cy.get('[data-bs-target="#modalAdicionarAluno"]').click();
    cy.get('#modalAdicionarAluno').should('be.visible').within(() => {
      cy.get('select[name="aluno_id"]').select('Aluno Avulso (Matrícula: 9400001)');
      cy.contains('button', 'Adicionar à Turma').click();
    });
    cy.contains('Aluno Avulso').should('be.visible');
    cy.ponte('turma', { nome: 'C90' }).its('alunos').should('deep.eq', ['9400001']);

    cy.visit('/admin/turmas');
    cy.contains('[data-busca-item]', 'Turma Temporaria').find('button[aria-label="Excluir turma"]').click();
    cy.contains('[data-busca-item]', 'Turma Temporaria').should('not.exist');
    cy.ponte('turma', { nome: 'C90' }).its('existe').should('eq', false);
    cy.ponte('aluno', { matricula: '9400001' }).then((a) => {
      expect(a.existe, 'aluno continua cadastrado').to.eq(true);
      expect(a.turma_id, 'aluno sem turma').to.eq(null);
    });
  });

  it('CT-29 [RF08] Excluir aluno apaga as presenças dele', () => {
    cy.ponte('aluno', { matricula: '9400002' }).then((a) => {
      expect(a.presencas, 'pré-condição: aluno com presenças').to.be.greaterThan(0);
      cy.visit('/admin/alunos?busca=9400002');
      cy.contains('tr', '9400002').find('button[aria-label="Excluir aluno"]').click();
      cy.mensagem('Aluno removido.').should('be.visible');
      cy.ponte('aluno_por_id', { id: a.id }).then((r) => {
        expect(r.existe, 'aluno removido').to.eq(false);
        expect(r.presencas, 'presenças removidas').to.eq(0);
      });
    });
  });
});
