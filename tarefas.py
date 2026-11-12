"""tarefas.py - o que o servidor faz sozinho, em segundo plano:
alertas de frequência baixa (RF20), backup do banco (RNF10) e aviso de totem sem sinal (RNF16)."""
import glob
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from database import (db, Aluno, Dispositivo, Turma, ALERTA_FREQUENCIA, agora_local, blocos_abertos,
                      eh_dia_com_aula)
from email_service import enviar_alerta_frequencia, enviar_aviso_totem, smtp_configurado

TOTEM_SEM_SINAL = int(os.getenv("TOTEM_SEM_SINAL", "10"))      # minutos sem imagens = totem sem sinal
BACKUPS_GUARDADOS = int(os.getenv("BACKUPS_GUARDADOS", "30"))
_totens_avisados = set()        # ids dos totens que ja geraram e-mail nesta queda


# ---------- RF20: alerta de frequencia ----------

def alunos_para_alertar(agora=None):
    """Alunos abaixo de ALERTA_FREQUENCIA que ainda não receberam aviso nos últimos 7 dias."""
    agora = agora or agora_local()
    lista = []
    for a in Aluno.query.filter(Aluno.turma_id.isnot(None)):
        if not a.presencas:
            continue
        freq = a.frequencia
        if freq < ALERTA_FREQUENCIA and not (a.alerta_enviado_em and agora - a.alerta_enviado_em < timedelta(days=7)):
            lista.append((a, freq))
    return lista


def verificar_alertas(app, agora=None):
    """Manda o e-mail de aviso para quem está perto do limite de faltas. Devolve (enviados, sem_email)."""
    with app.app_context():
        agora = agora or agora_local()
        enviados, sem_email = [], []
        if not smtp_configurado():
            return enviados, sem_email
        for aluno, freq in alunos_para_alertar(agora):
            if not aluno.email:
                sem_email.append(aluno.nome)
                continue
            enviar_alerta_frequencia(aluno, freq)
            aluno.alerta_enviado_em = agora
            enviados.append(aluno.nome)
        db.session.commit()
        return enviados, sem_email


# ---------- RNF10: backup ----------

def pasta_backups(app):
    return os.path.join(app.instance_path, "backups")


def fazer_backup(app):
    """Copia o banco SQLite (com a API de backup, seguro mesmo com o site em uso) para instance/backups.
    Guarda só as BACKUPS_GUARDADOS cópias mais novas. Devolve o caminho da cópia ou None."""
    with app.app_context():
        if db.engine.url.get_backend_name() != "sqlite":
            return None
        pasta = pasta_backups(app)
        os.makedirs(pasta, exist_ok=True)
        destino = os.path.join(pasta, f"frequencyon-{agora_local():%Y%m%d-%H%M%S}.db")
        origem = db.engine.raw_connection()
        try:
            alvo = sqlite3.connect(destino)
            origem.driver_connection.backup(alvo)
            alvo.close()
        finally:
            origem.close()
        for velho in sorted(glob.glob(os.path.join(pasta, "frequencyon-*.db")))[:-BACKUPS_GUARDADOS]:
            os.remove(velho)
        print(f"[backup] {destino}")
        return destino


def ultimo_backup(app):
    """(data, quantidade) do backup mais novo, ou (None, 0)."""
    arquivos = sorted(glob.glob(os.path.join(pasta_backups(app), "frequencyon-*.db")))
    if not arquivos:
        return None, 0
    return datetime.fromtimestamp(os.path.getmtime(arquivos[-1])), len(arquivos)


# ---------- RNF16: totem sem sinal ----------

def tem_aula_agora(agora):
    return any(t.modelo and eh_dia_com_aula(agora.date(), t.dias_aula) and blocos_abertos(t, agora)
               for t in Turma.query.all())


def totens_sem_sinal(agora=None):
    """[(totem, minutos)] dos totens liberados que pararam de mandar imagens há mais de TOTEM_SEM_SINAL min."""
    agora = agora or agora_local()
    lista = []
    for d in Dispositivo.query.all():
        if d.liberado_ate and d.liberado_ate > agora and d.ultimo_uso:
            minutos = int((agora - d.ultimo_uso).total_seconds() // 60)
            if minutos >= TOTEM_SEM_SINAL:
                lista.append((d, minutos))
    return lista


def verificar_totens(app, agora=None):
    """Durante o horário de aula, avisa a coordenação por e-mail uma vez por queda de cada totem."""
    with app.app_context():
        agora = agora or agora_local()
        caidos = totens_sem_sinal(agora) if tem_aula_agora(agora) else []
        ids = {d.id for d, _ in caidos}
        _totens_avisados.intersection_update(ids)          # totem que voltou pode avisar de novo na próxima queda
        novos = [(d, m) for d, m in caidos if d.id not in _totens_avisados]
        for d, minutos in novos:
            if enviar_aviso_totem(d.nome, minutos):
                _totens_avisados.add(d.id)
        return caidos


# ---------- agenda ----------

def iniciar_tarefas(app):
    """Roda em segundo plano enquanto o servidor estiver no ar: backup uma vez por dia,
    alertas de frequência a cada 6 h e conferência dos totens a cada 5 min."""
    def laco():
        ultimo = {"backup": 0.0, "alertas": 0.0, "totens": 0.0}
        while True:
            agora = time.time()
            for nome, intervalo, tarefa in (("backup", 24 * 3600, fazer_backup), ("alertas", 6 * 3600, verificar_alertas),
                                            ("totens", 300, verificar_totens)):
                if agora - ultimo[nome] >= intervalo:
                    ultimo[nome] = agora
                    try:
                        tarefa(app)
                    except Exception as e:          # uma tarefa com problema não derruba as outras
                        print(f"[tarefas] {nome} falhou: {e}")
            time.sleep(60)
    threading.Thread(target=laco, name="tarefas", daemon=True).start()
