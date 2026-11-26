"""Ponte entre o Cypress e o FrequencyON (chamada pelo cy.task "ponte").

Uso: python ponte.py preparar   (antes de subir os servidores)
As outras ações rodam dentro do servidor de teste (rota /__teste__/ponte/<acao> do servidor_teste.py):
assim as gravações passam pelo mesmo processo do site e o cache de frequência dele continua certo.

Serve para duas coisas que o navegador não alcança:
  - preparar a massa de dados (cópia do banco do projeto + turmas e alunos de teste);
  - consultar o banco de teste e chamar regras com um horário escolhido
    (ex.: "o aluno passou no totem às 07:08 de 02/11/2026").
O banco usado é sempre a cópia em .tmp/; o banco e as fotos do projeto não são alterados.
"""
import base64
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJETO = os.path.abspath(os.environ.get("FREQUENCYON_DIR", os.path.join(RAIZ, "..")))
BANCO = os.path.abspath(os.environ.get("BANCO_TESTE", os.path.join(RAIZ, ".tmp", "frequencyon-teste.db")))
TMP = os.path.dirname(BANCO)

SENHA_ADMIN = "Admin@Teste2026"
SENHA_PROFESSOR = "Prof@Teste2026"
SENHA_ALUNO = "Aluno@Teste2026"
DIA_REGRAS = date(2026, 11, 2)       # segunda-feira usada nos casos de regra de presença

sys.path.insert(0, PROJETO)


_apps = {}


def _app(banco=None):
    """App Flask mínimo ligado ao banco de teste (só modelos, sem rotas nem câmera).
    Dentro do servidor de teste é criado uma vez só por banco."""
    banco = banco or BANCO
    if banco not in _apps:
        from email_service import carregar_env
        carregar_env(os.path.join(PROJETO, ".env"))
        os.environ.setdefault("FREQUENCYON_DATA", "")
        from flask import Flask
        import database
        app = Flask("ponte")
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + banco.replace("\\", "/")
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"timeout": 15}}
        database.db.init_app(app)
        _apps[banco] = (app, database)
    return _apps[banco]


def _aluno(d, matricula):
    a = d.Aluno.query.filter_by(matricula=matricula).first()
    if not a:
        raise ValueError(f"aluno {matricula} não existe no banco de teste")
    return a


def _linha_dia(d, aluno, dia):
    """Aulas do dia em uma linha: P presente, A atraso, F falta, · sem registro."""
    n = aluno.turma.aulas_por_dia if aluno.turma else 0
    regs = {p.aula: p.status for p in d.Presenca.query.filter_by(aluno_id=aluno.id, data=dia)}
    letra = {"presente": "P", "atraso": "A", "falta": "F"}
    return "".join(letra.get(regs.get(i), "·") for i in range(n))


