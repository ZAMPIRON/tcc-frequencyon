# painel da coordenacao: dashboard, cadastros, turmas, risco de evasao e justificativas
# os relatorios e a planilha ficam em relatorios.py pra esse arquivo nao crescer demais
import os
import uuid

import cv2
import secrets

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import or_

from database import (db, Aluno, Dispositivo, Justificativa, Professor, ProfessorTurma, Turma,
                      DIAS_SELECIONAVEIS, NOMES_DIAS, agora_local, dias_de_formulario)
from .aluno import exportar_csv, render_detalhes
from face_service import encoding_de_imagens
from .comum import encoding_de_foto, pasta_uploads, pegar_totem, requer, salvar_foto
from .totem import _hash, gerar_codigo_ativacao

admin = Blueprint("admin", __name__, url_prefix="/admin")


# ---------- dashboard ----------

@admin.route("/")
@admin.route("/dashboard")
@requer("admin")
def dashboard():
    turmas, alunos = Turma.query.all(), Aluno.query.all()
    por_curso = {}
    for t in turmas:
        por_curso.setdefault(t.curso, []).append(t.frequencia_media)
    # aluno sem turma não tem frequência (seria 0%), então fica fora da média
    freqs = [a.frequencia for a in alunos if a.turma_id]
    return render_template(
        "admin/dashboard.html",
        total_alunos=len(alunos), total_professores=Professor.query.count(),
        total_turmas=len(turmas),
        frequencia_geral=round(sum(freqs) / len(freqs)) if freqs else 0,
        frequencia_por_curso=[(c, sum(v) / len(v)) for c, v in por_curso.items()],
        turmas_criticas=sorted(turmas, key=lambda t: t.frequencia_media)[:5],
        alunos_em_risco=sum(1 for x in alunos if x.presencas and x.frequencia < 75))


@admin.route("/risco-evasao")
@requer("admin")
def risco_evasao():
    # todo mundo abaixo de 75%, do pior pro melhor
    # quem ainda nao tem nenhum registro fica de fora
    em_risco = [a for a in Aluno.query.all() if a.presencas and a.frequencia < 75]
    return render_template("admin/risco_evasao.html", alunos=sorted(em_risco, key=lambda a: a.frequencia))


# ---------- alunos ----------

@admin.route("/alunos")
@requer("admin")
def alunos():
    busca = request.args.get("busca", "").strip()
    q = Aluno.query
    if busca:
        q = q.filter(or_(Aluno.nome.ilike(f"%{busca}%"), Aluno.matricula.ilike(f"%{busca}%")))
    return render_template("admin/alunos.html", alunos=q.order_by(Aluno.nome).all(), busca=busca)


@admin.route("/alunos/novo", methods=["GET", "POST"])
@requer("admin")
def novo_aluno():
    if request.method == "POST":
        f = request.form
        if Aluno.query.filter_by(matricula=f["matricula"].strip()).first():
            flash("Já existe um aluno com essa matrícula.", "danger")
            return redirect(url_for("admin.novo_aluno"))
        a = Aluno(nome=f["nome"].strip(), email=f.get("email"), matricula=f["matricula"].strip(),
                  numero_chamada=int(f["numero_chamada"]) if f.get("numero_chamada") else None,
                  turma_id=int(f["turma_id"]) if f.get("turma_id") else None)
        a.set_senha(f["senha"])
        a.foto = salvar_foto(request.files.get("foto"))
        a.face_encoding = encoding_de_foto(a.foto)  # ja deixa o rosto pronto pro totem
        db.session.add(a)
        db.session.commit()
        pegar_totem().recarregar()
        if a.foto and not a.face_encoding:
            flash("Aluno cadastrado, mas não achei um rosto único na foto. "
                  "Cadastre o rosto pelo totem.", "warning")
        else:
            flash("Aluno cadastrado com sucesso!", "success")
        return redirect(url_for("admin.alunos"))
    return render_template("admin/cadastro_aluno.html", turmas=Turma.query.all())


@admin.route("/alunos/<int:id>")
@requer("admin")
def detalhes_aluno(id):
    # a mesma tela que o aluno ve, mas com os botoes de aceitar/recusar justificativa
    return render_detalhes(db.get_or_404(Aluno, id), "admin")


@admin.route("/alunos/<int:id>/exportar")
@requer("admin")
def exportar_aluno(id):
    return exportar_csv(db.get_or_404(Aluno, id))


@admin.route("/alunos/<int:id>/deletar", methods=["POST"])
@requer("admin")
def deletar_aluno(id):
    db.session.delete(db.get_or_404(Aluno, id))
    db.session.commit()
    pegar_totem().recarregar()  # tira o rosto dele da memoria do totem
    flash("Aluno removido.", "success")
    return redirect(url_for("admin.alunos"))


# ---------- professores ----------

