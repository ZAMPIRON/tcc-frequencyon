// Seção 4 — Rodada 2: reconhecimento com a prova de vida desligada (CT-82 e CT-83)
// Uma foto parada não pisca; com PROVA_DE_VIDA=0 (só neste servidor de teste, porta 5056)
// dá para medir a identificação com uma foto. O banco é o mesmo da rodada 1.
import usuarios from '../fixtures/usuarios.json';

const RODADA2 = Cypress.config('baseUrl').replace(':5055', ':5056');
const imagens = {};

describe('Reconhecimento — rodada 2 (prova de vida desligada)', { baseUrl: RODADA2 }, () => {
  before(() => {
    cy.ponte('caminho_projeto', { partes: ['static', 'assets', 'logo.png'] })
      .then(({ caminho }) => cy.readFile(caminho, 'base64')).then((b64) => { imagens.semRosto = b64; });
    cy.ponte('foto', { matricula: '2025002' }).then(({ caminho }) => cy.readFile(caminho, 'base64'))
      .then((b64) => { imagens.aluno = b64; });
    cy.ponte('foto', { email: usuarios.professor.login }).then(({ caminho }) => cy.readFile(caminho, 'base64'))
      .then((b64) => { imagens.professor = b64; });
  });

  it('CT-82 [RF03, RNF02] Reconhecimento do aluno (prova de vida desligada só para o teste)', () => {
    cy.criarTotem('Totem Rodada 2').then((codigo) => cy.ativarTotem(codigo));
    cy.liberarTotemComSenha(usuarios.professor);
    cy.contains('AO VIVO').should('be.visible');
    cy.visit('/');

    // aquecimento: espera o reconhecimento subir e responder (rosto de professor = desconhecido para alunos)
    cy.enviarFrames({ url: '/api/totem/frame', base64: imagens.professor, duracaoMs: 90000,
      intervaloMs: 250, pararQuando: (r) => r.estado === 'desconhecido' })
      .then((r) => expect(r[r.length - 1].estado, 'reconhecimento respondendo').to.eq('desconhecido'));
    // tira o rosto da frente da câmera
    cy.enviarFrames({ url: '/api/totem/frame', base64: imagens.semRosto, duracaoMs: 1500 });

    // o aluno para na frente do totem
    cy.enviarFrames({ url: '/api/totem/frame', base64: imagens.aluno, duracaoMs: 10000,
      intervaloMs: 100, pararQuando: (r) => r.evento })
      .then((respostas) => {
        const comEvento = respostas.find((r) => r.evento);
        expect(comEvento, 'aluno reconhecido').to.exist;
        expect(comEvento.evento.nome).to.eq(usuarios.aluno.nome);
        expect(comEvento.evento.matricula).to.eq(usuarios.aluno.login);
        expect(comEvento.ms, 'identificado em até 2 s').to.be.at.most(2000);
        cy.log(`Identificou ${comEvento.evento.nome} em ${(comEvento.ms / 1000).toFixed(2)} s ` +
          `(${comEvento.evento.status}: ${comEvento.evento.mensagem})`);
        cy.medicao('CT-82', { nome: comEvento.evento.nome, segundos: comEvento.ms / 1000,
          status: comEvento.evento.status, mensagem: comEvento.evento.mensagem });
      });
  });

  it('CT-83 [Extra] Professor libera o totem pelo rosto', () => {
    cy.criarTotem('Totem Rosto Professor').then((codigo) => cy.ativarTotem(codigo));
    cy.contains('Totem bloqueado').should('be.visible');
    cy.ponte('dispositivo', { nome: 'Totem Rosto Professor' }).its('liberado').should('eq', false);

    cy.enviarFrames({ url: '/totem/liberar/frame', base64: imagens.professor, duracaoMs: 15000,
      intervaloMs: 100, pararQuando: (r) => r.liberado })
      .then((respostas) => {
        const liberou = respostas.find((r) => r.liberado);
        expect(liberou, 'totem liberado pelo rosto').to.exist;
        expect(liberou.nome).to.eq(usuarios.professor.nome);
        cy.log(`Liberado por ${liberou.nome} em ${(liberou.ms / 1000).toFixed(2)} s`);
        cy.medicao('CT-83', { nome: liberou.nome, segundos: liberou.ms / 1000 });
      });
    cy.ponte('dispositivo', { nome: 'Totem Rosto Professor' }).then((d) => {
      expect(d.liberado).to.eq(true);
      expect(d.liberado_por).to.eq('Carlos');
    });
    cy.visit('/totem');
    cy.contains('AO VIVO · Totem Rosto Professor').should('be.visible');
  });
});
