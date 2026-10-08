# seed.py
from app import create_app  # Importe a instância do seu app Flask (ajuste o nome se necessário)
from database import db, Admin, Professor, Turma, Aluno, Presenca, ProfessorTurma, Justificativa



def popular_banco():
    app = create_app()
    # O Flask-SQLAlchemy exige que as operações de banco rodem dentro do contexto do app
    with app.app_context():
        # Opcional: Criar as tabelas caso ainda não existam
        db.create_all()

        print("Limpando dados antigos (opcional)...")
        # Se quiser apagar tudo antes de recriar, descomente as linhas abaixo com cuidado:
        Presenca.query.delete()
        Justificativa.query.delete()
        ProfessorTurma.query.delete()
        Aluno.query.delete()
        Turma.query.delete()
        Professor.query.delete()
        Admin.query.delete()

        print("Criando Administrador...")
        admin = Admin(nome="Admin Principal", email="admin@senai.com")
        admin.set_senha("admin123") # Usa o seu UsuarioMixin para gerar o hash
        db.session.add(admin)

        print("Criando Professor...")
        prof = Professor(nome="Carlos Silva", email="carlos@professor.senai.com", departamento="TI")
        prof.set_senha("prof123")
        db.session.add(prof)

        # Precisamos fazer um commit parcial aqui para gerar o ID do professor no banco,
        # pois a Turma precisa do professor_id
        db.session.commit()

        print("Criando Turma...")
        turma = Turma(nome="C13", curso="Análise de Desenvolvimento de Sistemas")
        db.session.add(turma)
        # Vincula o professor à turma com os dias de aula dele (1 = terça, 3 = quinta)
        turma.vinculos.append(ProfessorTurma(professor=prof, dias="1,3"))
        
        # Commit parcial para gerar o ID da turma
        db.session.commit()

        print("Criando Alunos...")
        aluno1 = Aluno(
            nome="Gustavo Lopes Zampiron", 
            email="gustavo@aluno.senai.com", 
            matricula="2025001", 
            numero_chamada=9, 
            turma_id=turma.id
        )
        aluno1.set_senha("123")
        
        aluno2 = Aluno(
            nome="Nicolas Luciani", 
            email="nicolas@aluno.senai.com", 
            matricula="2025002", 
            numero_chamada=25, 
            turma_id=turma.id
        )
        aluno2.set_senha("123")

        aluno3 = Aluno(
            nome="Samuel Gustavo", 
            email="samuel@aluno.senai.com", 
            matricula="2025003", 
            numero_chamada=30, 
            turma_id=turma.id
        )
        aluno3.set_senha("123")

        db.session.add(aluno1)
        db.session.add(aluno2)
        db.session.add(aluno3)

        # Salva tudo no banco definitivamente
        db.session.commit()
        print("Banco de dados populado com sucesso!")

if __name__ == '__main__':
    popular_banco()