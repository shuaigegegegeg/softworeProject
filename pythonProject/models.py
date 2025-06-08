# models.py  ▶ 统一的数据库和数据表 - 增加位置信息字段
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(16), default='user')  # 'user' | 'passenger' | 'admin' | 'system_admin'
    reg_code = db.Column(db.String(64), nullable=True)  # 注册码

    # 新增位置信息字段
    longitude = db.Column(db.Float, nullable=True)  # 经度
    latitude = db.Column(db.Float, nullable=True)  # 纬度
    home_name = db.Column(db.String(100), nullable=True)  # 家的名字/地址

    def set_password(self, raw_pwd):
        self.password = generate_password_hash(raw_pwd)

    def check_password(self, raw_pwd):
        return check_password_hash(self.password, raw_pwd)

    def is_admin(self):
        return self.role == 'admin'

    def is_passenger(self):
        return self.role == 'passenger'

    def is_system_admin(self):
        return self.role == 'system_admin'

    def set_location(self, longitude, latitude, home_name=None):
        """设置用户位置信息"""
        self.longitude = longitude
        self.latitude = latitude
        if home_name:
            self.home_name = home_name

    def get_location(self):
        """获取用户位置信息"""
        if self.longitude is not None and self.latitude is not None:
            return {
                'longitude': self.longitude,
                'latitude': self.latitude,
                'home_name': self.home_name,
                'coordinates': f"{self.latitude:.6f}, {self.longitude:.6f}"
            }
        return None

    def has_location(self):
        """检查用户是否设置了位置信息"""
        return self.longitude is not None and self.latitude is not None


class RegistrationCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), unique=True, nullable=False)
    is_used = db.Column(db.Boolean, default=False)

    def mark_used(self): self.is_used = True