# pagina inicial, as tres telas de login e o logout
# essas rotas ficam direto no app (sem blueprint) pra manter os nomes
# que os templates ja usam: url_for("login_aluno"), url_for("logout"), etc
import time

from flask import flash, redirect, render_template, request, session, url_for
from sqlalchemy import or_

from database import Admin, Professor, Aluno

# forca bruta: 10 senhas erradas seguidas no mesmo login, do mesmo aparelho, bloqueiam por 15 minutos
TENTATIVAS_LOGIN = 10
JANELA_LOGIN = 15 * 60
_erros_login = {}                   # (tipo, ip, login) -> (quantidade, primeira_tentativa)


def _bloqueado(chave):
    n, desde = _erros_login.get(chave, (0, 0))
    if time.time() - desde > JANELA_LOGIN:
        _erros_login.pop(chave, None)
        return False
    return n >= TENTATIVAS_LOGIN


def _entrar(modelo, tipo, destino, template):
    # o login e igual pros tres tipos, so muda a tabela e pra onde vai depois
    # aluno pode entrar com e-mail ou com a matricula
    if request.method == "POST":
        ident, senha = request.form["email"].strip(), request.form["senha"]
        chave = (tipo, request.remote_addr or "?", ident.lower())
        if _bloqueado(chave):
            # bloqueado ate a senha certa: senao daria pra continuar chutando
            flash("Muitas tentativas erradas. Aguarde 15 minutos e tente de novo.", "danger")
            return render_template(template), 429
        filtros = [modelo.email == ident]
        if modelo is Aluno:
            filtros.append(Aluno.matricula == ident)
        u = modelo.query.filter(or_(*filtros)).first()
        if u and u.check_senha(senha):
            _erros_login.pop(chave, None)
            session.clear()
            session.update(tipo=tipo, uid=u.id)
            return redirect(destino)
        n, desde = _erros_login.get(chave, (0, time.time()))
        _erros_login[chave] = (n + 1, desde)
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
