# rotas do totem da entrada
# a parte pesada (reconhecimento) fica em face_service.py,
# aqui so tem a ponte entre o navegador do totem (tablet) e o servidor.
# so aparelho ativado pelo admin consegue usar as rotas do totem
import hashlib
import os
import secrets
import threading
import time
import uuid
from datetime import timedelta
from functools import wraps

import cv2
from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, url_for

from database import db, Aluno, Dispositivo, agora_local
from .comum import pasta_uploads, pegar_totem

reconhecimento = Blueprint("reconhecimento", __name__)

COOKIE_TOTEM = "totem_token"
MAX_FOTO_BYTES = 600 * 1024


# ---------------------------------------------------------------------
# ativacao do tablet: o admin gera um codigo, o tablet digita uma vez e
# recebe um token guardado num cookie. o banco guarda so o hash do token
# ---------------------------------------------------------------------
CODIGO_VALIDADE = 15 * 60
_codigos = {}                       # codigo -> (nome do aparelho, expira_em)
_codigos_lock = threading.Lock()
_erros_ativacao = {}                # ip -> [quantidade, primeira_tentativa]


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def gerar_codigo_ativacao(nome):
    # 8 letras/numeros sem os que se confundem (0/O, 1/I)
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codigo = "".join(secrets.choice(alfabeto) for _ in range(8))
    with _codigos_lock:
        agora = time.time()
        for c in [c for c, (_, exp) in _codigos.items() if exp < agora]:
            del _codigos[c]
        _codigos[codigo] = (nome, agora + CODIGO_VALIDADE)
    return codigo


def _usar_codigo(codigo):
    with _codigos_lock:
        nome, exp = _codigos.pop(codigo, (None, 0))
    return nome if exp > time.time() else None


def dispositivo_atual():
    token = request.cookies.get(COOKIE_TOTEM)
    if not token:
        return None
    disp = Dispositivo.query.filter_by(token_hash=_hash(token)).first()
    if disp and (not disp.ultimo_uso or agora_local() - disp.ultimo_uso > timedelta(minutes=1)):
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
        if not disp:
            return jsonify(sucesso=False, erro="totem_nao_ativado",
                           mensagem="Este aparelho não está ativado como totem."), 401
        return f(disp, *a, **kw)
    return wrapper


@reconhecimento.route("/totem")
def pagina_totem():
    disp = dispositivo_atual()
    if not disp:
        return render_template("totem/ativar.html")
    totem = pegar_totem()
    totem.iniciar()
    return render_template("totem/reconhecimento.html", modo=totem.fonte, nome_totem=disp.nome)


@reconhecimento.route("/totem/ativar", methods=["POST"])
def ativar_totem():
    ip = request.remote_addr or "?"
    agora = time.time()
    n, desde = _erros_ativacao.get(ip, (0, agora))
    if agora - desde > CODIGO_VALIDADE:
        n, desde = 0, agora
    if n >= 10:
        return render_template("totem/ativar.html", erro="Muitas tentativas. Aguarde alguns minutos."), 429

    nome = _usar_codigo((request.form.get("codigo") or "").strip().upper().replace(" ", ""))
    if not nome:
        _erros_ativacao[ip] = (n + 1, desde)
        return render_template("totem/ativar.html", erro="Código inválido ou vencido. Peça um novo à coordenação."), 403

    token = secrets.token_urlsafe(32)
    disp = Dispositivo(nome=nome, token_hash=_hash(token))
    db.session.add(disp)
    db.session.commit()
    resp = redirect(url_for("reconhecimento.pagina_totem"))
    # cookie proprio (nao a sessao) pra continuar valendo mesmo se o navegador do tablet reiniciar
    resp.set_cookie(COOKIE_TOTEM, token, max_age=2 * 365 * 24 * 3600, httponly=True, samesite="Strict",
                    secure=current_app.config.get("SESSION_COOKIE_SECURE", False))
    print(f"[totem] aparelho ativado: {nome}")
    return resp


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
        return jsonify(pegar_totem().receber_frame(chave_do_totem(disp), jpeg))
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
