# rotas do totem da entrada
# a parte pesada (reconhecimento) fica em face_service.py,
# aqui so tem a ponte entre o navegador do totem (tablet) e o servidor.
# o totem e criado pela coordenacao (com a sala), ativado no tablet com um codigo
# e liberado todo dia por um professor da sala olhando pra camera
import hashlib
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, time as dtime, timedelta
from functools import wraps

import cv2
from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, url_for

from database import db, Admin, Aluno, Dispositivo, Professor, agora_local, hoje_local
from .comum import pasta_uploads, pegar_totem

reconhecimento = Blueprint("reconhecimento", __name__)

COOKIE_TOTEM = "totem_token"
MAX_FOTO_BYTES = 600 * 1024


# ---------------------------------------------------------------------
# ativacao: a coordenacao cria o totem no painel (nome + sala) e recebe um
# codigo. o tablet digita o codigo uma vez e ganha um token guardado num
# cookie; o banco guarda so o hash dele.
# liberacao: todo dia um professor da sala olha pra camera (ou digita e-mail
# e senha) e o totem fica liberado ate o fim do dia.
# ---------------------------------------------------------------------
TENTATIVAS_LIBERAR = 10
JANELA_LIBERAR = 15 * 60
_erros_liberar = {}                 # ip -> (quantidade, primeira_tentativa)
_erros_ativacao = {}                # ip -> (quantidade, primeira_tentativa)
ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sem 0/O e 1/I, que se confundem


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def gerar_codigo_ativacao(disp):
    # codigo de 8 letras que o tablet digita para virar este totem (vale 24 h, uma vez so)
    codigo = "".join(secrets.choice(ALFABETO_CODIGO) for _ in range(8))
    disp.codigo_hash = _hash(codigo)
    disp.codigo_ate = agora_local() + timedelta(hours=24)
    return f"{codigo[:4]} {codigo[4:]}"


def _limite(registro, ip):
    # True se o ip errou demais nos ultimos 15 minutos
    agora = time.time()
    n, desde = registro.get(ip, (0, agora))
    if agora - desde > JANELA_LIBERAR:
        n, desde = 0, agora
    registro[ip] = (n, desde)
    return n >= TENTATIVAS_LIBERAR


def _errou(registro, ip):
    n, desde = registro.get(ip, (0, time.time()))
    registro[ip] = (n + 1, desde)


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
    if not disp:
        return render_template("totem/ativar.html")
    totem = pegar_totem()
    totem.iniciar()
    if not disp.liberado:
        return render_template("totem/liberar.html", modo=totem.fonte, disp=disp)
    return render_template("totem/reconhecimento.html", modo=totem.fonte, nome_totem=disp.nome)


@reconhecimento.route("/totem/ativar", methods=["POST"])
def ativar_totem():
    # o tablet digita o codigo gerado pela coordenacao e passa a ser aquele totem
    ip = request.remote_addr or "?"
    if _limite(_erros_ativacao, ip):
        return render_template("totem/ativar.html", erro="Muitas tentativas. Aguarde 15 minutos."), 429
    codigo = (request.form.get("codigo") or "").strip().upper().replace(" ", "").replace("-", "")
    disp = Dispositivo.query.filter_by(codigo_hash=_hash(codigo)).first() if codigo else None
    if not disp or not disp.codigo_ate or disp.codigo_ate < agora_local():
        _errou(_erros_ativacao, ip)
        return render_template("totem/ativar.html", erro="Código inválido ou vencido. Peça um novo à coordenação."), 403
    _erros_ativacao.pop(ip, None)

    token = secrets.token_urlsafe(32)
    # token novo: se outro tablet usava este totem, ele perde o acesso
    disp.token_hash, disp.codigo_hash, disp.codigo_ate = _hash(token), None, None
    disp.ativado_em, disp.liberado_ate = agora_local(), None
    db.session.commit()
    print(f"[totem] aparelho ativado como {disp.nome}")
    resp = redirect(url_for("reconhecimento.pagina_totem"))
    # cookie proprio (nao a sessao) pra continuar valendo mesmo se o navegador do tablet reiniciar
    resp.set_cookie(COOKIE_TOTEM, token, max_age=2 * 365 * 24 * 3600, httponly=True, samesite="Strict",
                    secure=current_app.config.get("SESSION_COOKIE_SECURE", False))
    return resp


