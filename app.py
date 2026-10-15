# ponto de entrada do frequencyon: monta o app e liga o servidor
# as rotas ficam na pasta rotas/, os modelos em database.py e a camera em face_service.py
import os
import secrets
import threading

from flask import Flask, flash, jsonify, redirect, request, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect

from email_service import carregar_env

# o .env precisa ser lido antes de importar o database,
# porque os horarios das aulas sao lidos das variaveis na hora do import
carregar_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from database import db, Admin, migrar_professor_turma  # noqa: E402
from face_service import Totem  # noqa: E402
from rotas import registrar_rotas  # noqa: E402
from rotas.comum import usuario_atual  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or _chave_secreta(app.instance_path)
    # cookie de login: o JavaScript não lê e outro site não consegue usar
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # o token CSRF vale enquanto a sessão durar (o totem fica aberto o dia todo)
    app.config["WTF_CSRF_TIME_LIMIT"] = None
    CSRFProtect(app)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///frequencyon.db")
    # o totem e o site escrevem no banco ao mesmo tempo, entao espera ate 15s se estiver ocupado
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"timeout": 15}}
    app.config["UPLOAD_DIR"] = os.path.join(app.static_folder, "uploads")
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
    db.init_app(app)

    # um totem so pro app inteiro, as rotas pegam ele com pegar_totem()
    app.extensions["totem"] = Totem(app, camera=int(os.getenv("TOTEM_CAMERA", "0")))

    registrar_rotas(app)

    # coisas que todo template pode usar
    app.jinja_env.filters["inicial"] = lambda n: (n or "A")[0].upper()
    # a foto só aparece se o arquivo existir (o banco pode vir de outro computador sem as imagens)
    app.jinja_env.filters["foto_existe"] = lambda url: bool(url) and url.startswith("/static/") and         os.path.isfile(os.path.join(app.static_folder, url[len("/static/"):]))

    @app.errorhandler(CSRFError)
    def csrf_invalido(e):
        # formulário velho ou enviado de fora do site
        if request.is_json or request.path.startswith(("/api/", "/professor/toggle", "/professor/atraso")):
            msg = "Sessão expirada. Recarregue a página e tente de novo."
            return jsonify(sucesso=False, erro=msg, mensagem=msg), 400
        flash("Sua sessão expirou. Recarregue a página e tente de novo.", "warning")
        return redirect(request.referrer or url_for("index"))
    app.context_processor(lambda: {"usuario": usuario_atual()})

    with app.app_context():
        db.create_all()
        migrar_professor_turma()
        # banco novo: cria um admin pra conseguir entrar a primeira vez.
        # a senha vem do .env (ADMIN_SENHA) ou é sorteada e mostrada uma vez no terminal
        if not Admin.query.first():
            email = os.getenv("ADMIN_EMAIL", "admin@frequencyon.com")
            senha = os.getenv("ADMIN_SENHA") or secrets.token_urlsafe(9)
            a = Admin(nome="Administrador", email=email)
            a.set_senha(senha)
            db.session.add(a)
            db.session.commit()
            print(f"Admin criado: {email}" + ("" if os.getenv("ADMIN_SENHA") else f" / senha: {senha}  (anote, ela não aparece de novo)"))
    # conferir senha é lento de propósito; roda em segundo plano para não atrasar a subida
    threading.Thread(target=_avisar_senhas_fracas, args=(app,), daemon=True).start()
    return app


def _chave_secreta(pasta):
    """Sem SECRET_KEY no .env, sorteia uma e guarda em instance/ (fora do Git) para as sessões
    continuarem valendo depois de reiniciar o servidor."""
    os.makedirs(pasta, exist_ok=True)
    arquivo = os.path.join(pasta, "secret_key")
    if not os.path.exists(arquivo):
        with open(arquivo, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    with open(arquivo, encoding="utf-8") as f:
        return f.read().strip()


SENHAS_FRACAS = ("admin123", "prof123", "123", "1234", "123456", "senha", "admin")


def _avisar_senhas_fracas(app):
    from database import Aluno, Professor
    with app.app_context():
        contas = [(t, getattr(u, "matricula", None) or u.email) for t, modelo in
                  (("admin", Admin), ("professor", Professor), ("aluno", Aluno))
                  for u in modelo.query.all() if any(u.check_senha(s) for s in SENHAS_FRACAS)]
    if contas:
        print(f"[seguranca] {len(contas)} conta(s) com senha padrão/fraca. Troque com: python trocar_senha.py <email ou matricula>")
        for tipo, login in contas[:10]:
            print(f"    - {tipo}: {login}")


if __name__ == "__main__":
    # debug fica desligado porque o reloader abriria a camera duas vezes
    create_app().run(host="0.0.0.0", port=5000, threaded=True, debug=False)
