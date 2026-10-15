# funcoes pequenas que mais de um arquivo de rotas precisa
import os
import uuid
from functools import wraps

from flask import current_app, redirect, session, url_for

from database import db, Admin, Professor, Aluno
from face_service import encoding_de_arquivo


def pegar_totem():
    # o totem e criado uma vez so no create_app e fica guardado no proprio app
    return current_app.extensions["totem"]


def pasta_uploads():
    return current_app.config["UPLOAD_DIR"]


def salvar_foto(arquivo):
    # salva a foto enviada em static/uploads com um nome aleatorio e devolve a url
    if not arquivo or not arquivo.filename:
        return None
    ext = os.path.splitext(arquivo.filename)[1].lower() or ".jpg"
    nome = f"{uuid.uuid4().hex}{ext}"
    arquivo.save(os.path.join(pasta_uploads(), nome))
    return f"/static/uploads/{nome}"


def encoding_de_foto(url):
    # tira os 128 numeros do rosto de uma foto ja salva
    # se nao tiver exatamente um rosto na foto, volta None
    if not url:
        return None
    try:
        enc = encoding_de_arquivo(os.path.join(pasta_uploads(), os.path.basename(url)))
        return enc.tobytes() if enc is not None else None
    except Exception as e:
        print(f"[foto] não consegui ler o rosto da foto: {e}")
        return None


def usuario_atual():
    # descobre quem esta logado olhando a sessao (admin, professor ou aluno)
    tipo, uid = session.get("tipo"), session.get("uid")
    modelo = {"admin": Admin, "professor": Professor, "aluno": Aluno}.get(tipo)
    return db.session.get(modelo, uid) if modelo and uid else None


def requer(tipo):
    # decorator pra bloquear a rota de quem nao e do tipo certo
    # quem nao pode entrar e mandado pra tela de login certa
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            if session.get("tipo") != tipo or not usuario_atual():
                return redirect(url_for({"admin": "login_admin", "professor": "login_professor"}
                                        .get(tipo, "login_aluno")))
            return f(*a, **kw)
        return wrapper
    return deco
