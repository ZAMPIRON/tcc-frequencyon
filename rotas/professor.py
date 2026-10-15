# tela de chamada do professor
# hoje ele edita a vontade, dias anteriores so com a senha de um admin, dia futuro nunca
from datetime import date, timedelta

from flask import Blueprint, jsonify, render_template, request, session, url_for

from database import (db, Admin, Aluno, Presenca, ProfessorTurma, AULAS_POR_DIA, NOMES_DIAS,
                      eh_dia_com_aula, hoje_local, ultimo_dia_com_aula)
from .comum import requer, usuario_atual

professor = Blueprint("professor", __name__, url_prefix="/professor")

MESES = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")


# ---------- datas e calendario ----------

def _normalizar_data_chamada(valor, dias):
    # pega a data da url e garante que e um dia de aula que ja aconteceu
    # data invalida ou no futuro vira hoje, dia sem aula volta pro ultimo dia com aula
    hoje = hoje_local()
    try:
        selecionada = date.fromisoformat(valor) if valor else hoje
    except (TypeError, ValueError):
        selecionada = hoje
    return ultimo_dia_com_aula(min(selecionada, hoje), dias)


def _fim_do_mes(d):
    # dia 28 + 4 dias sempre cai no mes seguinte, ai volta um dia do dia 1
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _link_mes(d, hoje, dias, turma_id):
    # link pra outro mes: abre no ultimo dia de aula daquele mes, sem passar de hoje
    alvo = ultimo_dia_com_aula(min(_fim_do_mes(d), hoje), dias)
    return url_for("professor.chamada", turma_id=turma_id, data=alvo.isoformat())


def _calendario_mes(data_ref, hoje, dias_aula, turma, taxa_por_dia):
    # monta o calendario do mes com as semanas comecando na segunda
    # cada dia de aula ganha uma cor pela frequencia da turma naquele dia
    primeiro = data_ref.replace(day=1)
    ultimo = _fim_do_mes(data_ref)
    d = primeiro - timedelta(days=primeiro.weekday())
    semanas = []
    while d <= ultimo:
        semana = []
        for _ in range(7):
            aula = d.month == data_ref.month and eh_dia_com_aula(d, dias_aula)
            taxa = taxa_por_dia.get(d)
            nivel = None
            if aula and d <= hoje:
                nivel = "vazio" if taxa is None else ("bom" if taxa >= 75 else "medio" if taxa >= 50 else "ruim")
            semana.append({
                "dia": d.day,
                "no_mes": d.month == data_ref.month,
                "aula": aula,
                "futuro": d > hoje,
                "hoje": d == hoje,
                "selecionado": d == data_ref,
                "nivel": nivel,
                "taxa": taxa,
                "url": url_for("professor.chamada", turma_id=turma.id, data=d.isoformat())
                       if aula and d <= hoje else None,
            })
            d += timedelta(days=1)
        semanas.append(semana)

    mes_anterior = primeiro - timedelta(days=1)
    proximo_mes = ultimo + timedelta(days=1)
    return {
        "titulo": f"{MESES[data_ref.month - 1]} {data_ref.year}",
        "semanas": semanas,
        "cabecalho": [n[:3] for n in NOMES_DIAS],
        "anterior": _link_mes(mes_anterior, hoje, dias_aula, turma.id),
        "proximo": _link_mes(proximo_mes, hoje, dias_aula, turma.id) if proximo_mes <= hoje else None,
        "hoje": url_for("professor.chamada", turma_id=turma.id),
    }


# ---------- tela de chamada ----------

