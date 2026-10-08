"""app.py - FrequencyON: create_app, rotas e integração do totem com o banco."""
import os
import uuid
from datetime import date, timedelta
from functools import wraps

import cv2
from flask import (Flask, Blueprint, render_template, request, redirect, url_for,
                   flash, session, jsonify, Response)
from sqlalchemy import or_

from database import (db, Admin, Professor, Turma, Aluno, Presenca, ProfessorTurma,
                      AULAS_POR_DIA, DIAS_SELECIONAVEIS, NOMES_DIAS,
                      hoje_local, eh_dia_com_aula, ultimo_dia_com_aula,
                      dias_de_formulario, migrar_professor_turma)
from face_service import Totem, encoding_de_arquivo

admin = Blueprint("admin", __name__, url_prefix="/admin")
professor = Blueprint("professor", __name__, url_prefix="/professor")
reconhecimento = Blueprint("reconhecimento", __name__)
totem = None  # definido em create_app


# ============================ helpers ============================
def salvar_foto(arquivo):
    """Salva upload em static/uploads e devolve a URL (ou None)."""
    if not arquivo or not arquivo.filename:
        return None
    ext = os.path.splitext(arquivo.filename)[1].lower() or ".jpg"
    nome = f"{uuid.uuid4().hex}{ext}"
    arquivo.save(os.path.join(UPLOAD_DIR(), nome))
    return f"/static/uploads/{nome}"


def UPLOAD_DIR():
    from flask import current_app
    return current_app.config["UPLOAD_DIR"]


def encoding_de_foto(url):
    """Gera o encoding facial a partir de uma foto já salva. None se não achar 1 rosto."""
    if not url:
        return None
    try:
        enc = encoding_de_arquivo(os.path.join(UPLOAD_DIR(), os.path.basename(url)))
        return enc.tobytes() if enc is not None else None
    except Exception as e:
        print(f"[foto] não consegui ler o rosto da foto: {e}")
        return None


def usuario_atual():
    tipo, uid = session.get("tipo"), session.get("uid")
    modelo = {"admin": Admin, "professor": Professor, "aluno": Aluno}.get(tipo)
    return db.session.get(modelo, uid) if modelo and uid else None


def requer(tipo):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            if session.get("tipo") != tipo or not usuario_atual():
                return redirect(url_for("login_admin" if tipo == "admin" else "login_professor"))
            return f(*a, **kw)
        return wrapper
    return deco


# ============================ TOTEM ============================
@reconhecimento.route("/totem")
def pagina_totem():
    totem.iniciar()
    return render_template("totem/reconhecimento.html")


