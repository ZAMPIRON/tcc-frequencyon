# api rest de leitura (RNF11) para integrar com o sistema de gestao da escola (erp)
# autenticacao: cabecalho "Authorization: Bearer <FREQUENCYON_API_TOKEN do .env>"; sem token no .env a api fica desligada
# nunca devolve senha, foto ou rosto (dados biometricos ficam so no frequencyon)
import os
import secrets
from datetime import date
from functools import wraps

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from database import db, Aluno, Presenca, Turma, agora_local
from .comum import pegar_totem

api = Blueprint("api", __name__, url_prefix="/api/v1")


def requer_token(f):
    @wraps(f)
    def wrapper(*a, **kw):
        token = os.getenv("FREQUENCYON_API_TOKEN", "")
        if not token:
            return jsonify(erro="API desligada: defina FREQUENCYON_API_TOKEN no .env."), 404
        enviado = request.headers.get("Authorization", "")
        enviado = enviado[7:] if enviado.startswith("Bearer ") else ""
        if not secrets.compare_digest(enviado.encode(), token.encode()):
            return jsonify(erro="Token inválido."), 401, {"WWW-Authenticate": "Bearer"}
        return f(*a, **kw)
    return wrapper


def _periodo():
    try:
        inicio = date.fromisoformat(request.args["inicio"]) if request.args.get("inicio") else None
        fim = date.fromisoformat(request.args["fim"]) if request.args.get("fim") else None
    except ValueError:
        return None, None, "Use datas no formato AAAA-MM-DD."
    return inicio, fim, None


def _aluno_json(a, inicio=None, fim=None):
    return {"id": a.id, "nome": a.nome, "matricula": a.matricula, "email": a.email, "numero_chamada": a.numero_chamada,
            "turma_id": a.turma_id, "frequencia": a.frequencia_periodo(inicio, fim)}


@api.route("/turmas")
@requer_token
def turmas():
    return jsonify([{"id": t.id, "nome": t.nome, "curso": t.curso, "horario": t.modelo.nome if t.modelo else None,
                     "aulas_por_dia": t.aulas_por_dia, "dias_aula": t.dias_aula_nomes, "alunos": len(t.alunos),
                     "frequencia_media": t.frequencia_media}
                    for t in Turma.query.order_by(Turma.nome, Turma.curso)])


@api.route("/alunos")
@requer_token
def alunos():
    q = Aluno.query
    if request.args.get("turma_id"):
        q = q.filter_by(turma_id=request.args.get("turma_id", type=int))
    return jsonify([_aluno_json(a) for a in q.order_by(Aluno.nome)])


@api.route("/frequencia")
@requer_token
def frequencia():
    inicio, fim, erro = _periodo()
    if erro:
        return jsonify(erro=erro), 400
    q = Aluno.query.filter(Aluno.turma_id.isnot(None))
    if request.args.get("turma_id"):
        q = q.filter_by(turma_id=request.args.get("turma_id", type=int))
    return jsonify({"inicio": inicio.isoformat() if inicio else None, "fim": fim.isoformat() if fim else None,
                    "alunos": [_aluno_json(a, inicio, fim) for a in q.order_by(Aluno.nome)]})


@api.route("/alunos/<int:aluno_id>/presencas")
@requer_token
def presencas(aluno_id):
    a = db.session.get(Aluno, aluno_id)
    if not a:
        return jsonify(erro="Aluno não encontrado."), 404
    inicio, fim, erro = _periodo()
    if erro:
        return jsonify(erro=erro), 400
    q = Presenca.query.filter_by(aluno_id=a.id)
    if inicio:
        q = q.filter(Presenca.data >= inicio)
    if fim:
        q = q.filter(Presenca.data <= fim)
    return jsonify({"aluno": _aluno_json(a, inicio, fim),
                    "presencas": [{"data": p.data.isoformat(), "aula": p.aula + 1, "status": p.status, "origem": p.origem,
                                   "registrado_em": p.registrado_em.isoformat(timespec="seconds") if p.registrado_em else None}
                                  for p in q.order_by(Presenca.data, Presenca.aula)]})


@api.route("/saude")
def saude():
    # monitoramento (RNF16): ferramentas como UptimeRobot ou Zabbix podem chamar esta rota; 503 = algo errado
    from tarefas import tem_aula_agora, totens_sem_sinal
    try:
        db.session.execute(text("SELECT 1"))
        banco = "ok"
    except Exception:
        banco = "erro"
    totem = pegar_totem()
    if totem.erro:
        reconhecimento = "erro: " + totem.erro
    elif totem._proc is None:
        reconhecimento = "aguardando o primeiro totem"
    else:
        reconhecimento = "ok" if totem._proc.is_alive() else "parado"
    agora = agora_local()
    caidos = totens_sem_sinal(agora) if banco == "ok" and tem_aula_agora(agora) else []
    ok = banco == "ok" and not reconhecimento.startswith(("erro", "parado")) and not caidos
    return jsonify(status="ok" if ok else "degradado", banco=banco, reconhecimento=reconhecimento,
                   totens_sem_sinal=[{"nome": d.nome, "minutos": m} for d, m in caidos],
                   horario=agora.isoformat(timespec="seconds")), 200 if ok else 503
