from flask import Blueprint, render_template, request, redirect, url_for, flash,session
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from models import db, User

auth_bp = Blueprint('auth', __name__, template_folder='templates')  # ← 显式声明模板目录也行，可不写
login_manager = LoginManager()
login_manager.login_view = 'auth.login'           # 未登录重定向
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(uid):      # 提供给 Flask-Login 的回调
    return User.query.get(int(uid))

# ---------- 初次启动时自动建管理员 ----------
def _ensure_admin():
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print('✅ 已创建默认管理员 admin / admin123')



@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and u.check_password(request.form['password']):
            login_user(u, remember=False, fresh=True)
            session.permanent = False  # ★ 双重保险：只活到浏览器关闭
            flash('登录成功', 'info')
            return redirect(request.args.get('next') or url_for('index'))
        flash('用户名或密码错误', 'error')
    return render_template('login.html')      # ← 用外部模板

# ---------- 注册 ----------
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        uname = request.form['username'].strip()
        pwd   = request.form['password']
        if User.query.filter_by(username=uname).first():
            flash('用户名已存在', 'error')
        else:
            user = User(username=uname, role='user')
            user.set_password(pwd)           # 明文或散列取决于你的 models.py
            db.session.add(user)
            db.session.commit()
            flash('注册成功，请登录', 'info')
            return redirect(url_for('auth.login'))
    return render_template('register.html')

# ---------- 找回 / 重设密码 ----------
@auth_bp.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        uname = request.form['username'].strip()
        new_pwd = request.form['new_password']
        user = User.query.filter_by(username=uname).first()
        if not user:
            flash('用户不存在', 'error')
        else:
            user.set_password(new_pwd)
            db.session.commit()
            flash('密码已更新，请使用新密码登录', 'info')
            return redirect(url_for('auth.login'))
    return render_template('reset_password.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/admin')
@login_required
def admin():
    if not current_user.is_admin():
        flash('权限不足', 'error')
        return redirect(url_for('index'))
    return '<h2>Admin Panel 👑</h2><p>这里放用户管理等功能</p>'

# ---------- 提供给 main1.py 的初始化函数 ----------
def init_auth(app):
    login_manager.init_app(app)
    app.register_blueprint(auth_bp)
    with app.app_context():
        db.create_all()
        _ensure_admin()