# ---------------------------------------------------------------------
# preparação: cópia do banco + massa de dados de teste
# ---------------------------------------------------------------------
def preparar(_dados):
    os.makedirs(TMP, exist_ok=True)
    for nome in ("caixa_saida.jsonl",):
        if os.path.exists(os.path.join(TMP, nome)):
            os.remove(os.path.join(TMP, nome))
    shutil.rmtree(os.path.join(TMP, "uploads"), ignore_errors=True)
    os.makedirs(os.path.join(TMP, "uploads"))
    for sufixo in ("", "-journal", "-wal", "-shm"):
        if os.path.exists(BANCO + sufixo):
            os.remove(BANCO + sufixo)

    # cópia consistente do banco do projeto (funciona mesmo com o sistema aberto)
    origem = sqlite3.connect(f"file:{os.path.join(PROJETO, 'instance', 'frequencyon.db')}?mode=ro", uri=True)
    destino = sqlite3.connect(BANCO)
    origem.backup(destino)
    origem.close()
    destino.close()

    app, d = _app()
    with app.app_context():
        d.db.create_all()
        d.migrar_horarios()
        d.migrar_dispositivos()
        d.migrar_professor_turma()
        db = d.db

        # senhas conhecidas só na cópia
        admin = d.Admin.query.filter_by(email="admin@senai.com").first()
        admin.set_senha(SENHA_ADMIN)
        bloqueio = d.Admin(nome="QA Bloqueio", email="qa.bloqueio@frequencyon.teste")
        bloqueio.set_senha(SENHA_ADMIN)
        db.session.add(bloqueio)
        carlos = d.Professor.query.filter_by(email="carlos@professor.senai.com").first()
        carlos.set_senha(SENHA_PROFESSOR)
        for m in ("2025002", "2025003"):
            _aluno(d, m).set_senha(SENHA_ALUNO)

        for nome, email in (("Professor Sem Turma", "prof.semturma@frequencyon.teste"),
                            ("Professor Editavel", "prof.editavel@frequencyon.teste")):
            p = d.Professor(nome=nome, email=email, departamento="QA")
            p.set_senha(SENHA_PROFESSOR)
            db.session.add(p)

        # horários: Técnico (do projeto) e CAI (criado se o banco não tiver)
        tecnico = d.ModeloHorario.query.filter(d.ModeloHorario.nome.like("Técnico%")).first()
        cai = d.ModeloHorario.query.filter(d.ModeloHorario.nome.like("CAI%")).first()
        if not cai:
            nome, aulas = next(m for m in d.MODELOS_PADRAO if m[0].startswith("CAI"))
            from datetime import time as dtime
            cai = d.ModeloHorario(nome=nome, aulas=[d.AulaHorario(inicio=dtime.fromisoformat(i), fim=dtime.fromisoformat(f),
                                                                    periodo=p) for i, f, p in aulas])
            db.session.add(cai)

        # turmas de teste; o Carlos dá aula em todas
        def turma(nome, curso, modelo, dias):
            t = d.Turma(nome=nome, curso=curso, modelo=modelo)
            t.vinculos.append(d.ProfessorTurma(professor=carlos, dias=dias))
            db.session.add(t)
            return t

        t99 = turma("C99", "Teste Regras de Presença", tecnico, "0,1,2,3,4")
        t98 = turma("C98", "Teste CAI", cai, "0,1,2,3,4")
        t97 = turma("C97", "Teste Chamada", tecnico, "0,1,2,3,4,5,6")   # todo dia tem aula: a chamada de hoje sempre abre
        t96 = turma("C96", "Teste Área do Aluno", tecnico, "0,1,2,3,4")

        alunos = (
            ("Regra Antes da Aula", "9100001", t99), ("Regra Atraso", "9100002", t99),
            ("Regra Meio da Aula", "9100003", t99), ("Regra Domingo", "9100004", t99),
            ("Regra Fim do Dia", "9100005", t99), ("Regra Chamada Professor", "9100006", t99),
            ("Regra CAI", "9100010", t98),
            ("Chamada Um", "9200001", t97), ("Chamada Dois", "9200002", t97), ("Chamada Tres", "9200003", t97),
            ("Justifica Falta", "9300001", t96), ("Justifica Presente", "9300002", t96),
            ("Justifica Motivo", "9300003", t96),
            ("Aluno Avulso", "9400001", None), ("Aluno Excluir", "9400002", None),
            ("Aluno Cadastro Rosto", "9400003", None),
        )
        for i, (nome, matricula, t) in enumerate(alunos, 1):
            a = d.Aluno(nome=nome, matricula=matricula, email=f"{matricula}@aluno.teste", numero_chamada=i, turma=t)
            a.set_senha(SENHA_ALUNO)
            db.session.add(a)
        db.session.flush()

        # o aluno que será excluído já tem presenças
        excluir = _aluno(d, "9400002")
        for aula in range(3):
            db.session.add(d.Presenca(aluno_id=excluir.id, data=DIA_REGRAS, aula=aula, status="presente", origem="totem"))
        db.session.commit()

    # certificado HTTPS só dos testes (em .tmp, não mexe no da pasta instance do projeto);
    # gerado aqui para os dois servidores não gerarem ao mesmo tempo
    from certificado import certificado_local
    certificado_local(os.path.join(TMP, "certificado"))
    return {"banco": BANCO}


# ---------------------------------------------------------------------
# consultas e regras (cada uma devolve um dicionário)
# ---------------------------------------------------------------------
def hoje(_dados):
    app, d = _app()
    h = d.hoje_local()
    ontem_util = h - timedelta(days=1)
    segunda = h - timedelta(days=h.weekday() or 7)     # segunda-feira anterior a hoje
    return {"hoje": h.isoformat(), "amanha": (h + timedelta(days=1)).isoformat(),
            "ontem": ontem_util.isoformat(), "segunda_passada": segunda.isoformat(),
            "dia_regras": DIA_REGRAS.isoformat()}


def registrar_totem(dados):
    """Chama a mesma função que o totem usa, com o horário escolhido pelo teste."""
    app, d = _app()
    with app.app_context():
        aluno = _aluno(d, dados["matricula"])
        quando = datetime.fromisoformat(dados["quando"])
        status, ja, info = d.registrar_presenca_totem(aluno, quando)
        return {"status": status, "ja_registrado": ja, "mensagem": info.get("mensagem", ""),
                "dia": _linha_dia(d, aluno, quando.date()),
                "registros": d.Presenca.query.filter_by(aluno_id=aluno.id, data=quando.date()).count()}


