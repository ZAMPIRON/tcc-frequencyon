// Seção 4 — Módulo: Regras de presença do totem (CT-35 a CT-46)
// O reconhecimento chama registrar_presenca_totem(aluno, agora). Aqui ela é chamada com o horário
// de cada cenário, numa segunda-feira (02/11/2026), turma C99 com o horário Técnico:
// manhã 07:05–11:10 (aulas 1 a 5), tarde 12:40–16:40 (aulas 6 a 10), totem abre 30 min antes do período.
// Legenda das linhas do dia: P presente, A atraso, F falta, · sem registro.
const DIA = '2026-11-02';

function passarNoTotem(matricula, hora, dia = DIA) {
  return cy.ponte('registrar_totem', { matricula, quando: `${dia}T${hora}` });
}

describe('Regras de presença (totem)', () => {
  context('aluno que chega antes da aula e volta do almoço (mesmo aluno, em sequência)', () => {
    it('CT-35 [RF04] Aluno chega antes da primeira aula', () => {
      passarNoTotem('9100001', '06:50').then((r) => {
        expect(r.status).to.eq('presente');
        expect(r.dia, 'presença nas 5 aulas da manhã').to.eq('PPPPP·····');
      });
    });

    it('CT-36 [RF04] Presença gravada com data e horário', () => {
      cy.ponte('presenca', { matricula: '9100001', data: DIA, aula: 0 }).then((p) => {
        expect(p.existe).to.eq(true);
        expect(p.data).to.eq(DIA);
        expect(p.hora).to.eq('06:50');
        expect(p.origem).to.eq('totem');
      });
    });

    it('CT-39 [RF05] Aluno passa duas vezes no mesmo período', () => {
      passarNoTotem('9100001', '09:50').then((r) => {
        expect(r.ja_registrado, 'já registrado').to.eq(true);
        expect(r.registros, 'sem duplicar').to.eq(5);
      });
    });

    it('CT-40 [RF05] Passagem no almoço, antes de abrir a tarde', () => {
      passarNoTotem('9100001', '11:30').then((r) => {
        expect(r.status).to.eq('fora_horario');
        expect(r.mensagem).to.eq('O registro da tarde abre às 12:10.');
        expect(r.registros).to.eq(5);
      });
    });

    it('CT-41 [RF04] Aluno volta do almoço e passa no totem', () => {
      passarNoTotem('9100001', '12:20').then((r) => {
        expect(r.status).to.eq('presente');
        expect(r.dia).to.eq('PPPPPPPPPP');
      });
    });
  });

  it('CT-37 [RF14] Aluno chega 3 min depois do início', () => {
    passarNoTotem('9100002', '07:08').then((r) => {
      expect(r.status).to.eq('atraso');
      expect(r.dia, 'atraso na aula 1, presença nas demais da manhã').to.eq('APPPP·····');
    });
  });

  it('CT-38 [RF14] Aluno chega no meio da segunda aula', () => {
    passarNoTotem('9100003', '08:00').then((r) => {
      expect(r.dia, 'falta nas aulas 1 e 2').to.eq('FFPPP·····');
    });
  });

  it('CT-42 [RNF06] Aluno vai embora no almoço', () => {
    // o aluno do CT-37 passou só de manhã
    cy.ponte('linha_dia', { matricula: '9100002', data: DIA }).its('dia').should('eq', 'APPPP·····');
    cy.ponte('aluno', { matricula: '9100002' }).its('frequencia').should('eq', 50);
    // e é o que ele vê no portal
    cy.entrar({ tipo: 'aluno', login: '9100002', senha: 'Aluno@Teste2026', destino: '/aluno/' });
    cy.visit('/aluno/');
    cy.get('.frequencia-anel').should('contain', '50%');
  });

  it('CT-43 [RNF06] Reconhecimento em dia sem aula', () => {
    passarNoTotem('9100004', '07:00', '2026-11-01').then((r) => {       // domingo
      expect(r.status).to.eq('sem_aula');
      expect(r.registros).to.eq(0);
    });
  });

  it('CT-44 [RNF06] Reconhecimento depois da última aula', () => {
    passarNoTotem('9100005', '17:00').then((r) => {
      expect(r.status).to.eq('fora_horario');
      expect(r.mensagem).to.eq('As aulas da sua turma já acabaram hoje.');
      expect(r.registros).to.eq(0);
    });
  });

  it('CT-45 [RF14] Turma CAI (4 aulas de 60 min)', () => {
    passarNoTotem('9100010', '07:00').then((r) => {
      expect(r.registros).to.eq(4);
      expect(r.dia).to.eq('PPPP');
    });
    cy.ponte('aluno', { matricula: '9100010' }).its('frequencia').should('eq', 100);
  });

  it('CT-46 [RF15] Totem não sobrescreve a chamada do professor', () => {
    // pré-condição: o professor lançou falta na aula 6 (primeira da tarde)
    cy.ponte('lancar', { matricula: '9100006', data: DIA, aula: 5, status: 'falta', origem: 'professor' });
    passarNoTotem('9100006', '12:30').then((r) => {
      expect(r.dia, 'aula 6 continua falta, demais presença').to.eq('·····FPPPP');
    });
    cy.ponte('presenca', { matricula: '9100006', data: DIA, aula: 5 }).its('origem').should('eq', 'professor');
  });
});
