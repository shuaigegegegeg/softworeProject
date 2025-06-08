from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False)
    password  = db.Column(db.String(128), nullable=False)
    role     = db.Column(db.String(16), default='user')  # 'user' | 'admin'

    # -------- 修正密码处理方法 --------
    def set_password(self, raw_pwd):
        """设置密码（使用哈希）"""
        self.password = generate_password_hash(raw_pwd)

    def check_password(self, raw_pwd):
        """验证密码（使用哈希验证）"""
        return check_password_hash(self.password, raw_pwd)

    def is_admin(self):
        """检查是否为管理员"""
        return self.role == 'admin'