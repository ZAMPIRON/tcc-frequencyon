// Seção 4 — Módulo: Reconhecimento facial e prova de vida (CT-78 a CT-81)
// Rodada 1: servidor com a prova de vida ligada (configuração normal do sistema).
import usuarios from '../fixtures/usuarios.json';

describe('Reconhecimento facial', () => {
  it('CT-78 [RF02] Foto com um rosto gera o encoding do aluno', () => {
    cy.ponte('foto', { matricula: '2025002' }).then(({ caminho, existe }) => {
      expect(existe, 'foto cadastrada do Nicolas').to.eq(true);
      cy.ponte('encoding_foto', { caminho, matricula: '2025002' }).then((r) => {
        expect(r.encontrou_rosto).to.eq(true);
        expect(r.distancia, 'mesma pessoa (< 0,50)').to.be.lessThan(0.5);
        cy.log(`distância ${r.distancia}, cálculo em ${r.segundos} s`);
        cy.medicao('CT-78', { distancia: r.distancia, segundos: r.segundos });
      });
    });
  });

  it('CT-79 [RF03] Rostos de pessoas diferentes', () => {
    cy.ponte('distancia_alunos', { a: '2025002', b: '2025003' }).its('distancia').then((d) => {
      expect(d, 'pessoas diferentes (> 0,50)').to.be.greaterThan(0.5);
      cy.medicao('CT-79', { distancia: d });
    });
  });

  it('CT-80 [RF03] Imagem sem rosto', () => {
    cy.ponte('caminho_projeto', { partes: ['static', 'assets', 'logo.png'] }).then(({ caminho }) => {
      cy.ponte('encoding_foto', { caminho }).its('encontrou_rosto').should('eq', false);
    });
  });

  it('CT-81 [RF16] Prova de vida: foto parada (simula foto impressa)', () => {
    // pré-condição: totem criado, ativado e liberado pelo professor
    cy.criarTotem('Totem Prova de Vida').then((codigo) => cy.ativarTotem(codigo));
    cy.guardarTotem('vida');
    cy.liberarTotemComSenha(usuarios.professor);
    cy.contains('AO VIVO').should('be.visible');
    cy.visit('/');

    cy.ponte('aluno', { matricula: '2025002' }).its('presencas').as('antes');
    cy.ponte('caminho_projeto', { partes: ['static', 'assets', 'logo.png'] })
      .then(({ caminho }) => cy.readFile(caminho, 'base64')).as('semRosto');
    cy.ponte('foto', { matricula: '2025002' }).then(({ caminho }) => cy.readFile(caminho, 'base64')).as('fotoNicolas');

    // espera o reconhecimento do servidor ficar pronto
    cy.get('@semRosto').then((b64) => cy.enviarFrames({
      url: '/api/totem/frame', base64: b64, duracaoMs: 60000, intervaloMs: 300, pararQuando: (r) => r.pronto,
    })).then((r) => expect(r[r.length - 1].pronto, 'reconhecimento pronto').to.eq(true));

    // a mesma foto, parada, por 8 segundos
    cy.get('@fotoNicolas').then((b64) => cy.enviarFrames({ url: '/api/totem/frame', base64: b64, duracaoMs: 8000 }))
      .then((respostas) => {
        expect(respostas.every((r) => r.status === 200)).to.eq(true);
        expect(respostas.some((r) => r.caixa), 'o rosto foi detectado').to.eq(true);
        expect(respostas.filter((r) => r.evento), 'nenhum registro de presença').to.have.length(0);
        expect(respostas.map((r) => r.estado), 'nunca chega em "ok"').not.to.include('ok');
        expect(respostas[respostas.length - 1].estado, 'continua esperando a piscada').to.eq('pisque');
        cy.medicao('CT-81', { quadros_enviados: respostas.length, duracao_ms: respostas[respostas.length - 1].ms,
          estados: [...new Set(respostas.map((r) => r.estado))], eventos: 0 });
      });
    cy.get('@antes').then((antes) => cy.ponte('aluno', { matricula: '2025002' }).its('presencas').should('eq', antes));
  });
});