def linha_dia(dados):
    app, d = _app()
    with app.app_context():
        aluno = _aluno(d, dados["matricula"])
        return {"dia": _linha_dia(d, aluno, date.fromisoformat(dados["data"]))}


def lancar(dados):
    """Arranjo: grava uma presença como se o professor tivesse lançado (pré-condição de caso)."""
    app, d = _app()
    with app.app_context():
        aluno = _aluno(d, dados["matricula"])
        d.db.session.add(d.Presenca(aluno_id=aluno.id, data=date.fromisoformat(dados["data"]), aula=dados["aula"],
                                    status=dados["status"], origem=dados.get("origem", "professor")))
        d.db.session.commit()
        return {"ok": True}


def presenca(dados):
    app, d = _app()
    with app.app_context():
        aluno = _aluno(d, dados["matricula"])
        p = d.Presenca.query.filter_by(aluno_id=aluno.id, data=date.fromisoformat(dados["data"]), aula=dados["aula"]).first()
        if not p:
            return {"existe": False}
        return {"existe": True, "status": p.status, "origem": p.origem, "data": p.data.isoformat(),
                "hora": p.registrado_em.strftime("%H:%M") if p.registrado_em else None}


def alteracoes(dados):
    app, d = _app()
    with app.app_context():
        aluno = _aluno(d, dados["matricula"])
        q = d.AlteracaoPresenca.query.filter_by(aluno_id=aluno.id, data=date.fromisoformat(dados["data"]),
                                                aula=dados["aula"]).order_by(d.AlteracaoPresenca.id)
        return {"alteracoes": [{"professor": a.professor_nome, "anterior": a.status_anterior, "novo": a.status_novo,
                                "com_senha_admin": a.com_senha_admin, "alterado_em": a.alterado_em.isoformat()}
                               for a in q]}


def aluno(dados):
    app, d = _app()
    with app.app_context():
        a = d.Aluno.query.filter_by(matricula=dados["matricula"]).first()
        if not a:
            return {"existe": False}
        r = {"existe": True, "id": a.id, "nome": a.nome, "numero_chamada": a.numero_chamada,
             "turma": a.turma.nome if a.turma else None, "turma_curso": a.turma.curso if a.turma else None,
             "turma_id": a.turma_id, "foto": a.foto, "tem_rosto": a.face_encoding is not None,
             "frequencia": a.frequencia, "presencas": len(a.presencas)}
        if "senha" in dados:
            r["senha_confere"] = a.check_senha(dados["senha"])
        return r


def aluno_por_id(dados):
    app, d = _app()
    with app.app_context():
        a = d.db.session.get(d.Aluno, dados["id"])
        return {"existe": a is not None,
                "presencas": d.Presenca.query.filter_by(aluno_id=dados["id"]).count()}


def professores_com_email(dados):
    app, d = _app()
    with app.app_context():
        email = dados["email"].lower()
        return {"quantidade": d.Professor.query.filter(d.db.func.lower(d.Professor.email) == email).count()}


def professor(dados):
    app, d = _app()
    with app.app_context():
        p = d.Professor.query.filter_by(email=dados["email"]).first()
        return {"existe": bool(p), "nome": p and p.nome, "departamento": p and p.departamento,
                "foto": p and p.foto}


def senha_hash(dados):
    app, d = _app()
    with app.app_context():
        u = d.Admin.query.filter_by(email=dados["email"]).first()
        return {"hash": u.senha_hash}


def turma(dados):
    app, d = _app()
    with app.app_context():
        q = d.Turma.query.filter_by(nome=dados["nome"])
        if dados.get("curso"):
            q = q.filter_by(curso=dados["curso"])
        t = q.first()
        if not t:
            return {"existe": False}
        return {"existe": True, "id": t.id, "aulas_por_dia": t.aulas_por_dia,
                "modelo": t.modelo.nome if t.modelo else None, "alunos": [a.matricula for a in t.alunos]}


def modelo(dados):
    app, d = _app()
    with app.app_context():
        m = d.ModeloHorario.query.filter(d.ModeloHorario.nome.like(dados["nome"] + "%")).first()
        return {"id": m.id, "nome": m.nome, "turmas": len(m.turmas),
                "aulas": [[a.inicio.strftime("%H:%M"), a.fim.strftime("%H:%M"), a.periodo] for a in m.aulas]}


def horarios_banco_novo(_dados):
    """Sobe o esquema num banco vazio e lista os horários que o sistema cria sozinho."""
    pasta = tempfile.mkdtemp(prefix="frequencyon-novo-")
    banco = os.path.join(pasta, "novo.db")
    try:
        app, d = _app(banco)
        with app.app_context():
            d.db.create_all()
            d.migrar_horarios()
            r = {"modelos": [{"nome": m.nome, "aulas": len(m.aulas), "resumo": m.resumo}
                             for m in d.ModeloHorario.query.order_by(d.ModeloHorario.id)]}
            d.db.session.remove()
            d.db.engine.dispose()
        return r
    finally:
        _apps.pop(banco, None)
        shutil.rmtree(pasta, ignore_errors=True)