def _liberar(disp, pessoa):
    # libera o aparelho ate o fim do dia em nome de 'pessoa'
    fim_do_dia = datetime.combine(hoje_local(), dtime(23, 59, 59))
    disp.liberado_ate, disp.liberado_por, disp.ultimo_uso = fim_do_dia, pessoa.nome, agora_local()
    db.session.commit()
    print(f"[totem] {disp.nome} liberado por {pessoa.nome} até {fim_do_dia:%d/%m %H:%M}")


def _motivo_negado(pessoa, disp):
    # None se 'pessoa' pode liberar este aparelho; senao, o texto que aparece no totem
    if disp.pode_liberar(pessoa):
        return None
    if not disp.turma_id:
        return "Este totem está sem sala. Peça à coordenação para escolher a sala dele em Totens."
    return f"{pessoa.nome} não é professor(a) da {disp.turma.nome}."


@reconhecimento.route("/totem/liberar/frame", methods=["POST"])
def liberar_por_rosto():
    # totem bloqueado: o tablet manda fotos e, quando reconhece o rosto de um professor da sala, libera o aparelho
    disp = dispositivo_atual()
    if not disp:
        return jsonify(sucesso=False, erro="totem_nao_ativado", mensagem="Este aparelho não está ativado."), 401
    jpeg = request.get_data(cache=False)
    if not jpeg or len(jpeg) > MAX_FOTO_BYTES:
        return jsonify(sucesso=False, mensagem="Imagem vazia ou grande demais."), 413
    totem, chave = pegar_totem(), chave_do_totem(disp)
    try:
        resultado = totem.receber_frame(chave, jpeg, grupo="prof")
    except ValueError:
        return jsonify(sucesso=False, mensagem="Imagem inválida."), 400
    pid = totem.professor_reconhecido(chave)
    professor = db.session.get(Professor, pid) if pid else None
    if not professor:
        return jsonify({**resultado, "liberado": False})
    negado = _motivo_negado(professor, disp)
    if negado:
        totem.esquecer(chave)       # recomeca do zero: o proximo rosto e conferido de novo
        return jsonify({**resultado, "liberado": False, "negado": negado})
    _liberar(disp, professor)
    return jsonify({**resultado, "liberado": True, "nome": professor.nome})


@reconhecimento.route("/totem/liberar", methods=["POST"])
def liberar_totem():
    # plano B: e-mail e senha (admin sem rosto cadastrado, camera com problema)
    disp = dispositivo_atual()
    if not disp:
        return redirect(url_for("reconhecimento.pagina_totem"))

    def tela(erro, status, **kw):
        return render_template("totem/liberar.html", modo=pegar_totem().fonte, disp=disp, erro=erro, **kw), status

    ip = request.remote_addr or "?"
    if _limite(_erros_liberar, ip):
        return tela("Muitas tentativas erradas. Aguarde 15 minutos.", 429)

    email = (request.form.get("email") or "").strip().lower()
    senha = request.form.get("senha") or ""
    # professor da sala libera o totem; admin tambem pode
    pessoa = (Professor.query.filter(db.func.lower(Professor.email) == email).first()
              or Admin.query.filter(db.func.lower(Admin.email) == email).first())
    if not pessoa or not pessoa.check_senha(senha):
        _errou(_erros_liberar, ip)
        return tela("E-mail ou senha incorretos.", 403, email=email)
    _erros_liberar.pop(ip, None)
    negado = _motivo_negado(pessoa, disp)
    if negado:
        return tela(negado, 403)
    _liberar(disp, pessoa)
    return redirect(url_for("reconhecimento.pagina_totem"))


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
