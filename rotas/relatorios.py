# relatorios da coordenacao: a pagina com os graficos e a planilha do excel
# as rotas entram no mesmo blueprint do admin, entao continuam em /admin/relatorios
import io

from datetime import date

from flask import Response, current_app, flash, render_template, request
from openpyxl import Workbook
from sqlalchemy import case, func
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from database import (db, Aluno, Justificativa, Presenca, Professor, Turma,
                      agora_local, eh_dia_com_aula, hoje_local)
from .admin import admin
from .comum import requer


def _situacao(freq):
    return "Regular" if freq >= 75 else ("Atenção" if freq >= 50 else "Crítico")


def _periodo():
    # le ?inicio=AAAA-MM-DD&fim=AAAA-MM-DD da url; sem datas = todo o historico
    try:
        inicio = date.fromisoformat(request.args["inicio"]) if request.args.get("inicio") else None
        fim = date.fromisoformat(request.args["fim"]) if request.args.get("fim") else None
    except ValueError:
        return None, None, "Data inválida no filtro."
    if inicio and fim and inicio > fim:
        return None, None, "A data inicial precisa ser antes da final."
    return inicio, fim, None


def _rotulo_periodo(inicio, fim):
    if inicio and fim:
        return f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y}"
    if inicio:
        return f"desde {inicio:%d/%m/%Y}"
    if fim:
        return f"até {fim:%d/%m/%Y}"
    return "Todo o período"


def _dados_relatorio(inicio=None, fim=None):
    # numeros que aparecem na pagina de relatorios, na planilha e no pdf (so do periodo escolhido)
    alunos, turmas = Aluno.query.all(), Turma.query.all()
    periodo = ([Presenca.data >= inicio] if inicio else []) + ([Presenca.data <= fim] if fim else [])
    freq = {a.id: a.frequencia_periodo(inicio, fim) for a in alunos}
    com_registro = {aid for (aid,) in db.session.query(Presenca.aluno_id).filter(*periodo).distinct()}
    # aluno sem turma não tem frequência (seria 0%), então fica fora da média
    freqs = [freq[a.id] for a in alunos if a.turma_id]

    freq_turma = {t.id: round(sum(freq[a.id] for a in t.alunos) / len(t.alunos), 1) if t.alunos else 0 for t in turmas}
    por_curso = {}
    for t in turmas:
        por_curso.setdefault(t.curso, []).append(freq_turma[t.id])

    # frequencia mes a mes com o mesmo criterio do Aluno.frequencia: cada dia com chamada
    # na turma vale as aulas do horario dela (CAI 4, tecnico 10...) para cada aluno, e aula sem registro conta como falta
    turma_do_aluno = {x.id: x.turma_id for x in alunos}
    dias_aula = {t.id: t.dias_aula for t in turmas}
    alunos_na_turma = {t.id: len(t.alunos) for t in turmas}
    aulas_da_turma = {t.id: t.aulas_por_dia for t in turmas}
    presentes_no_dia, dias_com_chamada = {}, set()
    ok = func.sum(case((Presenca.status.in_(("presente", "atraso")), 1), else_=0))
    for tid, data_, aula, n_ok in (db.session.query(Aluno.turma_id, Presenca.data, Presenca.aula, ok)
                                   .join(Aluno, Presenca.aluno_id == Aluno.id).filter(*periodo)
                                   .group_by(Aluno.turma_id, Presenca.data, Presenca.aula)):
        if tid is None or not eh_dia_com_aula(data_, dias_aula.get(tid, ())) or aula >= aulas_da_turma[tid]:
            continue
        dias_com_chamada.add((tid, data_))
        presentes_no_dia[(tid, data_)] = presentes_no_dia.get((tid, data_), 0) + n_ok

    # presente/atraso/falta de cada aluno no periodo (so em dias de aula da turma dele)
    contagens = {a.id: [0, 0, 0] for a in alunos}
    for aid, data_, status, n_st in (db.session.query(Presenca.aluno_id, Presenca.data, Presenca.status, func.count())
                                     .filter(*periodo).group_by(Presenca.aluno_id, Presenca.data, Presenca.status)):
        tid = turma_do_aluno.get(aid)
        if aid in contagens and tid and eh_dia_com_aula(data_, dias_aula.get(tid, ())) and status in ("presente", "atraso", "falta"):
            contagens[aid][("presente", "atraso", "falta").index(status)] += n_st
    meses = {}
    for tid, dia in dias_com_chamada:
        ok, tot = meses.get(dia.strftime("%Y-%m"), (0, 0))
        meses[dia.strftime("%Y-%m")] = (ok + presentes_no_dia.get((tid, dia), 0),
                                         tot + alunos_na_turma[tid] * aulas_da_turma[tid])
    chaves = sorted(meses) if (inicio or fim) else sorted(meses)[-6:]   # sem filtro: os ultimos 6 meses

    n = len(alunos)
    em_risco = sum(1 for x in alunos if x.id in com_registro and freq[x.id] < 75)
    media_prof = {}
    for prof in Professor.query.all():
        v = [freq_turma[t.id] for t in prof.turmas]
        media_prof[prof] = round(sum(v) / len(v)) if v else 0
    return dict(
        alunos=alunos, turmas=turmas, total_alunos=n, freq=freq, freq_turma=freq_turma, com_registro=com_registro,
        contagens=contagens,
        inicio=inicio, fim=fim, rotulo_periodo=_rotulo_periodo(inicio, fim),
        media_geral=round(sum(freqs) / len(freqs)) if freqs else 0,
        alunos_criticos=em_risco,
        taxa_evasao=round(100 * em_risco / n, 1) if n else 0,
        cursos_labels=list(por_curso), cursos_valores=[round(sum(v) / len(v)) for v in por_curso.values()],
        meses_labels=[k[5:] + "/" + k[:4] for k in chaves],
        meses_valores=[round(100 * meses[k][0] / meses[k][1]) if meses[k][1] else 0 for k in chaves],
        top_professores=[p for p, _ in sorted(media_prof.items(), key=lambda x: x[1], reverse=True)[:5]],
        media_prof=media_prof)