@professor.route("/chamada")
@requer("professor")
def chamada():
    prof = usuario_atual()
    turma_id = request.args.get("turma_id", type=int)
    hoje = hoje_local()

    # sem turma na url, abre a primeira turma do professor
    turmas = prof.turmas
    turma = next((t for t in turmas if t.id == turma_id), turmas[0] if turmas else None)
    vinculo = prof.vinculo(turma.id) if turma else None
    dias_prof = vinculo.dias_semana if vinculo else ()
    data_selecionada = _normalizar_data_chamada(request.args.get("data"), dias_prof)
    alunos, presentes, faltas = [], 0, 0
    calendario = None

    if turma and dias_prof:
        ids = [a.id for a in turma.alunos]
        inicio_mes, fim_mes = data_selecionada.replace(day=1), _fim_do_mes(data_selecionada)
        registros = Presenca.query.filter(
            Presenca.aluno_id.in_(ids),
            Presenca.data.between(inicio_mes, fim_mes)
        ).all() if ids else []

        # numa passada so: a chamada do dia escolhido e os totais do mes
        # (contando so os dias em que esse professor da aula)
        mapa, ok_mes, ok_dia, dias_com_chamada = {}, {}, {}, set()
        for r in registros:
            if not eh_dia_com_aula(r.data, dias_prof):
                continue
            dias_com_chamada.add(r.data)
            presente = r.status in ("presente", "atraso")
            ok_mes[r.aluno_id] = ok_mes.get(r.aluno_id, 0) + presente
            ok_dia[r.data] = ok_dia.get(r.data, 0) + presente
            if r.data == data_selecionada:
                mapa.setdefault(r.aluno_id, {})[r.aula] = r.status

        aulas_por_dia_turma = len(ids) * AULAS_POR_DIA
        taxa_por_dia = {d: round(100 * ok_dia.get(d, 0) / aulas_por_dia_turma)
                        for d in dias_com_chamada}
        calendario = _calendario_mes(data_selecionada, hoje, dias_prof, turma, taxa_por_dia)
        total_aulas_mes = len(dias_com_chamada) * AULAS_POR_DIA

        # aula sem registro conta como falta
        for a in sorted(turma.alunos, key=lambda x: (x.numero_chamada or 999, x.nome)):
            st = [mapa.get(a.id, {}).get(i, "falta") for i in range(AULAS_POR_DIA)]
            tem_presenca = any(s in ("presente", "atraso") for s in st)
            faltou_dia = all(s == "falta" for s in st)
            presentes += int(tem_presenca)
            faltas += int(faltou_dia)
            alunos.append({
                "id": a.id,
                "nome": a.nome,
                "matricula": a.matricula,
                "iniciais": "".join(p[0] for p in a.nome.split()[:2]).upper(),
                "status": st,
                "freq_mes": round(100 * ok_mes.get(a.id, 0) / total_aulas_mes) if total_aulas_mes else None,
            })

    eh_hoje = data_selecionada == hoje
    pode_editar = eh_hoje and eh_dia_com_aula(hoje, dias_prof)

    return render_template(
        "professor/frequencia.html",
        turmas=turmas,
        turma_selecionada=turma,
        alunos=alunos,
        total_matriculados=len(alunos),
        total_presentes=presentes,
        total_faltas=faltas,
        media_frequencia=turma.frequencia_media if turma else 0,
        data_iso=data_selecionada.isoformat(),
        data_exibicao=data_selecionada.strftime("%d/%m/%Y"),
        eh_hoje=eh_hoje,
        pode_editar=pode_editar,
        dia_nome=NOMES_DIAS[data_selecionada.weekday()],
        mes_nome=MESES[data_selecionada.month - 1],
        dias_prof=dias_prof,
        dias_prof_nomes=vinculo.dias_nomes if vinculo else "",
        calendario=calendario,
    )


# ---------- alterar a chamada (cliques nas barrinhas) ----------

def _dados_postagem():
    # a data vem na url ou no json, e a senha do admin so vem quando e dia anterior
    dados = request.get_json(silent=True) or {}
    valor = request.args.get("data") or dados.get("data") or ""
    senha_admin = (dados.get("admin_senha") or "").strip()
    try:
        data_requisitada = date.fromisoformat(valor)
    except (TypeError, ValueError):
        data_requisitada = None
    return data_requisitada, senha_admin


def _senha_admin_valida(senha):
    # vale a senha de qualquer admin
    if not senha:
        return False
    return any(adm.check_senha(senha) for adm in Admin.query.all())


def _pode_alterar_data(data_requisitada, senha_admin, dias):
    # devolve (pode, mensagem de erro)
    hoje = hoje_local()
    if data_requisitada is None:
        return False, "Data inválida."
    if data_requisitada > hoje:
        return False, "Não é possível alterar uma chamada futura."
    if not eh_dia_com_aula(data_requisitada, dias):
        return False, "Você não tem aula nesta turma neste dia da semana."
    if data_requisitada == hoje:
        return True, None
    if not _senha_admin_valida(senha_admin):
        return False, "Para alterar uma chamada anterior, informe a senha de um administrador."
    return True, None


def _alterar(aluno_id, barra, regra):
    # parte comum do toggle e do atraso
    # regra recebe o status atual e devolve o novo
    if barra < 0 or barra >= AULAS_POR_DIA:
        return jsonify(erro="Aula inválida."), 400

    # o professor so mexe em aluno das turmas dele
    aluno = db.get_or_404(Aluno, aluno_id)
    vinculo = db.session.get(ProfessorTurma, (session["uid"], aluno.turma_id)) if aluno.turma_id else None
    if not vinculo:
        return jsonify(erro="Aluno não pertence às suas turmas."), 403

    data_requisitada, senha_admin = _dados_postagem()
    permitido, erro = _pode_alterar_data(data_requisitada, senha_admin, vinculo.dias_semana)
    if not permitido:
        return jsonify(erro=erro), 403

    p = Presenca.query.filter_by(aluno_id=aluno_id, data=data_requisitada, aula=barra).first()
    if not p:
        # aula sem registro e falta, entao comeca como falta antes de aplicar a regra
        p = Presenca(aluno_id=aluno_id, data=data_requisitada, aula=barra, status="falta")
        db.session.add(p)

    p.status, p.origem = regra(p.status), "professor"
    db.session.commit()
    return jsonify(estado=p.status, media_frequencia=aluno.turma.frequencia_media)


@professor.route("/toggle/<int:aluno_id>/<int:barra>", methods=["POST"])
@requer("professor")
def toggle(aluno_id, barra):
    # clique normal: presente <-> falta
    return _alterar(aluno_id, barra, lambda s: "falta" if s == "presente" else "presente")


@professor.route("/atraso/<int:aluno_id>/<int:barra>", methods=["POST"])
@requer("professor")
def atraso(aluno_id, barra):
    # botao direito: presente <-> atraso, so nas duas primeiras aulas
    if barra > 1:
        return jsonify(erro="Atraso só pode ser marcado nas aulas 1 e 2."), 400
    return _alterar(aluno_id, barra, lambda s: "presente" if s == "atraso" else "atraso")
