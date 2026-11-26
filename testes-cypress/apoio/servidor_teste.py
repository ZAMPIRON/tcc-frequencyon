"""Sobe o FrequencyON para a suíte Cypress.

Uso: python servidor_teste.py <porta>

- usa a cópia do banco feita pelo "ponte.py preparar" (variável BANCO_TESTE);
- HTTPS ligado, como em produção (certificado local próprio dos testes, em .tmp/certificado);
- e-mails não saem de verdade: ficam gravados em .tmp/caixa_saida.jsonl para os testes conferirem;
- fotos enviadas nos testes vão para .tmp/uploads, e o totem não troca a foto de exibição do aluno
  (assim nenhum arquivo de static/uploads do projeto é criado ou apagado);
- PROVA_DE_VIDA=0 no ambiente sobe a "rodada 2" (reconhecimento sem exigir piscada);
- a rota /__teste__/ponte/<acao> atende o cy.task('ponte') (só existe neste servidor de teste).
"""
import json
import os
import sys
import threading

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJETO = os.path.abspath(os.environ.get("FREQUENCYON_DIR", os.path.join(RAIZ, "..")))
BANCO = os.path.abspath(os.environ.get("BANCO_TESTE", os.path.join(RAIZ, ".tmp", "frequencyon-teste.db")))
TMP = os.path.dirname(BANCO)


def main():
    porta = int(sys.argv[1])
    # tudo antes de importar o projeto: os módulos leem as variáveis na hora do import
    os.environ.update({
        "DATABASE_URL": "sqlite:///" + BANCO.replace("\\", "/"),
        "HTTPS": "1",
        "SSL_CERT": "", "SSL_KEY": "",
        "FREQUENCYON_DATA": "",
        "TOTEM_FONTE": "tablet",
        "SMTP_USUARIO": "frequencyon.teste@localhost",
        "SMTP_SENHA": "teste",
        "EMAIL_JUSTIFICATIVAS": "coordenacao.teste@localhost",
    })
    sys.path.insert(0, PROJETO)
    from email_service import carregar_env
    carregar_env(os.path.join(PROJETO, ".env"))     # o resto da configuração do projeto (não sobrescreve o que está acima)

    import email_service
    import face_service

    caixa, trava = os.path.join(TMP, "caixa_saida.jsonl"), threading.Lock()

    def enviar_para_caixa(cfg, msg, tentativas=3):
        with trava, open(caixa, "a", encoding="utf-8") as f:
            f.write(json.dumps({"para": msg["To"], "assunto": msg["Subject"], "porta": porta}, ensure_ascii=False) + "\n")

    email_service._enviar = enviar_para_caixa
    face_service.Totem._atualizar_foto = lambda self, aluno, frame, caixa_rosto: None

    from app import create_app
    from certificado import certificado_local

    app = create_app(avisar_senhas=False)
    app.config["UPLOAD_DIR"] = os.path.join(TMP, "uploads")
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
    _rota_da_ponte(app)
    cert, chave = certificado_local(os.path.join(TMP, "certificado"))
    print(f"[teste] FrequencyON em https://127.0.0.1:{porta} (prova de vida: {face_service.PROVA_DE_VIDA})", flush=True)
    app.run(host="127.0.0.1", port=porta, threaded=True, debug=False, ssl_context=(cert, chave))


def _rota_da_ponte(app):
    """cy.task('ponte') chega aqui: as ações do ponte.py rodam dentro do processo do site.
    Esta rota só existe neste servidor de teste (escuta apenas em 127.0.0.1)."""
    import traceback
    from flask import jsonify, request
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ponte

    @app.post("/__teste__/ponte/<acao>")
    def ponte_de_teste(acao):
        try:
            return jsonify(ponte.ACOES[acao](request.get_json(silent=True) or {}))
        except Exception:
            return jsonify(erro=traceback.format_exc()), 500

    app.extensions["csrf"].exempt(ponte_de_teste)


if __name__ == "__main__":
    main()