@admin.route("/relatorios")
@requer("admin")
def relatorios():
    inicio, fim, erro = _periodo()
    if erro:
        flash(erro, "danger")
    from tarefas import ultimo_backup
    backup_em, backups = ultimo_backup(current_app)
    return render_template("admin/relatorios.html", backup_em=backup_em, backups=backups, **_dados_relatorio(inicio, fim))


# ---------- planilha ----------

TITULO_FONTE = Font(bold=True, size=16, color="3B2FBF")
CAB_FONTE = Font(bold=True, color="FFFFFF")
CAB_FUNDO = PatternFill("solid", fgColor="5B4BFF")
SECAO_FONTE = Font(bold=True, size=12, color="3B2FBF")
CORES_SITUACAO = {"Regular": "D1FAE5", "Atenção": "FEF3C7", "Crítico": "FEE2E2"}
CORES_JUSTIFICATIVA = {"aceita": "D1FAE5", "pendente": "FEF3C7", "recusada": "FEE2E2"}


def _tabela(ws, linha, cabecalho, linhas, larguras, formatos=None, coluna_cor=None, cores=None):
    # escreve uma tabela na aba a partir da linha passada e devolve a proxima linha livre
    # formatos = {indice da coluna: formato do numero}, ex: {8: "0%"}
    # coluna_cor + cores pinta a linha inteira de acordo com o valor daquela coluna
    for c, texto in enumerate(cabecalho, 1):
        cel = ws.cell(row=linha, column=c, value=texto)
        cel.font, cel.fill = CAB_FONTE, CAB_FUNDO
        cel.alignment = Alignment(vertical="center", wrap_text=True)
    for i, valores in enumerate(linhas, linha + 1):
        for c, v in enumerate(valores, 1):
            cel = ws.cell(row=i, column=c, value=v)
            if formatos and (c - 1) in formatos:
                cel.number_format = formatos[c - 1]
        if coluna_cor is not None and valores[coluna_cor] in cores:
            fundo = PatternFill("solid", fgColor=cores[valores[coluna_cor]])
            for c in range(1, len(valores) + 1):
                ws.cell(row=i, column=c).fill = fundo
    for c, largura in enumerate(larguras, 1):
        ws.column_dimensions[get_column_letter(c)].width = max(
            ws.column_dimensions[get_column_letter(c)].width or 0, largura)
    return linha + len(linhas) + 1


