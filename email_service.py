import os
import smtplib
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr
from html import escape


def carregar_env(caminho=".env"):
    """Lê CHAVE=valor do arquivo .env sem sobrescrever variáveis já definidas no sistema."""
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                chave, valor = linha.split("=", 1)
                os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def _config():
    return {
        "servidor": os.getenv("SMTP_SERVIDOR", "smtp.gmail.com"),
        "porta": int(os.getenv("SMTP_PORTA", "465")),
        "usuario": os.getenv("SMTP_USUARIO", ""),
        "senha": os.getenv("SMTP_SENHA", ""),
        "destino": os.getenv("EMAIL_JUSTIFICATIVAS", ""),
    }


def _enviar(cfg, msg, tentativas=3):
    for n in range(1, tentativas + 1):
        try:
            # 465 = SSL direto; 587 = STARTTLS (algumas redes travam o envio na 587)
            if cfg["porta"] == 465:
                conexao = smtplib.SMTP_SSL(cfg["servidor"], cfg["porta"], timeout=30)
            else:
                conexao = smtplib.SMTP(cfg["servidor"], cfg["porta"], timeout=30)
                conexao.starttls()
            with conexao as smtp:
                smtp.login(cfg["usuario"], cfg["senha"])
                smtp.send_message(msg)
            print(f"[email] enviado para {msg['To']}: {msg['Subject']}")
            return
        except smtplib.SMTPAuthenticationError as e:
            print(f"[email] usuário ou senha de app recusados pelo servidor: {e}")
            return
        except Exception as e:  # rede instável: tenta de novo; o aluno já recebeu a confirmação
            print(f"[email] tentativa {n}/{tentativas} falhou para '{msg['Subject']}': {e}")
            if n < tentativas:
                time.sleep(5 * n)


def enviar_justificativa(aluno, justificativa, link_admin):
    """Avisa a coordenação por e-mail que chegou uma justificativa (em segundo plano)."""
    cfg = _config()
    if not (cfg["usuario"] and cfg["senha"] and cfg["destino"]):
        print("[email] SMTP_USUARIO, SMTP_SENHA ou EMAIL_JUSTIFICATIVAS não configurados; e-mail não enviado.")
        return

    dias = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
    data = justificativa.data
    data_txt = f"{data.strftime('%d/%m/%Y')} ({dias[data.weekday()]})"
    turma = aluno.turma.nome if aluno.turma else "Sem turma"
    enviada = justificativa.criada_em.strftime("%d/%m/%Y às %H:%M")

    msg = EmailMessage()
    msg["Subject"] = f"Justificativa de falta - {aluno.nome} ({data.strftime('%d/%m/%Y')})"
    # o envio sai pela conta do sistema (não temos a senha do aluno), mas com o nome dele
    # como remetente e o "Responder" indo direto para o e-mail do aluno
    msg["From"] = formataddr((f"{aluno.nome} (via FrequencyON)", cfg["usuario"]))
    msg["To"] = cfg["destino"]
    if aluno.email:
        msg["Reply-To"] = formataddr((aluno.nome, aluno.email))
    email_aluno = aluno.email or "não cadastrado"

    msg.set_content(
        f"Nova justificativa de falta recebida pelo FrequencyON.\n\n"
        f"Aluno: {aluno.nome}\nE-mail: {email_aluno}\nMatrícula: {aluno.matricula}\nTurma: {turma}\n"
        f"Data da falta: {data_txt}\nEnviada em: {enviada}\n\n"
        f"Motivo:\n{justificativa.motivo}\n\n"
        f"Para aceitar ou recusar: {link_admin}\n"
    )

    linhas = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#6b7280">{r}</td>'
        f'<td style="padding:6px 0;font-weight:600">{escape(v)}</td></tr>'
        for r, v in (("Aluno", aluno.nome), ("E-mail", email_aluno), ("Matrícula", aluno.matricula), ("Turma", turma),
                     ("Data da falta", data_txt), ("Enviada em", enviada))
    )
    msg.add_alternative(f"""\
<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#111827">
  <div style="background:linear-gradient(135deg,#5b8cff,#a26bff,#ff4fd8);color:#fff;padding:20px 24px;border-radius:14px 14px 0 0">
    <div style="font-size:13px;opacity:.85">FrequencyON</div>
    <div style="font-size:20px;font-weight:700">Nova justificativa de falta</div>
  </div>
  <div style="border:1px solid #e5e7eb;border-top:0;padding:20px 24px;border-radius:0 0 14px 14px">
    <table style="border-collapse:collapse;font-size:14px">{linhas}</table>
    <div style="margin-top:16px;font-size:13px;color:#6b7280">Motivo</div>
    <div style="margin-top:6px;padding:12px 14px;background:#f5f7fb;border-radius:10px;font-size:14px;white-space:pre-wrap">{escape(justificativa.motivo)}</div>
    <a href="{escape(link_admin)}" style="display:inline-block;margin-top:20px;background:#5b8cff;color:#fff;text-decoration:none;padding:10px 18px;border-radius:10px;font-weight:600;font-size:14px">Analisar no painel</a>
  </div>
</div>""", subtype="html")

    threading.Thread(target=_enviar, args=(cfg, msg), daemon=True).start()


