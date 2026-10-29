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

from database import db, Admin, SENHAS_FRACAS, migrar_dispositivos, migrar_professor_turma  # noqa: E402
from face_service import Totem  # noqa: E402
from rotas import registrar_rotas  # noqa: E402
from rotas.comum import usuario_atual  # noqa: E402


def create_app(avisar_senhas=True):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or _chave_secreta(app.instance_path)
    # cookie de login: o JavaScript não lê e outro site não consegue usar
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # HTTPS ligado por padrão (HTTPS=0 no .env desliga, por exemplo para testes)
    usar_https = os.getenv("HTTPS", "1") != "0"
    app.config["USAR_HTTPS"] = usar_https
    app.config["SESSION_COOKIE_SECURE"] = usar_https      # cookie de login só trafega criptografado
    app.config["PREFERRED_URL_SCHEME"] = "https" if usar_https else "http"
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

    if usar_https and os.getenv("SSL_CERT"):
        # com certificado de verdade, o navegador passa a só aceitar HTTPS neste endereço.
        # (não vale para o certificado local: se ele não estiver instalado, o site ficaria inacessível)
        @app.after_request
        def hsts(resposta):
            resposta.headers["Strict-Transport-Security"] = "max-age=31536000"
            return resposta

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
        migrar_dispositivos()       # antes: cria colunas que as consultas de Professor já usam
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
    if avisar_senhas:
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


def _redirecionar_para_https(porta_http, porta_https):
    """Servidor mínimo na porta antiga (HTTP) que manda tudo para o endereço HTTPS."""
    from werkzeug.serving import make_server

    def app_redirecionar(environ, start_response):
        host = environ.get("HTTP_HOST", "localhost").rsplit(":", 1)[0]
        destino = f"https://{host}:{porta_https}{environ.get('PATH_INFO', '/')}"
        if environ.get("QUERY_STRING"):
            destino += "?" + environ["QUERY_STRING"]
        start_response("302 Found", [("Location", destino), ("Content-Length", "0")])
        return [b""]

    try:
        make_server("0.0.0.0", porta_http, app_redirecionar, threaded=True).serve_forever()
    except OSError as e:
        print(f"[https] porta {porta_http} ocupada, sem redirecionamento de HTTP: {e}")


if __name__ == "__main__":
    app = create_app()
    porta = int(os.getenv("PORTA", "5000"))
    # debug fica desligado porque o reloader abriria a camera duas vezes
    if not app.config["USAR_HTTPS"]:
        app.run(host="0.0.0.0", port=porta, threaded=True, debug=False)
    else:
        from certificado import certificado_local, ips_da_maquina
        porta_https = int(os.getenv("PORTA_HTTPS", "5443"))
        if os.getenv("SSL_CERT") and os.getenv("SSL_KEY"):
            cert, chave = os.getenv("SSL_CERT"), os.getenv("SSL_KEY")
        else:
            cert, chave = certificado_local(app.instance_path)
            print(f"[https] para o navegador confiar no site, instale uma vez: "
                  f"{os.path.join(app.instance_path, 'ca-frequencyon.pem')}")
        threading.Thread(target=_redirecionar_para_https, args=(porta, porta_https), daemon=True).start()
        for ip in ["localhost"] + [i for i in ips_da_maquina() if i != "127.0.0.1"]:
            print(f"[https] acesse: https://{ip}:{porta_https}   (http://{ip}:{porta} redireciona)")
        app.run(host="0.0.0.0", port=porta_https, threaded=True, debug=False, ssl_context=(cert, chave))
