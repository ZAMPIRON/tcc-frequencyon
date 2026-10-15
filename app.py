# ponto de entrada do frequencyon: monta o app e liga o servidor
# as rotas ficam na pasta rotas/, os modelos em database.py e a camera em face_service.py
import os

from flask import Flask

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
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "troque-esta-chave")
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
    app.context_processor(lambda: {"usuario": usuario_atual()})

    with app.app_context():
        db.create_all()
        migrar_professor_turma()
        # banco novo: cria um admin pra conseguir entrar a primeira vez
        if not Admin.query.first():
            a = Admin(nome="Administrador", email="admin@frequencyon.com")
            a.set_senha("admin123")
            db.session.add(a)
            db.session.commit()
            print("Admin criado: admin@frequencyon.com / admin123")
    return app


if __name__ == "__main__":
    # debug fica desligado porque o reloader abriria a camera duas vezes
    create_app().run(host="0.0.0.0", port=5000, threaded=True, debug=False)
