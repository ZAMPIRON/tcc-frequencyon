# rotas do totem da entrada
# a parte pesada (reconhecimento) fica em face_service.py,
# aqui so tem a ponte entre o navegador do totem (tablet) e o servidor.
# o totem so funciona depois que um professor olha pra camera dele (vale ate o fim do dia)
import hashlib
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, time as dtime, timedelta
from functools import wraps

import cv2
from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, session, url_for

from database import db, Admin, Aluno, Dispositivo, Professor, agora_local, hoje_local
from .comum import pasta_uploads, pegar_totem

reconhecimento = Blueprint("reconhecimento", __name__)

COOKIE_TOTEM = "totem_token"
MAX_FOTO_BYTES = 600 * 1024


# ---------------------------------------------------------------------
# liberacao do tablet: quando o professor chega, olha pra camera do totem
# (ou digita e-mail e senha) e ele fica liberado ate o fim do dia. o aparelho guarda um token num
# cookie e o banco guarda so o hash dele
# ---------------------------------------------------------------------
TENTATIVAS_LIBERAR = 10
JANELA_LIBERAR = 15 * 60
_erros_liberar = {}                 # ip -> (quantidade, primeira_tentativa)


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def dispositivo_atual():
    # aparelho deste navegador (liberado hoje ou nao)
    token = request.cookies.get(COOKIE_TOTEM)
    if not token:
        return None
    disp = Dispositivo.query.filter_by(token_hash=_hash(token)).first()
    if disp and disp.liberado and (not disp.ultimo_uso or agora_local() - disp.ultimo_uso > timedelta(minutes=1)):
        disp.ultimo_uso = agora_local()
        db.session.commit()
    return disp


def chave_do_totem(disp):
    # no modo tablet cada aparelho tem as suas imagens; no modo camera todos olham a webcam do servidor
    return "camera" if pegar_totem().fonte == "camera" else f"disp{disp.id}"


def requer_totem(f):
    @wraps(f)
    def wrapper(*a, **kw):
        disp = dispositivo_atual()
        if not disp or not disp.liberado:
            return jsonify(sucesso=False, erro="totem_bloqueado",
                           mensagem="O totem precisa ser liberado por um professor."), 401
        return f(disp, *a, **kw)
    return wrapper


@reconhecimento.route("/totem")
def pagina_totem():
    disp = dispositivo_atual()
    if not disp or not disp.liberado:
        totem = pegar_totem()
        totem.iniciar()
        return render_template("totem/liberar.html", modo=totem.fonte)
    totem = pegar_totem()
    totem.iniciar()
    return render_template("totem/reconhecimento.html", modo=totem.fonte, nome_totem=disp.nome)


def _liberar(pessoa, resp):
    # libera este aparelho ate o fim do dia em nome de 'pessoa' (aparelho novo ganha um token num cookie)
    fim_do_dia = datetime.combine(hoje_local(), dtime(23, 59, 59))
    disp = dispositivo_atual()
    token = None
    if not disp:
        token = secrets.token_urlsafe(32)
        disp = Dispositivo(nome=f"Totem {Dispositivo.query.count() + 1}", token_hash=_hash(token))
        db.session.add(disp)
    disp.liberado_ate, disp.liberado_por, disp.ultimo_uso = fim_do_dia, pessoa.nome, agora_local()
    db.session.commit()
    print(f"[totem] {disp.nome} liberado por {pessoa.nome} até {fim_do_dia:%d/%m %H:%M}")
    if token:
        # cookie proprio (nao a sessao) pra continuar valendo mesmo se o navegador do tablet reiniciar
        resp.set_cookie(COOKIE_TOTEM, token, max_age=2 * 365 * 24 * 3600, httponly=True, samesite="Strict",
                        secure=current_app.config.get("SESSION_COOKIE_SECURE", False))
    return resp


def _chave_bloqueado():
    # totem bloqueado: aparelho conhecido usa a chave dele; aparelho novo ganha uma chave provisoria na sessao
    disp = dispositivo_atual()
    if disp:
        return chave_do_totem(disp)
    if pegar_totem().fonte == "camera":
        return "camera"
    if "totem_pre" not in session:
        session["totem_pre"] = secrets.token_hex(8)
    return f"pre{session['totem_pre']}"


@reconhecimento.route("/totem/liberar/frame", methods=["POST"])
def liberar_por_rosto():
    # totem bloqueado: o tablet manda fotos e, quando reconhece o rosto de um professor, libera o aparelho
    jpeg = request.get_data(cache=False)
    if not jpeg or len(jpeg) > MAX_FOTO_BYTES:
        return jsonify(sucesso=False, mensagem="Imagem vazia ou grande demais."), 413
    totem, chave = pegar_totem(), _chave_bloqueado()
    try:
        resultado = totem.receber_frame(chave, jpeg, grupo="prof")
    except ValueError:
        return jsonify(sucesso=False, mensagem="Imagem inválida."), 400
    pid = totem.professor_reconhecido(chave)
    professor = db.session.get(Professor, pid) if pid else None
    if not professor:
        return jsonify({**resultado, "liberado": False})
    resp = _liberar(professor, jsonify({**resultado, "liberado": True, "nome": professor.nome}))
    if chave.startswith("pre"):
        totem.esquecer(chave)
        session.pop("totem_pre", None)
    return resp


