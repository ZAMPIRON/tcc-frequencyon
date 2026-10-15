# rotas do totem da entrada
# a parte pesada (camera e reconhecimento) fica em face_service.py,
# aqui so tem a ponte entre o navegador e o totem
import os
import threading
import time
import uuid

import cv2
from flask import Blueprint, Response, jsonify, render_template, request

from database import db, Aluno
from .comum import pasta_uploads, pegar_totem

reconhecimento = Blueprint("reconhecimento", __name__)


@reconhecimento.route("/totem")
def pagina_totem():
    pegar_totem().iniciar()
    return render_template("totem/reconhecimento.html")


@reconhecimento.route("/video_feed")
def video_feed():
    # video da camera em mjpeg, a pagina mostra isso num <img>
    totem = pegar_totem()
    totem.iniciar()
    return Response(totem.stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


@reconhecimento.route("/api/reconhecimento")
def api_reconhecimento():
    # a pagina do totem pergunta aqui a cada segundo se alguem foi reconhecido
    # cada evento so e entregue uma vez
    ev = pegar_totem().proximo_evento()
    return jsonify({"reconhecido": True, "dados": ev} if ev else {"reconhecido": False})


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
def api_cadastrar_foto():
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
        enc, frame = totem.capturar_encoding()
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
