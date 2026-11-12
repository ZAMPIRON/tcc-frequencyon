# trilha de auditoria do painel (RNF14 e RF17): toda alteracao feita no painel da coordenacao
# fica registrada com quem fez, quando e o que mudou; a tela /admin/auditoria mostra o historico
# a chamada do professor tem a sua propria tabela (AlteracaoPresenca), mostrada na mesma tela
from flask import g, render_template, request, session

from database import (db, AlteracaoPresenca, Aluno, AuditoriaPainel, Dispositivo, Justificativa, ModeloHorario,
                      Professor, Turma)
from .admin import admin
from .comum import requer, usuario_atual

# endpoint -> o que aparece na coluna "acao"
ACOES = {
    "admin.novo_aluno": "Cadastrou aluno", "admin.editar_aluno": "Editou aluno", "admin.deletar_aluno": "Excluiu aluno",
    "admin.professores": "Cadastrou professor", "admin.editar_professor": "Editou professor",
    "admin.rosto_professor": "Cadastrou o rosto do professor", "admin.deletar_professor": "Excluiu professor",
    "admin.turmas": "Criou turma", "admin.editar_turma": "Editou turma", "admin.deletar_turma": "Excluiu turma",
    "admin.adicionar_aluno_turma": "Pôs aluno na turma", "admin.desvincular_aluno": "Tirou aluno da turma",
    "admin.horario_turma": "Trocou o horário da turma", "admin.vincular_professor": "Vinculou professor à turma",
    "admin.dias_professor_turma": "Mudou os dias do professor", "admin.desvincular_professor": "Tirou professor da turma",
    "admin.novo_horario": "Criou horário", "admin.salvar_horario": "Editou horário", "admin.remover_horario": "Removeu horário",
    "admin.responder_justificativa": "Respondeu justificativa",
    "admin.novo_totem": "Criou totem", "admin.codigo_totem": "Gerou código do totem", "admin.remover_totem": "Removeu totem",
    "admin.enviar_alertas": "Enviou alertas de frequência", "admin.fazer_backup_agora": "Fez backup do banco",
}
# campos do formulario que entram no detalhe (senha e foto nunca)
CAMPOS = ("nome", "matricula", "email", "curso", "departamento")


def _modelo_do_id(endpoint):
    for pedaco, modelo in (("justificativa", Justificativa), ("aluno", Aluno), ("professor", Professor),
                           ("horario", ModeloHorario), ("totem", Dispositivo), ("turma", Turma)):
        if pedaco in endpoint:
            return modelo
    return None


def _nome(obj):
    if isinstance(obj, Turma):
        return f"turma {obj.nome} · {obj.curso}"
    if isinstance(obj, Justificativa):
        return f"justificativa de {obj.aluno.nome} ({obj.data:%d/%m/%Y})"
    tipo = {Aluno: "aluno", Professor: "professor", ModeloHorario: "horário", Dispositivo: "totem"}.get(type(obj), "")
    return f"{tipo} {getattr(obj, 'nome', obj.id)}".strip()


def _alvo(endpoint, args):
    # descreve o que vai ser alterado ANTES da alteracao (depois de excluir nao da mais pra ler o nome)
    partes = []
    for chave, valor in args.items():
        modelo = {"aluno_id": Aluno, "turma_id": Turma, "professor_id": Professor}.get(chave) or \
            (_modelo_do_id(endpoint) if chave == "id" else None)
        obj = db.session.get(modelo, valor) if modelo else None
        if obj:
            partes.append(_nome(obj))
        elif chave == "acao":
            partes.append(f"resposta: {valor}")
    return partes


@admin.before_request
def _antes():
    if request.method == "POST" and request.endpoint in ACOES:
        g.auditoria = (len(session.get("_flashes", [])), _alvo(request.endpoint, request.view_args or {}))


@admin.after_request
def _depois(resposta):
    # so grava quando deu certo: resposta sem erro e nenhuma mensagem vermelha (validacao recusada)
    if not hasattr(g, "auditoria") or resposta.status_code >= 400:
        return resposta
    antes, partes = g.auditoria
    if any(cat == "danger" for cat, _ in session.get("_flashes", [])[antes:]):
        return resposta
    pessoa = usuario_atual()
    if not pessoa:
        return resposta
    partes = partes + [f"{c}: {request.form[c].strip()}" for c in CAMPOS if (request.form.get(c) or "").strip()]
    try:
        db.session.add(AuditoriaPainel(usuario_tipo=session.get("tipo", "?"), usuario_nome=pessoa.nome,
                                       acao=ACOES[request.endpoint], detalhe="; ".join(partes)[:500]))
        db.session.commit()
    except Exception as e:      # a auditoria nunca pode derrubar a acao que ja deu certo
        db.session.rollback()
        print(f"[auditoria] não consegui registrar: {e}")
    return resposta


@admin.route("/auditoria")
@requer("admin")
def auditoria():
    return render_template("admin/auditoria.html",
                           painel=AuditoriaPainel.query.order_by(AuditoriaPainel.quando.desc()).limit(300).all(),
                           chamada=AlteracaoPresenca.query.order_by(AlteracaoPresenca.alterado_em.desc()).limit(300).all(),
                           alunos={a.id: a for a in Aluno.query.all()})