@reconhecimento.route("/totem/liberar", methods=["POST"])
def liberar_totem():
    # plano B: e-mail e senha (admin sem rosto cadastrado, camera com problema)
    ip = request.remote_addr or "?"
    agora = time.time()
    n, desde = _erros_liberar.get(ip, (0, agora))
    if agora - desde > JANELA_LIBERAR:
        n, desde = 0, agora
    if n >= TENTATIVAS_LIBERAR:
        return render_template("totem/liberar.html", modo=pegar_totem().fonte, erro="Muitas tentativas erradas. Aguarde 15 minutos."), 429

    email = (request.form.get("email") or "").strip().lower()
    senha = request.form.get("senha") or ""
    # professor libera o totem; admin tambem pode
    pessoa = (Professor.query.filter(db.func.lower(Professor.email) == email).first()
              or Admin.query.filter(db.func.lower(Admin.email) == email).first())
    if not pessoa or not pessoa.check_senha(senha):
        _erros_liberar[ip] = (n + 1, desde)
        return render_template("totem/liberar.html", modo=pegar_totem().fonte, erro="E-mail ou senha incorretos.", email=email), 403
    _erros_liberar.pop(ip, None)
    return _liberar(pessoa, redirect(url_for("reconhecimento.pagina_totem")))


# ---------------------------------------------------------------------
# imagens e eventos
# ---------------------------------------------------------------------
@reconhecimento.route("/api/totem/frame", methods=["POST"])
@requer_totem
def api_frame(disp):
    # o navegador do tablet manda aqui uma foto JPEG da camera algumas vezes por segundo
    jpeg = request.get_data(cache=False)
    if not jpeg or len(jpeg) > MAX_FOTO_BYTES:
        return jsonify(sucesso=False, mensagem="Imagem vazia ou grande demais."), 413
    try:
        totem, chave = pegar_totem(), chave_do_totem(disp)
        resultado = totem.receber_frame(chave, jpeg)
        # o reconhecimento volta junto com a resposta do frame: a tela não espera o polling de 1 s
        return jsonify({**resultado, "evento": totem.proximo_evento(chave)})
    except ValueError:
        return jsonify(sucesso=False, mensagem="Imagem inválida."), 400


@reconhecimento.route("/video_feed")
@requer_totem
def video_feed(disp):
    # modo camera: video da webcam do servidor em mjpeg, a pagina mostra isso num <img>
    totem = pegar_totem()
    totem.iniciar()
    return Response(totem.stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


@reconhecimento.route("/api/reconhecimento")
@requer_totem
def api_reconhecimento(disp):
    # a pagina do totem pergunta aqui a cada segundo se alguem foi reconhecido nela
    # cada evento so e entregue uma vez
    ev = pegar_totem().proximo_evento(chave_do_totem(disp))
    return jsonify({"reconhecido": True, "dados": ev} if ev else {"reconhecido": False})


# ---------------------------------------------------------------------
# cadastro de rosto pelo proprio totem (pede a senha do aluno)
# ---------------------------------------------------------------------
# tentativas erradas de senha no cadastro de rosto: matricula -> [quantidade, bloqueado_ate]
TENTATIVAS_MAX = 5
BLOQUEIO_SEGUNDOS = 15 * 60
_tentativas = {}
_tentativas_lock = threading.Lock()


def _bloqueado(matricula):
    with _tentativas_lock:
        _, ate = _tentativas.get(matricula, (0, 0))
        return time.time() < ate


def _errou_senha(matricula):
    with _tentativas_lock:
        n, _ = _tentativas.get(matricula, (0, 0))
        n += 1
        _tentativas[matricula] = (0, time.time() + BLOQUEIO_SEGUNDOS) if n >= TENTATIVAS_MAX else (n, 0)


@reconhecimento.route("/api/cadastrar_foto", methods=["POST"])
@requer_totem
def api_cadastrar_foto(disp):
    # o aluno digita matricula e senha no totem e a camera tira umas fotos do rosto dele.
    # sem a senha, qualquer um trocaria o rosto de outro aluno pelo seu e "bateria ponto" por ele
    try:
        totem = pegar_totem()
        dados = request.get_json(silent=True) or {}
        matricula = (dados.get("matricula") or "").strip()
        senha = dados.get("senha") or ""
        if _bloqueado(matricula):
            return jsonify(sucesso=False, mensagem="Muitas tentativas erradas. Tente de novo em 15 minutos ou procure a coordenação."), 429
        aluno = Aluno.query.filter_by(matricula=matricula).first()
        if not aluno or not aluno.check_senha(senha):
            if aluno:
                _errou_senha(matricula)
            # mesma resposta para matrícula inexistente e senha errada: não revela quem existe
            return jsonify(sucesso=False, mensagem="Matrícula ou senha incorretas."), 403
        with _tentativas_lock:
            _tentativas.pop(matricula, None)
        totem.iniciar()
        enc, frame = totem.capturar_encoding(chave_do_totem(disp))
        if enc is None:
            # quando da errado, frame vem com o motivo em texto
            return jsonify(sucesso=False, mensagem=frame), 422
        aluno.face_encoding = enc.tobytes()
        if not aluno.foto:
            # se o aluno ainda nao tem foto de perfil, usa a captura
            nome = f"{uuid.uuid4().hex}.jpg"
            cv2.imwrite(os.path.join(pasta_uploads(), nome), frame)
            aluno.foto = f"/static/uploads/{nome}"
        db.session.commit()
        totem.recarregar()
        return jsonify(sucesso=True, mensagem=f"Rosto de {aluno.nome} cadastrado com sucesso!")
    except Exception as e:
        db.session.rollback()
        print(f"[cadastrar_foto] erro: {e}")
        return jsonify(sucesso=False, mensagem="Erro interno ao cadastrar o rosto."), 500
