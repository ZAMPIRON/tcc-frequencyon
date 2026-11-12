# aqui ficam todas as rotas do site, separadas por quem usa:
#   comum.py      -> coisas que varios arquivos usam (login, fotos, totem)
#   login.py      -> pagina inicial, telas de login e logout
#   totem.py      -> camera da entrada e cadastro de rosto
#   admin.py      -> painel da coordenacao (alunos, professores, turmas, justificativas)
#   relatorios.py -> relatorios da coordenacao e a planilha do excel
#   professor.py  -> chamada do professor e calendario
#   aluno.py      -> pagina do aluno, csv e justificativa de falta
#   auditoria.py  -> trilha de auditoria do painel e a tela que mostra o historico
#   api.py        -> api rest de leitura para outros sistemas e a rota de saude (monitoramento)

from . import login
from .admin import admin
from .aluno import area_aluno
from .professor import professor
from .totem import reconhecimento
from . import relatorios  # noqa: F401  so precisa importar pra rota entrar no blueprint do admin
from . import auditoria  # noqa: F401  idem
from .api import api


def registrar_rotas(app):
    # liga todos os blueprints no app
    app.register_blueprint(admin)
    app.register_blueprint(professor)
    app.register_blueprint(area_aluno)
    app.register_blueprint(reconhecimento)
    app.register_blueprint(api)
    login.registrar(app)