def smtp_configurado():
    cfg = _config()
    return bool(cfg["usuario"] and cfg["senha"])


def enviar_alerta_frequencia(aluno, frequencia):
    """RF20: avisa o aluno (em segundo plano) que a frequência dele está perto do mínimo de 75%."""
    cfg = _config()
    if not (smtp_configurado() and aluno.email):
        return False
    msg = EmailMessage()
    msg["Subject"] = f"FrequencyON: sua frequência está em {frequencia}%"
    msg["From"] = f"FrequencyON <{cfg['usuario']}>"
    msg["To"] = aluno.email
    msg.set_content(
        f"Olá, {aluno.nome}.\n\nSua frequência no FrequencyON está em {frequencia}%. "
        f"O mínimo exigido pela escola é 75%.\n\nSe alguma falta tiver motivo, envie a justificativa "
        f"pelo portal do aluno. Em caso de dúvida, procure a coordenação.\n")
    msg.add_alternative(f"""\
<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#111827">
  <div style="background:linear-gradient(135deg,#5b8cff,#a26bff,#ff4fd8);color:#fff;padding:20px 24px;border-radius:14px 14px 0 0">
    <div style="font-size:13px;opacity:.85">FrequencyON</div>
    <div style="font-size:20px;font-weight:700">Sua frequência está em {frequencia}%</div>
  </div>
  <div style="border:1px solid #e5e7eb;border-top:0;padding:20px 24px;border-radius:0 0 14px 14px;font-size:14px">
    <p>Olá, {escape(aluno.nome)}.</p>
    <p>O mínimo exigido pela escola é <b>75%</b>. Se alguma falta tiver motivo, envie a justificativa pelo portal do aluno.</p>
  </div>
</div>""", subtype="html")
    threading.Thread(target=_enviar, args=(cfg, msg), daemon=True).start()
    return True


def enviar_resumo_frequencia(nome, email, alunos):
    """RF20: avisa um professor ou admin quais alunos dele ficaram perto do mínimo. alunos = [(aluno, frequencia)]."""
    cfg = _config()
    if not (smtp_configurado() and email and alunos):
        return False
    msg = EmailMessage()
    msg["Subject"] = f"FrequencyON: {len(alunos)} aluno(s) com frequência baixa"
    msg["From"] = f"FrequencyON <{cfg['usuario']}>"
    msg["To"] = formataddr((nome, email))
    turma = lambda a: a.turma.nome if a.turma else "Sem turma"
    msg.set_content(
        f"Olá, {nome}.\n\nEstes alunos estão abaixo de {os.getenv('ALERTA_FREQUENCIA', '80')}% de frequência "
        f"(o mínimo da escola é 75%):\n\n"
        + "".join(f"- {a.nome} ({a.matricula}, {turma(a)}): {f}%\n" for a, f in alunos)
        + "\nCada aluno com e-mail cadastrado também recebeu o aviso.\n")
    linhas = "".join(
        f'<tr><td style="padding:6px 12px 6px 0">{escape(a.nome)}</td><td style="padding:6px 12px 6px 0;color:#6b7280">'
        f'{escape(a.matricula)} · {escape(turma(a))}</td><td style="padding:6px 0;font-weight:700;color:'
        f'{"#dc2626" if f < 75 else "#d97706"}">{f}%</td></tr>'
        for a, f in alunos)
    msg.add_alternative(f"""\
<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#111827">
  <div style="background:linear-gradient(135deg,#5b8cff,#a26bff,#ff4fd8);color:#fff;padding:20px 24px;border-radius:14px 14px 0 0">
    <div style="font-size:13px;opacity:.85">FrequencyON</div>
    <div style="font-size:20px;font-weight:700">{len(alunos)} aluno(s) com frequência baixa</div>
  </div>
  <div style="border:1px solid #e5e7eb;border-top:0;padding:20px 24px;border-radius:0 0 14px 14px;font-size:14px">
    <p>Olá, {escape(nome)}. Estes alunos estão perto ou abaixo do mínimo de <b>75%</b>:</p>
    <table style="border-collapse:collapse;font-size:14px">{linhas}</table>
    <p style="color:#6b7280;font-size:13px">Cada aluno com e-mail cadastrado também recebeu o aviso.</p>
  </div>
</div>""", subtype="html")
    threading.Thread(target=_enviar, args=(cfg, msg), daemon=True).start()
    return True


def enviar_aviso_totem(nome_totem, minutos):
    """RNF16: avisa a coordenação que um totem liberado parou de mandar imagens durante a aula."""
    cfg = _config()
    if not (smtp_configurado() and cfg["destino"]):
        print(f"[monitor] totem {nome_totem} sem sinal há {minutos} min (e-mail não configurado)")
        return False
    msg = EmailMessage()
    msg["Subject"] = f"FrequencyON: totem \"{nome_totem}\" sem sinal há {minutos} min"
    msg["From"] = f"FrequencyON <{cfg['usuario']}>"
    msg["To"] = cfg["destino"]
    msg.set_content(f"O totem \"{nome_totem}\" está liberado, mas não manda imagens há {minutos} minutos.\n"
                    f"Confira se o tablet está ligado, com internet e com a página do totem aberta.\n")
    threading.Thread(target=_enviar, args=(cfg, msg), daemon=True).start()
    return True

