# rotas do totem da entrada
# a parte pesada (camera e reconhecimento) fica em face_service.py,
# aqui so tem a ponte entre o navegador e o totem
import os
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


@reconhecimento.route("/api/cadastrar_foto", methods=["POST"])
def api_cadastrar_foto():
    # o aluno digita a matricula no totem e a camera tira umas fotos do rosto dele
    try:
        totem = pegar_totem()
        matricula = ((request.get_json(silent=True) or {}).get("matricula") or "").strip()
        aluno = Aluno.query.filter_by(matricula=matricula).first()
        if not aluno:
            return jsonify(sucesso=False, mensagem="Matrícula não encontrada."), 404
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