@admin.route("/professores", methods=["GET", "POST"])
@requer("admin")
def professores():
    if request.method == "POST":
        f = request.form
        if Professor.query.filter_by(email=f["email"]).first():
            flash("Já existe um professor com esse e-mail.", "danger")
        else:
            p = Professor(nome=f["nome"], email=f["email"], departamento=f.get("departamento"),
                          foto=salvar_foto(request.files.get("foto")))
            p.set_senha(f["senha"])
            db.session.add(p)
            db.session.commit()
            flash("Professor cadastrado! Agora cadastre o rosto dele: é com ele que o totem é liberado.", "success")
            return redirect(url_for("admin.rosto_professor", id=p.id))
        return redirect(url_for("admin.professores"))
    return render_template("admin/professores.html", professores=Professor.query.order_by(Professor.nome).all())


@admin.route("/professores/<int:id>/rosto", methods=["GET", "POST"])
@requer("admin")
def rosto_professor(id):
    # tela tipo totem: a camera do computador do admin tira umas fotos e guarda o rosto do professor
    p = db.get_or_404(Professor, id)
    if request.method == "GET":
        return render_template("admin/rosto_professor.html", professor=p)
    fotos = [f.read() for f in request.files.getlist("fotos")[:8]]
    enc, frame = encoding_de_imagens([f for f in fotos if f and len(f) <= 600 * 1024])
    if enc is None:
        return jsonify(sucesso=False, mensagem=frame), 422
    p.face_encoding = enc.tobytes()
    if not p.foto:
        nome = f"{uuid.uuid4().hex}.jpg"
        cv2.imwrite(os.path.join(pasta_uploads(), nome), frame)
        p.foto = f"/static/uploads/{nome}"
    db.session.commit()
    pegar_totem().recarregar()
    return jsonify(sucesso=True, mensagem=f"Rosto de {p.nome} cadastrado! Ele já pode liberar o totem.")


@admin.route("/professores/<int:id>/deletar", methods=["POST"])
@requer("admin")
def deletar_professor(id):
    p = db.get_or_404(Professor, id)
    db.session.delete(p)  # os vinculos com as turmas vao embora junto
    db.session.commit()
    pegar_totem().recarregar()   # o rosto dele para de liberar o totem
    return redirect(url_for("admin.professores"))


# ---------- turmas ----------

@admin.route("/turmas", methods=["GET", "POST"])
@requer("admin")
def turmas():
    if request.method == "POST":
        f = request.form
        turma = Turma(nome=f["nome"], curso=f["curso"])
        # os professores entram sem dias, o admin escolhe os dias depois nos detalhes da turma
        for pid in set(f.getlist("professor_ids", type=int)):
            if db.session.get(Professor, pid):
                turma.vinculos.append(ProfessorTurma(professor_id=pid, dias=""))
        db.session.add(turma)
        db.session.commit()
        flash("Turma criada! Defina os dias de aula de cada professor nos detalhes da turma.", "success")
        return redirect(url_for("admin.turmas"))
    return render_template("admin/turmas.html", turmas=Turma.query.all(),
                           professores=Professor.query.order_by(Professor.nome).all())


@admin.route("/turmas/<int:id>")
@requer("admin")
def detalhes_turma(id):
    turma = db.get_or_404(Turma, id)
    vinculados = {v.professor_id for v in turma.vinculos}
    return render_template("admin/detalhes_turma.html", turma=turma,
                           alunos_sem_turma=Aluno.query.filter_by(turma_id=None).all(),
                           professores_disponiveis=[p for p in Professor.query.order_by(Professor.nome)
                                                    if p.id not in vinculados],
                           dias_opcoes=[(d, NOMES_DIAS[d]) for d in DIAS_SELECIONAVEIS])


@admin.route("/turmas/<int:id>/deletar", methods=["POST"])
@requer("admin")
def deletar_turma(id):
    t = db.get_or_404(Turma, id)
    # os alunos nao sao apagados, so ficam sem turma
    for a in t.alunos:
        a.turma_id = None
    db.session.delete(t)
    db.session.commit()
    return redirect(url_for("admin.turmas"))


@admin.route("/turmas/<int:turma_id>/adicionar", methods=["POST"])
@requer("admin")
def adicionar_aluno_turma(turma_id):
    aluno = db.get_or_404(Aluno, int(request.form["aluno_id"]))
    aluno.turma_id = turma_id
    db.session.commit()
    return redirect(url_for("admin.detalhes_turma", id=turma_id))


@admin.route("/alunos/<int:aluno_id>/desvincular", methods=["POST"])
@requer("admin")
def desvincular_aluno(aluno_id):
    aluno = db.get_or_404(Aluno, aluno_id)
    turma_id, aluno.turma_id = aluno.turma_id, None
    db.session.commit()
    return redirect(url_for("admin.detalhes_turma", id=turma_id) if turma_id else url_for("admin.turmas"))


# ---------- professor <-> turma ----------
# cada professor tem os seus dias em cada turma (ex: matematica ter/qui, ingles qua/sex)

