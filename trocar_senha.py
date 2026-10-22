"""Troca a senha de um admin, professor ou aluno pelo terminal.

Uso:  python trocar_senha.py [email ou matrícula]   (sem argumento, ele pergunta)
A senha nova é digitada sem aparecer na tela.
"""
import getpass
import sys

from sqlalchemy import or_

from app import SENHAS_FRACAS, create_app
from database import Admin, Aluno, Professor, db


def main():
    if len(sys.argv) > 2:
        print(__doc__)
        sys.exit(1)
    # sem argumento (ex.: botão de rodar do VS Code) pergunta no terminal
    login = (sys.argv[1] if len(sys.argv) == 2 else input("E-mail ou matrícula: ")).strip()
    app = create_app(avisar_senhas=False)   # sem o aviso de senhas fracas misturado com a pergunta
    with app.app_context():
        conta = (Admin.query.filter_by(email=login).first()
                 or Professor.query.filter_by(email=login).first()
                 or Aluno.query.filter(or_(Aluno.email == login, Aluno.matricula == login)).first())
        if not conta:
            print(f"Nenhuma conta com o e-mail ou matrícula '{login}'.")
            sys.exit(1)
        print(f"Trocando a senha de {conta.nome} ({type(conta).__name__.lower()}).")
        senha = getpass.getpass("Senha nova (mínimo 8 caracteres): ")
        if len(senha) < 8 or senha in SENHAS_FRACAS:
            print("Senha curta ou fraca demais. Nada foi alterado.")
            sys.exit(1)
        if getpass.getpass("Repita a senha nova: ") != senha:
            print("As senhas não conferem. Nada foi alterado.")
            sys.exit(1)
        conta.set_senha(senha)
        db.session.commit()
        print("Senha trocada.")


if __name__ == "__main__":
    main()