@reconhecimento.route("/video_feed")
def video_feed():
    totem.iniciar()
    return Response(totem.stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


@reconhecimento.route("/api/reconhecimento")
def api_reconhecimento():
    ev = totem.proximo_evento()   # cada evento é entregue uma única vez
    return jsonify({"reconhecido": True, "dados": ev} if ev else {"reconhecido": False})


@reconhecimento.route("/api/cadastrar_foto", methods=["POST"])
def api_cadastrar_foto():
    try:
        matricula = ((request.get_json(silent=True) or {}).get("matricula") or "").strip()
        aluno = Aluno.query.filter_by(matricula=matricula).first()
        if not aluno:
            return jsonify(sucesso=False, mensagem="Matrícula não encontrada."), 404
        totem.iniciar()
        enc, frame = totem.capturar_encoding()
        if enc is None:
            return jsonify(sucesso=False, mensagem=frame), 422
        aluno.face_encoding = enc.tobytes()
        if not aluno.foto:  # usa a captura como foto de perfil
            nome = f"{uuid.uuid4().hex}.jpg"
            cv2.imwrite(os.path.join(UPLOAD_DIR(), nome), frame)
            aluno.foto = f"/static/uploads/{nome}"
        db.session.commit()
        totem.recarregar()
        return jsonify(sucesso=True, mensagem=f"Rosto de {aluno.nome} cadastrado com sucesso!")
    except Exception as e:
        db.session.rollback()
        print(f"[cadastrar_foto] erro: {e}")
        return jsonify(sucesso=False, mensagem="Erro interno ao cadastrar o rosto."), 500


# ============================ ADMIN ============================
@admin.route("/")
@admin.route("/dashboard")
@requer("admin")
def dashboard():
    turmas, alunos = Turma.query.all(), Aluno.query.all()
    por_curso = {}
    for t in turmas:
        por_curso.setdefault(t.curso, []).append(t.frequencia_media)
    freqs = [a.frequencia for a in alunos]
    return render_template(
        "admin/dashboard.html",
        total_alunos=len(alunos), total_professores=Professor.query.count(),
        total_turmas=len(turmas),
        frequencia_geral=round(sum(freqs) / len(freqs)) if freqs else 0,
        frequencia_por_curso=[(c, sum(v) / len(v)) for c, v in por_curso.items()],
        turmas_criticas=sorted(turmas, key=lambda t: t.frequencia_media)[:5],
        alunos_em_risco=sum(1 for x in alunos if x.presencas and x.frequencia < 75))


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
        a.face_encoding = encoding_de_foto(a.foto)     # já deixa o rosto pronto p/ o totem
        db.session.add(a)
        db.session.commit()
        totem.recarregar()
        if a.foto and not a.face_encoding:
            flash("Aluno cadastrado, mas não achei um rosto único na foto. "
                  "Cadastre o rosto pelo totem.", "warning")
        else:
            flash("Aluno cadastrado com sucesso!", "success")
        return redirect(url_for("admin.alunos"))
    return render_template("admin/cadastro_aluno.html", turmas=Turma.query.all())


@admin.route("/alunos/<int:id>/deletar", methods=["POST"])
@requer("admin")
def deletar_aluno(id):
    db.session.delete(db.get_or_404(Aluno, id))
    db.session.commit()
    totem.recarregar()
    flash("Aluno removido.", "success")
    return redirect(url_for("admin.alunos"))


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
            flash("Professor cadastrado!", "success")
        return redirect(url_for("admin.professores"))
    return render_template("admin/professores.html", professores=Professor.query.order_by(Professor.nome).all())


@admin.route("/professores/<int:id>/deletar", methods=["POST"])
@requer("admin")
def deletar_professor(id):
    p = db.get_or_404(Professor, id)
    db.session.delete(p)   # os vínculos com turmas são apagados junto
    db.session.commit()
    return redirect(url_for("admin.professores"))


@admin.route("/turmas", methods=["GET", "POST"])
@requer("admin")
def turmas():
    if request.method == "POST":
        f = request.form
        turma = Turma(nome=f["nome"], curso=f["curso"])
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


@admin.route("/turmas/<int:id>/deletar", methods=["POST"])
@requer("admin")
def deletar_turma(id):
    t = db.get_or_404(Turma, id)
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


@admin.route("/risco-evasao")
@requer("admin")
def risco_evasao():
    return render_template("admin/risco_evasao.html",
                           alunos=sorted([a for a in Aluno.query.all() if a.presencas and a.frequencia < 75],
                                         key=lambda a: a.frequencia))


@admin.route("/relatorios")
@requer("admin")
def relatorios():
    alunos, turmas = Aluno.query.all(), Turma.query.all()
    freqs = [a.frequencia for a in alunos]
    por_curso = {}
    for t in turmas:
        por_curso.setdefault(t.curso, []).append(t.frequencia_media)
    dias_por_turma = {t.id: t.dias_aula for t in turmas}
    meses = {}
    for p in Presenca.query.all():
        if not eh_dia_com_aula(p.data, dias_por_turma.get(p.aluno.turma_id, ())):
            continue
        ok, tot = meses.get(p.data.strftime("%Y-%m"), (0, 0))
        meses[p.data.strftime("%Y-%m")] = (ok + (p.status != "falta"), tot + 1)
    chaves = sorted(meses)[-6:]
    n = len(alunos)
    return render_template(
        "admin/relatorios.html", total_alunos=n,
        media_geral=round(sum(freqs) / n) if n else 0,
        alunos_criticos=sum(1 for x in alunos if x.presencas and x.frequencia < 75),
        taxa_evasao=round(100 * sum(1 for x in alunos if x.presencas and x.frequencia < 50) / n, 1) if n else 0,
        cursos_labels=list(por_curso), cursos_valores=[round(sum(v) / len(v)) for v in por_curso.values()],
        meses_labels=[k[5:] + "/" + k[:4] for k in chaves],
        meses_valores=[round(100 * meses[k][0] / meses[k][1]) for k in chaves],
        top_professores=sorted(Professor.query.all(), key=lambda p: p.media, reverse=True)[:5])


# ============================ PROFESSOR ============================
def _normalizar_data_chamada(valor, dias):
    """Retorna uma data válida de aula: nunca futura e sempre em dia de aula."""
    hoje = hoje_local()

    if not valor:
        selecionada = hoje
    else:
        try:
            selecionada = date.fromisoformat(valor)
        except (TypeError, ValueError):
            selecionada = hoje

    if selecionada > hoje:
        selecionada = hoje

    # dias sem aula apontam para o dia de aula anterior mais próximo
    return ultimo_dia_com_aula(selecionada, dias)


def _dias_uteis_semana(data_ref, hoje, dias_aula):
    """Monta as opções de dias de aula da semana para a tela do professor."""
    inicio = data_ref - timedelta(days=data_ref.weekday())
    dias = []
    for indice in dias_aula:
        d = inicio + timedelta(days=indice)
        dias.append({
            "data": d,
            "iso": d.isoformat(),
            "nome": NOMES_DIAS[indice],
            "display": d.strftime("%d/%m"),
            "disponivel": d <= hoje,
            "editavel": d == hoje,
            "selecionado": d == data_ref,
        })
    return dias


@professor.route("/chamada")
@requer("professor")
def chamada():
    prof = usuario_atual()
    turma_id = request.args.get("turma_id", type=int)
    hoje = hoje_local()

    turmas = prof.turmas
    turma = next((t for t in turmas if t.id == turma_id), turmas[0] if turmas else None)
    vinculo = prof.vinculo(turma.id) if turma else None
    dias_prof = vinculo.dias_semana if vinculo else ()
    data_selecionada = _normalizar_data_chamada(request.args.get("data"), dias_prof)
    alunos, presentes, faltas = [], 0, 0

    if turma and dias_prof:
        ids = [a.id for a in turma.alunos]
        mapa = {}
        if ids:
            registros = Presenca.query.filter(
                Presenca.aluno_id.in_(ids),
                Presenca.data == data_selecionada
            ).all()
            for r in registros:
                mapa.setdefault(r.aluno_id, {})[r.aula] = r.status

        for a in sorted(turma.alunos, key=lambda x: (x.numero_chamada or 999, x.nome)):
            st = [mapa.get(a.id, {}).get(i, "falta") for i in range(AULAS_POR_DIA)]
            tem_presenca = any(s in ("presente", "atraso") for s in st)
            faltou_dia = all(s == "falta" for s in st)
            presentes += int(tem_presenca)
            faltas += int(faltou_dia)
            alunos.append({
                "id": a.id,
                "nome": a.nome,
                "matricula": a.matricula,
                "iniciais": "".join(p[0] for p in a.nome.split()[:2]).upper(),
                "data": data_selecionada.strftime("%d/%m/%Y"),
                "status": st,
            })

    eh_hoje = data_selecionada == hoje
    pode_editar = eh_hoje and eh_dia_com_aula(hoje, dias_prof)

    return render_template(
        "professor/frequencia.html",
        turmas=turmas,
        turma_selecionada=turma,
        alunos=alunos,
        total_matriculados=len(alunos),
        total_presentes=presentes,
        total_faltas=faltas,
        media_frequencia=turma.frequencia_media if turma else 0,
        data_iso=data_selecionada.isoformat(),
        data_exibicao=data_selecionada.strftime("%d/%m/%Y"),
        hoje_iso=hoje.isoformat(),
        eh_hoje=eh_hoje,
        pode_editar=pode_editar,
        dias_semana=_dias_uteis_semana(data_selecionada, hoje, dias_prof),
        dia_nome=NOMES_DIAS[data_selecionada.weekday()],
        dias_prof=dias_prof,
        dias_prof_nomes=vinculo.dias_nomes if vinculo else "",
        dias_opcoes=[(d, NOMES_DIAS[d]) for d in DIAS_SELECIONAVEIS],
    )


@professor.route("/turmas/<int:turma_id>/dias", methods=["POST"])
@requer("professor")
def salvar_dias(turma_id):
    v = db.session.get(ProfessorTurma, (session["uid"], turma_id))
    if not v:
        flash("Você não leciona nessa turma.", "danger")
        return redirect(url_for("professor.chamada"))
    v.dias_semana = dias_de_formulario(request.form.getlist("dias"))
    db.session.commit()
    flash(f"Dias de aula salvos: {v.dias_nomes}.", "success")
    return redirect(url_for("professor.chamada", turma_id=turma_id))


def _dados_postagem():
    dados = request.get_json(silent=True) or {}
    valor = request.args.get("data") or dados.get("data") or ""
    senha_admin = (dados.get("admin_senha") or "").strip()

    try:
        data_requisitada = date.fromisoformat(valor)
    except (TypeError, ValueError):
        data_requisitada = None

    return data_requisitada, senha_admin


def _senha_admin_valida(senha):
    if not senha:
        return False
    return any(admin.check_senha(senha) for admin in Admin.query.all())


def _pode_alterar_data(data_requisitada, senha_admin, dias):
    hoje = hoje_local()

    if data_requisitada is None:
        return False, "Data inválida."

    if data_requisitada > hoje:
        return False, "Não é possível alterar uma chamada futura."

    if not eh_dia_com_aula(data_requisitada, dias):
        return False, "Você não tem aula nesta turma neste dia da semana."

    if data_requisitada == hoje:
        return True, None

    if not _senha_admin_valida(senha_admin):
        return False, "Para alterar uma chamada anterior, informe a senha de um administrador."

    return True, None


def _alterar(aluno_id, barra, regra):
    if barra < 0 or barra >= AULAS_POR_DIA:
        return jsonify(erro="Aula inválida."), 400

    aluno = db.get_or_404(Aluno, aluno_id)
    vinculo = db.session.get(ProfessorTurma, (session["uid"], aluno.turma_id)) if aluno.turma_id else None
    if not vinculo:
        return jsonify(erro="Aluno não pertence às suas turmas."), 403

    data_requisitada, senha_admin = _dados_postagem()
    permitido, erro = _pode_alterar_data(data_requisitada, senha_admin, vinculo.dias_semana)
    if not permitido:
        return jsonify(erro=erro), 403

    p = Presenca.query.filter_by(
        aluno_id=aluno_id, data=data_requisitada, aula=barra
    ).first()

    if not p:
        p = Presenca(
            aluno_id=aluno_id,
            data=data_requisitada,
            aula=barra,
            status="falta"
        )
        db.session.add(p)

    p.status, p.origem = regra(p.status), "professor"
    db.session.commit()

    return jsonify(estado=p.status, media_frequencia=aluno.turma.frequencia_media)


@professor.route("/toggle/<int:aluno_id>/<int:barra>", methods=["POST"])
@requer("professor")
def toggle(aluno_id, barra):
    return _alterar(aluno_id, barra, lambda s: "falta" if s == "presente" else "presente")


@professor.route("/atraso/<int:aluno_id>/<int:barra>", methods=["POST"])
@requer("professor")
def atraso(aluno_id, barra):
    if barra > 1:
        return jsonify(erro="Atraso só pode ser marcado nas aulas 1 e 2."), 400
    return _alterar(aluno_id, barra, lambda s: "presente" if s == "atraso" else "atraso")


# ============================ APP ============================
def create_app():
    global totem
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "troque-esta-chave")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///frequencyon.db")
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"timeout": 15}}
    app.config["UPLOAD_DIR"] = os.path.join(app.static_folder, "uploads")
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
    db.init_app(app)

    totem = Totem(app, camera=int(os.getenv("TOTEM_CAMERA", "0")))
    app.register_blueprint(admin)
    app.register_blueprint(professor)
    app.register_blueprint(reconhecimento)
    app.jinja_env.filters["inicial"] = lambda n: (n or "A")[0].upper()
    app.context_processor(lambda: {"usuario": usuario_atual()})

    def entrar(modelo, tipo, destino, template):
        if request.method == "POST":
            ident, senha = request.form["email"].strip(), request.form["senha"]
            u = modelo.query.filter(or_(modelo.email == ident,
                                        *( [Aluno.matricula == ident] if modelo is Aluno else []))).first()
            if u and u.check_senha(senha):
                session.clear()
                session.update(tipo=tipo, uid=u.id)
                return redirect(destino)
            flash("E-mail/matrícula ou senha inválidos.", "danger")
        return render_template(template)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/login", methods=["GET", "POST"])
    @app.route("/login/aluno", methods=["GET", "POST"])
    def login_aluno():
        return entrar(Aluno, "aluno", url_for("index"), "login.html")

    @app.route("/login/professor", methods=["GET", "POST"])
    def login_professor():
        return entrar(Professor, "professor", url_for("professor.chamada"), "professor/login_professor.html")

    @app.route("/login/admin", methods=["GET", "POST"])
    def login_admin():
        return entrar(Admin, "admin", url_for("admin.dashboard"), "admin/login_admin.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    with app.app_context():
        db.create_all()
        migrar_professor_turma()
        if not Admin.query.first():   # admin padrão para o primeiro acesso
            a = Admin(nome="Administrador", email="admin@frequencyon.com")
            a.set_senha("admin123")
            db.session.add(a)
            db.session.commit()
            print("Admin criado: admin@frequencyon.com / admin123")
    return app


if __name__ == "__main__":
    # debug=False: o reloader abriria a câmera duas vezes
    create_app().run(host="0.0.0.0", port=5000, threaded=True, debug=False)