@admin.route("/turmas/<int:turma_id>/professores", methods=["POST"])
@requer("admin")
def vincular_professor(turma_id):
    turma = db.get_or_404(Turma, turma_id)
    prof = db.get_or_404(Professor, request.form.get("professor_id", type=int))
    if not db.session.get(ProfessorTurma, (prof.id, turma.id)):
        v = ProfessorTurma(professor_id=prof.id, turma_id=turma.id)
        v.dias_semana = dias_de_formulario(request.form.getlist("dias"))
        db.session.add(v)
        db.session.commit()
        flash(f"{prof.nome} vinculado à turma.", "success")
    return redirect(url_for("admin.detalhes_turma", id=turma_id))


@admin.route("/turmas/<int:turma_id>/professores/<int:professor_id>/dias", methods=["POST"])
@requer("admin")
def dias_professor_turma(turma_id, professor_id):
    v = db.get_or_404(ProfessorTurma, (professor_id, turma_id))
    v.dias_semana = dias_de_formulario(request.form.getlist("dias"))
    db.session.commit()
    flash("Dias de aula atualizados.", "success")
    return redirect(url_for("admin.detalhes_turma", id=turma_id))


@admin.route("/turmas/<int:turma_id>/professores/<int:professor_id>/remover", methods=["POST"])
@requer("admin")
def desvincular_professor(turma_id, professor_id):
    db.session.delete(db.get_or_404(ProfessorTurma, (professor_id, turma_id)))
    db.session.commit()
    flash("Professor removido da turma.", "success")
    return redirect(url_for("admin.detalhes_turma", id=turma_id))


# ---------- justificativas ----------

@admin.route("/justificativas/<int:id>/<acao>", methods=["POST"])
@requer("admin")
def responder_justificativa(id, acao):
    j = db.get_or_404(Justificativa, id)
    if acao in ("aceita", "recusada"):
        j.status, j.respondida_em = acao, agora_local()
        db.session.commit()
        flash(f"Justificativa {acao}.", "success")
    return redirect(url_for("admin.detalhes_aluno", id=j.aluno_id))


# ---------- totens (tablets) ----------

@admin.route("/totens")
@requer("admin")
def totens():
    # totens criados pela coordenacao; cada um fica numa sala e e liberado por um professor dela a cada dia
    return render_template("admin/totens.html", modo=pegar_totem().fonte,
                           dispositivos=Dispositivo.query.order_by(Dispositivo.nome).all(),
                           turmas=Turma.query.order_by(Turma.nome).all(),
                           codigo_novo=session.pop("codigo_totem", None), agora=agora_local())


def _mostrar_codigo(disp):
    # o codigo aparece uma vez so na pagina (o banco guarda so o hash)
    session["codigo_totem"] = {"nome": disp.nome, "sala": disp.turma.nome if disp.turma else "",
                               "codigo": gerar_codigo_ativacao(disp)}
    db.session.commit()


@admin.route("/totens/novo", methods=["POST"])
@requer("admin")
def novo_totem():
    nome = (request.form.get("nome") or "").strip()
    turma = db.session.get(Turma, request.form.get("turma_id", type=int) or 0)
    if not nome or not turma:
        flash("Informe o nome do totem e a sala dele.", "danger")
        return redirect(url_for("admin.totens"))
    if Dispositivo.query.filter_by(nome=nome).first():
        flash(f"Já existe um totem chamado \"{nome}\".", "danger")
        return redirect(url_for("admin.totens"))
    # token sorteado e descartado: nenhum aparelho entra ate digitar o codigo de ativacao
    disp = Dispositivo(nome=nome, turma_id=turma.id, token_hash=_hash(secrets.token_urlsafe(32)))
    db.session.add(disp)
    db.session.flush()
    _mostrar_codigo(disp)
    return redirect(url_for("admin.totens"))


@admin.route("/totens/<int:id>/codigo", methods=["POST"])
@requer("admin")
def codigo_totem(id):
    # codigo novo: para ativar o primeiro tablet ou trocar o aparelho (o antigo perde o acesso ao ativar)
    _mostrar_codigo(db.get_or_404(Dispositivo, id))
    return redirect(url_for("admin.totens"))


@admin.route("/totens/<int:id>/sala", methods=["POST"])
@requer("admin")
def sala_totem(id):
    # define em que sala o totem fica: so os professores dessa turma conseguem libera-lo
    disp = db.get_or_404(Dispositivo, id)
    turma_id = request.form.get("turma_id", type=int)
    disp.turma_id = turma_id if turma_id and db.session.get(Turma, turma_id) else None
    db.session.commit()
    flash(f"Sala do \"{disp.nome}\": {disp.turma.nome if disp.turma else 'nenhuma'}.", "success")
    return redirect(url_for("admin.totens"))


@admin.route("/totens/<int:id>/remover", methods=["POST"])
@requer("admin")
def remover_totem(id):
    # o totem deixa de existir: o tablet dele perde o acesso na hora
    disp = db.get_or_404(Dispositivo, id)
    db.session.delete(disp)
    db.session.commit()
    flash(f"Totem \"{disp.nome}\" removido.", "success")
    return redirect(url_for("admin.totens"))
