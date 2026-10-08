"""database.py - configuração do banco (SQLAlchemy) e modelos do FrequencyON."""
import os
from datetime import date, datetime, time, timedelta, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

AULAS_POR_DIA = 10
DIAS_SELECIONAVEIS = (0, 1, 2, 3, 4, 5)  # segunda a sábado (date.weekday())
NOMES_DIAS = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")

try:
    from zoneinfo import ZoneInfo
    FUSO_HORARIO = ZoneInfo("America/Sao_Paulo")
except Exception:
    # fallback para ambientes sem a base de fusos horários instalada
    FUSO_HORARIO = timezone(timedelta(hours=-3))


def agora_local():
    """Data/hora oficial usada pelo sistema no fuso de São Paulo."""
    return datetime.now(FUSO_HORARIO).replace(tzinfo=None)


DATA_SISTEMA = os.getenv("FREQUENCYON_DATA", "").strip()


def hoje_local():
    """Dia oficial do sistema no fuso de São Paulo.

    Para testes, FREQUENCYON_DATA pode forçar uma data no formato AAAA-MM-DD.
    Em produção, deixe a variável vazia para usar a data real do computador.
    """
    if DATA_SISTEMA:
        try:
            return date.fromisoformat(DATA_SISTEMA)
        except ValueError:
            pass
    return agora_local().date()


def eh_dia_com_aula(data, dias):
    """True se o dia da semana de `data` está em `dias` (valores de date.weekday())."""
    return data.weekday() in dias


def ultimo_dia_com_aula(data, dias):
    """Retorna o próprio dia, se tiver aula, ou o dia de aula anterior mais próximo.
    Sem dias definidos, devolve a própria data."""
    if not dias:
        return data
    while not eh_dia_com_aula(data, dias):
        data -= timedelta(days=1)
    return data


def filtro_dias_aula(coluna, dias):
    """Filtro SQL (SQLite) que mantém só registros em dias de aula.
    strftime('%w') usa domingo=0, então converte de date.weekday()."""
    return func.strftime("%w", coluna).in_([str((d + 1) % 7) for d in dias])


def dias_de_formulario(valores):
    """Converte a lista de checkboxes ("1", "3"...) em tupla ordenada de dias válidos."""
    dias = set()
    for v in valores:
        try:
            d = int(v)
        except (TypeError, ValueError):
            continue
        if d in DIAS_SELECIONAVEIS:
            dias.add(d)
    return tuple(sorted(dias))


def _hora_env(nome, padrao):
    h, m = os.getenv(nome, padrao).split(":")
    return time(int(h), int(m))


# Regras de horário do totem (mude aqui ou por variável de ambiente)
HORARIO_PRESENTE = _hora_env("HORARIO_PRESENTE", "07:05")  # até aqui = presente
HORARIO_ATRASO = _hora_env("HORARIO_ATRASO", "07:10")      # até aqui = atraso na 1ª aula

# Horário de início de cada aula. Altere esta lista para os horários reais da escola.
# Por padrão, são 10 aulas de 50 minutos começando às 07:00.
def _horarios_aulas_env():
    padrao = "07:00,07:50,08:40,09:30,10:20,11:10,12:00,12:50,13:40,14:30"
    valores = os.getenv("HORARIOS_AULAS", padrao).split(",")
    horarios = []
    for valor in valores[:AULAS_POR_DIA]:
        h, m = valor.strip().split(":")
        horarios.append(time(int(h), int(m)))
    return horarios

HORARIOS_AULAS = _horarios_aulas_env()


class UsuarioMixin:
    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)


class Admin(UsuarioMixin, db.Model):
    __tablename__ = "admins"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)
    foto = db.Column(db.String(255))


class Professor(UsuarioMixin, db.Model):
    __tablename__ = "professores"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)
    departamento = db.Column(db.String(120))
    foto = db.Column(db.String(255))
    vinculos = db.relationship("ProfessorTurma", back_populates="professor",
                               cascade="all, delete-orphan")

    @property
    def turmas(self):
        return sorted((v.turma for v in self.vinculos), key=lambda t: t.nome)

    def vinculo(self, turma_id):
        return next((v for v in self.vinculos if v.turma_id == turma_id), None)

    @property
    def media(self):
        v = [t.frequencia_media for t in self.turmas]
        return round(sum(v) / len(v)) if v else 0


