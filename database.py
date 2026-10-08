"""database.py - configuração do banco (SQLAlchemy) e modelos do FrequencyON."""
import os
from datetime import date, datetime, time, timedelta, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

AULAS_POR_DIA = 10
DIAS_AULA = (0, 1, 2, 3, 4)  # segunda a sexta
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


def eh_dia_com_aula(data):
    """Considera aulas apenas de segunda a sexta."""
    return data.weekday() in DIAS_AULA


def _hora_env(nome, padrao):
    h, m = os.getenv(nome, padrao).split(":")
    return time(int(h), int(m))


# Regras de horário do totem (mude aqui ou por variável de ambiente)
HORARIO_PRESENTE = _hora_env("HORARIO_PRESENTE", "08:00")  # até aqui = presente
HORARIO_ATRASO = _hora_env("HORARIO_ATRASO", "08:03")      # até aqui = atraso; depois = falta


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
    turmas = db.relationship("Turma", back_populates="professor")

    @property
    def media(self):
        v = [t.frequencia_media for t in self.turmas]
        return round(sum(v) / len(v)) if v else 0


class Turma(db.Model):
    __tablename__ = "turmas"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    curso = db.Column(db.String(120), nullable=False)
    professor_id = db.Column(db.Integer, db.ForeignKey("professores.id"))
    professor = db.relationship("Professor", back_populates="turmas")
    alunos = db.relationship("Aluno", back_populates="turma")

    @property
    def frequencia_media(self):
        v = [a.frequencia for a in self.alunos]
        return round(sum(v) / len(v), 1) if v else 0


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

    @property
    def frequencia(self):
        """% de aulas presentes/atraso nos dias em que houve chamada na turma."""
        if not self.turma_id:
            return 0

        # Um dia entra no cálculo quando existe pelo menos um lançamento
        # de presença/falta para algum aluno da mesma turma.
        dias = (db.session.query(func.count(func.distinct(Presenca.data)))
                .join(Aluno, Presenca.aluno_id == Aluno.id)
                .filter(Aluno.turma_id == self.turma_id)
                .scalar())

        if not dias:
            return 0

        ok = (db.session.query(func.count(Presenca.id))
              .filter(
                  Presenca.aluno_id == self.id,
                  Presenca.status.in_(("presente", "atraso"))
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


def status_por_horario(agora=None):
    agora = agora or agora_local()
    t = agora.time()
    if t <= HORARIO_PRESENTE:
        return "presente"
    if t <= HORARIO_ATRASO:
        return "atraso"  # Considera presente mesmo que atrasado, para não prejudicar o aluno
    return "falta"


def registrar_presenca_totem(aluno, agora=None):
    """Registra a entrada do aluno somente no dia atual e uma vez por dia."""
    agora = agora or agora_local()
    hoje = agora.date()

    # sábado e domingo não são dias de aula do FrequencyON
    if not eh_dia_com_aula(hoje):
        return "sem_aula", False

    primeira = Presenca.query.filter_by(
        aluno_id=aluno.id,
        data=hoje,
        aula=0
    ).first()

    if primeira:
        return primeira.status, True

    status = status_por_horario(agora)

    for aula in range(AULAS_POR_DIA):
        estado = "presente" if (status == "atraso" and aula > 0) else status
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
        # Se dois reconhecimentos acontecerem ao mesmo tempo, a restrição única
        # do banco garante que não haverá dois registros para a mesma aula/dia.
        db.session.rollback()
        primeira = Presenca.query.filter_by(
            aluno_id=aluno.id,
            data=hoje,
            aula=0
        ).first()
        if primeira:
            return primeira.status, True
        raise

    return status, False