@admin.route("/relatorios/exportar")
@requer("admin")
def exportar_relatorio():
    # planilha com as abas: resumo, alunos, turmas, professores, em risco e justificativas
    inicio, fim, _ = _periodo()
    dados = _dados_relatorio(inicio, fim)
    wb = Workbook()
    linhas_alunos = _linhas_alunos(dados)

    # aba resumo
    ws = wb.active
    ws.title = "Resumo"
    ws["A1"] = "FrequencyON - Relatório de Frequência"
    ws["A1"].font = TITULO_FONTE
    ws["A2"] = f"Período: {dados['rotulo_periodo']} · gerado em " + agora_local().strftime("%d/%m/%Y %H:%M")
    ws["A2"].font = Font(italic=True, color="6B7280")

    ws["A4"] = "Indicadores gerais"
    ws["A4"].font = SECAO_FONTE
    indicadores = [
        ["Alunos matriculados", dados["total_alunos"]],
        ["Turmas", len(dados["turmas"])],
        ["Professores", Professor.query.count()],
        ["Frequência média da instituição", dados["media_geral"] / 100],
        ["Alunos em risco (frequência < 75%)", dados["alunos_criticos"]],
        ["Taxa de risco", dados["taxa_evasao"] / 100],
        ["Justificativas pendentes", Justificativa.query.filter_by(status="pendente").count()],
    ]
    linha = _tabela(ws, 5, ["Indicador", "Valor"], indicadores, [40, 16])
    ws.cell(row=9, column=2).number_format = "0%"     # frequencia media
    ws.cell(row=11, column=2).number_format = "0.0%"  # taxa de risco

    linha += 1
    ws.cell(row=linha, column=1, value="Frequência mensal (últimos 6 meses com aula)").font = SECAO_FONTE
    linha = _tabela(ws, linha + 1, ["Mês", "Frequência"],
                    [[m, v / 100] for m, v in zip(dados["meses_labels"], dados["meses_valores"])],
                    [40, 16], {1: "0%"})
    linha += 1
    ws.cell(row=linha, column=1, value="Frequência por curso").font = SECAO_FONTE
    _tabela(ws, linha + 1, ["Curso", "Frequência"],
            [[c, v / 100] for c, v in zip(dados["cursos_labels"], dados["cursos_valores"])],
            [40, 16], {1: "0%"})

    # aba alunos
    cab_alunos = ["Matrícula", "Nome", "Turma", "Curso", "Dias de aula",
                  "Aulas presente", "Aulas com atraso", "Aulas com falta", "Frequência", "Situação"]
    larg_alunos = [12, 32, 14, 34, 18, 14, 16, 15, 12, 14]
    ws = wb.create_sheet("Alunos")
    _tabela(ws, 1, cab_alunos, linhas_alunos, larg_alunos, {8: "0%"}, 9, CORES_SITUACAO)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    # aba turmas
    ws = wb.create_sheet("Turmas")
    _tabela(ws, 1, ["Turma", "Curso", "Professores", "Dias de aula", "Alunos", "Frequência média", "Alunos em risco"],
            [[t.nome, t.curso, t.nomes_professores, t.dias_aula_nomes, len(t.alunos), dados["freq_turma"][t.id] / 100,
              sum(1 for a in t.alunos if a.id in dados["com_registro"] and dados["freq"][a.id] < 75)]
             for t in sorted(dados["turmas"], key=lambda t: t.nome)],
            [14, 34, 30, 18, 9, 17, 15], {5: "0.0%"})
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    # aba professores
    ws = wb.create_sheet("Professores")
    _tabela(ws, 1, ["Professor", "E-mail", "Departamento", "Turmas (dias de aula)", "Frequência média das turmas"],
            [[p.nome, p.email, p.departamento or "-",
              "; ".join(f"{v.turma.nome} ({v.dias_nomes})"
                        for v in sorted(p.vinculos, key=lambda v: v.turma.nome)) or "-",
              dados["media_prof"][p] / 100]
             for p in sorted(dados["media_prof"], key=lambda p: p.nome)],
            [28, 30, 18, 40, 16], {4: "0%"})
    ws.freeze_panes = "A2"

    # aba em risco (atencao e critico, do pior pro melhor)
    ws = wb.create_sheet("Em risco")
    risco = sorted((l for l in linhas_alunos if l[9] in ("Atenção", "Crítico")), key=lambda l: l[8])
    if risco:
        _tabela(ws, 1, cab_alunos, risco, larg_alunos, {8: "0%"}, 9, CORES_SITUACAO)
        ws.freeze_panes = "A2"
    else:
        ws["A1"] = "Nenhum aluno com frequência abaixo de 75%."

    # aba justificativas
    ws = wb.create_sheet("Justificativas")
    js = [j for j in Justificativa.query.order_by(Justificativa.data.desc())
          if (not inicio or j.data >= inicio) and (not fim or j.data <= fim)]
    if js:
        _tabela(ws, 1, ["Data da falta", "Aluno", "Matrícula", "Turma", "Motivo", "Situação",
                        "Enviada em", "Respondida em"],
                [[j.data, j.aluno.nome, j.aluno.matricula, j.aluno.turma.nome if j.aluno.turma else "-",
                  j.motivo, j.status, j.criada_em, j.respondida_em] for j in js],
                [13, 28, 12, 12, 50, 12, 17, 17],
                {0: "DD/MM/YYYY", 6: "DD/MM/YYYY HH:MM", 7: "DD/MM/YYYY HH:MM"},
                5, CORES_JUSTIFICATIVA)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
    else:
        ws["A1"] = "Nenhuma justificativa enviada."

    saida = io.BytesIO()
    wb.save(saida)
    nome = f"relatorio_frequencyon_{hoje_local().isoformat()}.xlsx"
    return Response(saida.getvalue(),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename={nome}"})


def _linhas_alunos(dados):
    # uma linha por aluno (ordem: turma, nome) com as contagens e a frequencia do periodo
    linhas = []
    for a in sorted(dados["alunos"], key=lambda a: ((a.turma.nome if a.turma else "~"), a.nome)):
        pres, atr, fal = dados["contagens"][a.id]
        f = dados["freq"][a.id]
        linhas.append([a.matricula, a.nome, a.turma.nome if a.turma else "Sem turma",
                       a.turma.curso if a.turma else "-", a.turma.dias_aula_nomes if a.turma else "-",
                       pres, atr, fal, f / 100, _situacao(f) if a.id in dados["com_registro"] else "Sem registros"])
    return linhas


# ---------- pdf (RF19) ----------

@admin.route("/relatorios/pdf")
@requer("admin")
def exportar_relatorio_pdf():
    # o mesmo relatorio da pagina, em pdf (a4 deitado): indicadores, turmas, alunos e quem esta em risco
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    inicio, fim, _ = _periodo()
    dados = _dados_relatorio(inicio, fim)
    estilos = getSampleStyleSheet()
    roxo = colors.HexColor("#5B4BFF")

    def tabela(cabecalho, linhas, larguras):
        t = Table([cabecalho] + linhas, colWidths=[w * cm for w in larguras], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), roxo), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#C9CDD6")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F5F8")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    pct = lambda v: f"{round(v * 100)}%"
    linhas_alunos = _linhas_alunos(dados)
    corpo = [
        Paragraph("FrequencyON - Relatório de Frequência", estilos["Title"]),
        Paragraph(f"Período: {dados['rotulo_periodo']} · gerado em {agora_local():%d/%m/%Y %H:%M}", estilos["Normal"]),
        Spacer(1, 0.4 * cm),
        tabela(["Indicador", "Valor"], [
            ["Alunos matriculados", str(dados["total_alunos"])], ["Turmas", str(len(dados["turmas"]))],
            ["Frequência média da instituição", f"{dados['media_geral']}%"],
            ["Alunos em risco (frequência < 75%)", str(dados["alunos_criticos"])],
            ["Taxa de risco", f"{dados['taxa_evasao']}%"]], [9, 4]),
        Spacer(1, 0.5 * cm), Paragraph("Turmas", estilos["Heading2"]),
        tabela(["Turma", "Curso", "Professores", "Dias de aula", "Alunos", "Frequência"],
               [[t.nome, t.curso, t.nomes_professores, t.dias_aula_nomes, str(len(t.alunos)), f"{dados['freq_turma'][t.id]}%"]
                for t in sorted(dados["turmas"], key=lambda t: (t.nome, t.curso))], [3, 6.5, 6, 4.5, 2, 2.5]),
        Spacer(1, 0.5 * cm), Paragraph("Alunos", estilos["Heading2"]),
        tabela(["Matrícula", "Nome", "Turma", "Presente", "Atraso", "Falta", "Frequência", "Situação"],
               [[l[0], l[1], l[2], str(l[5]), str(l[6]), str(l[7]), pct(l[8]), l[9]] for l in linhas_alunos],
               [2.8, 7.5, 3, 2.2, 2.2, 2.2, 2.6, 3]),
        Spacer(1, 0.5 * cm), Paragraph("Em risco (frequência abaixo de 75%)", estilos["Heading2"]),
    ]
    risco = sorted((l for l in linhas_alunos if l[9] in ("Atenção", "Crítico")), key=lambda l: l[8])
    corpo.append(tabela(["Matrícula", "Nome", "Turma", "Frequência", "Situação"],
                        [[l[0], l[1], l[2], pct(l[8]), l[9]] for l in risco], [3, 9, 3.5, 3, 3]) if risco
                 else Paragraph("Nenhum aluno com frequência abaixo de 75%.", estilos["Normal"]))

    saida = io.BytesIO()
    SimpleDocTemplate(saida, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                      topMargin=1.5 * cm, bottomMargin=1.5 * cm, title="Relatório FrequencyON").build(corpo)
    nome = f"relatorio_frequencyon_{hoje_local().isoformat()}.pdf"
    return Response(saida.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={nome}"})
