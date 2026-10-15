# pagina inicial, as tres telas de login e o logout
# essas rotas ficam direto no app (sem blueprint) pra manter os nomes
# que os templates ja usam: url_for("login_aluno"), url_for("logout"), etc
from flask import flash, redirect, render_template, request, session, url_for
from sqlalchemy import or_

from database import Admin, Professor, Aluno


def _entrar(modelo, tipo, destino, template):
    # o login e igual pros tres tipos, so muda a tabela e pra onde vai depois
    # aluno pode entrar com e-mail ou com a matricula
    if request.method == "POST":
        ident, senha = request.form["email"].strip(), request.form["senha"]
        filtros = [modelo.email == ident]
        if modelo is Aluno:
            filtros.append(Aluno.matricula == ident)
        u = modelo.query.filter(or_(*filtros)).first()
        if u and u.check_senha(senha):
            session.clear()
            session.update(tipo=tipo, uid=u.id)
            return redirect(destino)
        flash("E-mail/matrícula ou senha inválidos.", "danger")
    return render_template(template)


def registrar(app):
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/login", methods=["GET", "POST"])
    @app.route("/login/aluno", methods=["GET", "POST"])
    def login_aluno():
        return _entrar(Aluno, "aluno", url_for("aluno.painel"), "login.html")

    @app.route("/login/professor", methods=["GET", "POST"])
    def login_professor():
        return _entrar(Professor, "professor", url_for("professor.chamada"), "professor/login_professor.html")

    @app.route("/login/admin", methods=["GET", "POST"])
    def login_admin():
        return _entrar(Admin, "admin", url_for("admin.dashboard"), "admin/login_admin.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))
