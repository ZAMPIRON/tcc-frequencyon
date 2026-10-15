# pagina do aluno: frequencia, historico dia a dia, csv e justificativa de falta
# o admin usa a mesma tela pra ver um aluno (render_detalhes com visao="admin")
import csv
import io
from datetime import date

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from database import (db, Aluno, Justificativa, Presenca, AULAS_POR_DIA, NOMES_DIAS,
                      agora_local, eh_dia_com_aula, hoje_local)
from email_service import enviar_justificativa
from .comum import requer, usuario_atual

area_aluno = Blueprint("aluno", __name__, url_prefix="/aluno")


def historico_aluno(aluno):
    # junta tudo que a tela de detalhes precisa: uma linha por dia de aula,
    # os totais em porcentagem e quais dias ainda podem ser justificados
    hoje = hoje_local()
    turma = aluno.turma
    dias_aula = turma.dias_aula if turma else ()
    linhas, justificaveis = [], []
    presentes = atrasos = total = 0

    if dias_aula:
        # dias em que teve chamada na turma (mesmo criterio do Aluno.frequencia)
        datas = {d for (d,) in db.session.query(Presenca.data).join(Aluno)
                 .filter(Aluno.turma_id == turma.id).distinct()
                 if eh_dia_com_aula(d, dias_aula)}
        mapa = {}
        for p in aluno.presencas:
            mapa.setdefault(p.data, {})[p.aula] = p.status
        justificativas = {j.data: j for j in aluno.justificativas}

        # se hoje tem aula mas ninguem passou ainda, mostra o dia como pendente
        pendente_hoje = eh_dia_com_aula(hoje, dias_aula) and hoje not in datas
        for d in sorted(datas | ({hoje} if pendente_hoje else set()), reverse=True):
            sem_chamada = d not in datas
            st = (["pendente"] * AULAS_POR_DIA if sem_chamada else
                  [mapa.get(d, {}).get(i, "falta") for i in range(AULAS_POR_DIA)])
            if not sem_chamada:
                total += AULAS_POR_DIA
                presentes += st.count("presente")
                atrasos += st.count("atraso")
            faltas_dia = st.count("falta")
            linhas.append({
                "data": d,
                "dia_nome": NOMES_DIAS[d.weekday()],
                "professores": [v.professor for v in turma.vinculos if d.weekday() in v.dias_semana],
                "status": st,
                "faltas": faltas_dia,
                "atrasos": st.count("atraso"),
                "justificativa": justificativas.get(d),
            })
            # da pra justificar dia com falta que nunca foi justificado ou que foi recusado
            if faltas_dia and (d not in justificativas or justificativas[d].status == "recusada"):
                justificaveis.append(d)

    pct_presenca = round(100 * presentes / total) if total else 0
    pct_atraso = round(100 * atrasos / total) if total else 0
    pct_falta = 100 - pct_presenca - pct_atraso if total else 0
    return {
        "linhas": linhas,
        "justificaveis": justificaveis,
        "total_aulas": total,
        "pct_presenca": pct_presenca,
        "pct_atraso": pct_atraso,
        "pct_falta": pct_falta,
        "frequencia": aluno.frequencia,
    }


def render_detalhes(aluno, visao):
    # visao e "aluno" ou "admin", o template muda os botoes de acordo
    return render_template("aluno/detalhes.html", aluno=aluno, visao=visao,
                           **historico_aluno(aluno))


def exportar_csv(aluno):
    # csv separado por ";" e com bom no comeco pra abrir certinho no excel
    dados = historico_aluno(aluno)
    rotulo = {"presente": "P", "atraso": "A", "falta": "F", "pendente": "-"}
    saida = io.StringIO()
    w = csv.writer(saida, delimiter=";")
    w.writerow(["Aluno", aluno.nome, "Matrícula", aluno.matricula,
                "Turma", aluno.turma.nome if aluno.turma else "-"])
    w.writerow(["Frequência", f"{dados['frequencia']}%", "Presenças", f"{dados['pct_presenca']}%",
                "Faltas", f"{dados['pct_falta']}%", "Atrasos", f"{dados['pct_atraso']}%"])
    w.writerow([])
    w.writerow(["Data", "Dia", "Professor(es)"] + [f"Aula {i + 1}" for i in range(AULAS_POR_DIA)]
               + ["Faltas", "Atrasos", "Justificativa"])
    for l in dados["linhas"]:
        j = l["justificativa"]
        w.writerow([l["data"].strftime("%d/%m/%Y"), l["dia_nome"],
                    ", ".join(p.nome for p in l["professores"])]
                   + [rotulo[s] for s in l["status"]]
                   + [l["faltas"], l["atrasos"], j.status if j else ""])
    w.writerow([])
    w.writerow(["Legenda: P = presente, A = atraso, F = falta, - = chamada ainda não lançada"])
    nome = f"frequencia_{aluno.matricula}.csv"
    return Response("﻿" + saida.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={nome}"})


@area_aluno.route("/")
@requer("aluno")
def painel():
    return render_detalhes(usuario_atual(), "aluno")


@area_aluno.route("/exportar")
@requer("aluno")
def exportar():
    return exportar_csv(usuario_atual())


@area_aluno.route("/justificar", methods=["POST"])
@requer("aluno")
def justificar():
    aluno = usuario_atual()
    motivo = (request.form.get("motivo") or "").strip()
    try:
        data_falta = date.fromisoformat(request.form.get("data", ""))
    except ValueError:
        data_falta = None

    if data_falta not in historico_aluno(aluno)["justificaveis"]:
        flash("Escolha um dia com falta que ainda não foi justificado.", "danger")
    elif len(motivo) < 5:
        flash("Descreva o motivo da falta.", "danger")
    else:
        # se ja tinha uma recusada pro mesmo dia, reaproveita e volta pra pendente
        j = Justificativa.query.filter_by(aluno_id=aluno.id, data=data_falta).first()
        if not j:
            j = Justificativa(aluno_id=aluno.id, data=data_falta)
            db.session.add(j)
        j.motivo, j.status, j.criada_em, j.respondida_em = motivo, "pendente", agora_local(), None
        db.session.commit()
        # o e-mail sai em segundo plano, o aluno nao fica esperando
        enviar_justificativa(aluno, j, url_for("admin.detalhes_aluno", id=aluno.id, _external=True))
        flash("Justificativa enviada! Aguarde a análise da coordenação.", "success")
    return redirect(url_for("aluno.painel"))
