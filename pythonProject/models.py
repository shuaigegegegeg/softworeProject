# models.py  ▶ 统一的数据库和数据表
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(16), default='user')   # 'user' | 'passenger' | 'admin' | 'system_admin'
    reg_code = db.Column(db.String(64), nullable=True)    # 注册码

    def set_password(self, raw_pwd):
        self.password = generate_password_hash(raw_pwd)

    def check_password(self, raw_pwd):
        return check_password_hash(self.password, raw_pwd)

    def is_admin(self):      return self.role == 'admin'
    def is_passenger(self):  return self.role == 'passenger'
    def is_system_admin(self): return self.role == 'system_admin'              # ← 新增
class RegistrationCode(db.Model):
    id      = db.Column(db.Integer, primary_key=True)
    code    = db.Column(db.String(64), unique=True, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    def mark_used(self): self.is_used = True