class Turma(db.Model):
    __tablename__ = "turmas"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    curso = db.Column(db.String(120), nullable=False)
    alunos = db.relationship("Aluno", back_populates="turma")
    vinculos = db.relationship("ProfessorTurma", back_populates="turma",
                               cascade="all, delete-orphan")

    @property
    def professores(self):
        return sorted((v.professor for v in self.vinculos), key=lambda p: p.nome)

    @property
    def nomes_professores(self):
        return ", ".join(p.nome for p in self.professores) or "Sem professor"

    @property
    def dias_aula(self):
        """Dias com aula na turma: união dos dias de todos os professores."""
        return tuple(sorted({d for v in self.vinculos for d in v.dias_semana}))

    @property
    def dias_aula_nomes(self):
        return ", ".join(NOMES_DIAS[d] for d in self.dias_aula) or "Nenhum dia definido"

    @property
    def frequencia_media(self):
        v = [a.frequencia for a in self.alunos]
        return round(sum(v) / len(v), 1) if v else 0


class ProfessorTurma(db.Model):
    """Vínculo professor <-> turma com os dias da semana em que esse professor dá aula nela."""
    __tablename__ = "professor_turma"
    professor_id = db.Column(db.Integer, db.ForeignKey("professores.id"), primary_key=True)
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"), primary_key=True)
    dias = db.Column(db.String(20), nullable=False, default="")   # ex: "1,3" = terça e quinta
    professor = db.relationship("Professor", back_populates="vinculos")
    turma = db.relationship("Turma", back_populates="vinculos")

    @property
    def dias_semana(self):
        return tuple(int(d) for d in self.dias.split(",") if d.strip().isdigit())

    @dias_semana.setter
    def dias_semana(self, valores):
        self.dias = ",".join(str(d) for d in sorted(set(valores)))

    @property
    def dias_nomes(self):
        return ", ".join(NOMES_DIAS[d] for d in self.dias_semana) or "Nenhum dia definido"


class Aluno(UsuarioMixin, db.Model):
    __tablename__ = "alunos"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120))
    matricula = db.Column(db.String(30), unique=True, nullable=False, index=True)
    numero_chamada = db.Column(db.Integer)
    senha_hash = db.Column(db.String(255), nullable=False)
    foto = db.Column(db.String(255))            # URL da foto (ex: /static/uploads/...)
    face_encoding = db.Column(db.LargeBinary)   # 128 floats (float64) do rosto
    turma_id = db.Column(db.Integer, db.ForeignKey("turmas.id"))
    turma = db.relationship("Turma", back_populates="alunos")
    presencas = db.relationship("Presenca", cascade="all, delete-orphan", backref="aluno")
    justificativas = db.relationship("Justificativa", cascade="all, delete-orphan", backref="aluno",
                                     order_by="Justificativa.data.desc()")

    @property
    def frequencia(self):
        """% de aulas presentes/atraso nos dias em que houve chamada na turma."""
        if not self.turma_id:
            return 0

        dias_aula = self.turma.dias_aula
        if not dias_aula:
            return 0

        # Um dia entra no cálculo quando existe pelo menos um lançamento
        # de presença/falta para algum aluno da mesma turma.
        dias = (db.session.query(func.count(func.distinct(Presenca.data)))
                .join(Aluno, Presenca.aluno_id == Aluno.id)
                .filter(Aluno.turma_id == self.turma_id,
                        filtro_dias_aula(Presenca.data, dias_aula))
                .scalar())

        if not dias:
            return 0

        ok = (db.session.query(func.count(Presenca.id))
              .filter(
                  Presenca.aluno_id == self.id,
                  Presenca.status.in_(("presente", "atraso")),
                  filtro_dias_aula(Presenca.data, dias_aula)
              )
              .scalar())

        return min(100, round(ok * 100 / (dias * AULAS_POR_DIA)))

