from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


class Usuario(db.Model, UserMixin):
    __tablename__ = "usuario"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(200), nullable=False)
    transacoes = db.relationship('Transacao', backref='usuario', lazy=True)

    def set_password(self, senha):
        """Define a senha do usuário, com validação mínima de 8 caracteres."""
        if not senha or len(senha) < 8:
            raise ValueError("A senha deve ter pelo menos 8 caracteres.")
        self.senha_hash = generate_password_hash(senha)

    def check_password(self, senha):
        """Verifica se a senha informada confere com o hash armazenado."""
        return check_password_hash(self.senha_hash, senha)


class Transacao(db.Model):
    __tablename__ = "transacao"

    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(150), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    tipo = db.Column(db.String(10), nullable=False)  # 'entrada' ou 'saida'
    categoria = db.Column(db.String(50))
    data = db.Column(db.Date, default=datetime.utcnow)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)