def dispositivo(dados):
    app, d = _app()
    with app.app_context():
        x = d.Dispositivo.query.filter_by(nome=dados["nome"]).first()
        if not x:
            return {"existe": False}
        return {"existe": True, "ativado": x.ativado_em is not None, "liberado": x.liberado,
                "liberado_por": x.liberado_por,
                "liberado_ate": x.liberado_ate.strftime("%H:%M:%S") if x.liberado_ate else None}


def vencer_codigo(dados):
    """Arranjo do CT-70: faz o código de ativação ter vencido (validade de 24 h já passou)."""
    app, d = _app()
    with app.app_context():
        x = d.Dispositivo.query.filter_by(nome=dados["nome"]).first()
        x.codigo_ate = d.agora_local() - timedelta(minutes=1)
        d.db.session.commit()
        return {"ok": True}


def justificativa(dados):
    app, d = _app()
    with app.app_context():
        a = _aluno(d, dados["matricula"])
        j = d.Justificativa.query.filter_by(aluno_id=a.id, data=date.fromisoformat(dados["data"])).first()
        return {"existe": bool(j), "status": j and j.status}


def caixa_saida(_dados):
    """E-mails que o sistema tentou mandar durante os testes (o envio real fica desligado)."""
    caminho = os.path.join(TMP, "caixa_saida.jsonl")
    if not os.path.exists(caminho):
        return {"emails": []}
    with open(caminho, encoding="utf-8") as f:
        return {"emails": [json.loads(l) for l in f if l.strip()]}


def risco(_dados):
    app, d = _app()
    with app.app_context():
        alunos = [a for a in d.Aluno.query.all() if a.presencas]
        return {"abaixo": sorted(a.nome for a in alunos if a.frequencia < 75),
                "acima": sorted(a.nome for a in alunos if a.frequencia >= 75)}


def abas_xlsx(dados):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(base64.b64decode(dados["base64"])))
    return {"abas": wb.sheetnames}


def foto(dados):
    """Caminho do arquivo da foto cadastrada (aluno pela matrícula ou professor pelo e-mail)."""
    app, d = _app()
    with app.app_context():
        pessoa = (d.Aluno.query.filter_by(matricula=dados["matricula"]).first() if "matricula" in dados
                  else d.Professor.query.filter_by(email=dados["email"]).first())
        caminho = os.path.join(PROJETO, "static", "uploads", os.path.basename(pessoa.foto))
        return {"url": pessoa.foto, "caminho": caminho, "existe": os.path.isfile(caminho)}


def caminho_projeto(dados):
    return {"caminho": os.path.join(PROJETO, *dados["partes"])}


def encoding_foto(dados):
    """CT-78/80: calcula o encoding de uma foto e compara com o rosto salvo de um aluno."""
    import numpy as np
    from face_service import encoding_de_arquivo
    inicio = time.time()
    enc = encoding_de_arquivo(dados["caminho"])
    segundos = round(time.time() - inicio, 2)
    r = {"encontrou_rosto": enc is not None, "segundos": segundos}
    if enc is not None and dados.get("matricula"):
        app, d = _app()
        with app.app_context():
            salvo = np.frombuffer(_aluno(d, dados["matricula"]).face_encoding, dtype=np.float64)
            r["distancia"] = round(float(np.linalg.norm(salvo - enc)), 3)
    return r


def distancia_alunos(dados):
    """CT-79: distância entre os rostos salvos de dois alunos."""
    import numpy as np
    app, d = _app()
    with app.app_context():
        a, b = (np.frombuffer(_aluno(d, m).face_encoding, dtype=np.float64) for m in (dados["a"], dados["b"]))
        return {"distancia": round(float(np.linalg.norm(a - b)), 3)}


ACOES = {f.__name__: f for f in (
    preparar, hoje, registrar_totem, linha_dia, lancar, presenca, alteracoes, aluno, aluno_por_id,
    professores_com_email, professor, senha_hash, turma, modelo, horarios_banco_novo, dispositivo, vencer_codigo,
    justificativa, caixa_saida, risco, abas_xlsx, foto, caminho_projeto, encoding_foto, distancia_alunos)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    acao = sys.argv[1]
    # os dados vêm pela entrada padrão (a planilha em base64 não cabe na linha de comando do Windows)
    dados = json.loads(sys.stdin.read() or "{}")
    resultado = ACOES[acao](dados)
    print(json.dumps(resultado, ensure_ascii=False, default=str))