class Presenca(db.Model):
    """Uma linha por aluno / dia / aula (0..9). status: presente | atraso | falta."""
    __tablename__ = "presencas"
    __table_args__ = (db.UniqueConstraint("aluno_id", "data", "aula"),)
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False, index=True)
    data = db.Column(db.Date, nullable=False, index=True)
    aula = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(10), nullable=False)
    origem = db.Column(db.String(10), default="totem")   # totem | professor
    registrado_em = db.Column(db.DateTime, default=agora_local)


class Justificativa(db.Model):
    """Pedido do aluno para justificar as faltas de um dia. status: pendente | aceita | recusada."""
    __tablename__ = "justificativas"
    __table_args__ = (db.UniqueConstraint("aluno_id", "data"),)
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey("alunos.id"), nullable=False, index=True)
    data = db.Column(db.Date, nullable=False)
    motivo = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(10), nullable=False, default="pendente")
    criada_em = db.Column(db.DateTime, default=agora_local)
    respondida_em = db.Column(db.DateTime)


def status_por_horario(agora=None):
    agora = agora or agora_local()
    t = agora.time()
    if t <= HORARIO_PRESENTE:
        return "presente"
    if t <= HORARIO_ATRASO:
        return "atraso"
    return "falta"


def aula_atual_por_horario(agora=None):
    """Retorna o índice (0..9) da aula em andamento no momento."""
    agora = agora or agora_local()
    t = agora.time()

    atual = 0
    for indice, inicio in enumerate(HORARIOS_AULAS):
        if t >= inicio:
            atual = indice
        else:
            break
    return atual


def registrar_presenca_totem(aluno, agora=None):
    """
    Registra a entrada do aluno somente no dia atual e uma vez por dia.

    Aulas anteriores ao momento do reconhecimento ficam como falta.
    A aula em andamento e as próximas ficam como presente.
    """
    agora = agora or agora_local()
    hoje = agora.date()

    if not aluno.turma or not eh_dia_com_aula(hoje, aluno.turma.dias_aula):
        return "sem_aula", False

    primeira = Presenca.query.filter_by(
        aluno_id=aluno.id,
        data=hoje,
        aula=0
    ).first()

    if primeira:
        return primeira.status, True

    aula_atual = aula_atual_por_horario(agora)
    status_entrada = status_por_horario(agora)

    for aula in range(AULAS_POR_DIA):
        if aula < aula_atual:
            estado = "falta"
        elif aula == 0 and status_entrada == "atraso":
            estado = "atraso"
        else:
            estado = "presente"

        db.session.add(
            Presenca(
                aluno_id=aluno.id,
                data=hoje,
                aula=aula,
                status=estado,
                origem="totem",
                registrado_em=agora
            )
        )

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        primeira = Presenca.query.filter_by(
            aluno_id=aluno.id,
            data=hoje,
            aula=0
        ).first()
        if primeira:
            return primeira.status, True
        raise

    if aula_atual > 0:
        return "presente", False
    return status_entrada, False


def migrar_professor_turma():
    """Bancos antigos tinham turmas.professor_id (1 professor por turma).
    Copia esses vínculos para professor_turma com os dias antigos (terça e quinta)."""
    from sqlalchemy import inspect, text
    colunas = [c["name"] for c in inspect(db.engine).get_columns("turmas")]
    if "professor_id" not in colunas:
        return
    linhas = db.session.execute(
        text("SELECT id, professor_id FROM turmas WHERE professor_id IS NOT NULL")).all()
    for turma_id, professor_id in linhas:
        if db.session.get(Professor, professor_id) and not db.session.get(
                ProfessorTurma, (professor_id, turma_id)):
            db.session.add(ProfessorTurma(professor_id=professor_id, turma_id=turma_id, dias="1,3"))
    db.session.execute(text("UPDATE turmas SET professor_id = NULL"))
    db.session.commit()
