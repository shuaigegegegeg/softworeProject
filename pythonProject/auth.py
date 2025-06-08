# auth.py  ── 完整可覆盖原文件
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user, UserMixin
)
from models import db, User

# ─────────── LoginManager & Blueprint ───────────
login_manager = LoginManager()                   # 只在此处创建
login_manager.login_view = 'auth.login'          # 未登录跳转
login_manager.login_message_category = 'info'

auth_bp = Blueprint('auth', __name__,             # url → /auth/...
                    template_folder='templates',
                    url_prefix='/auth')

@login_manager.user_loader
def load_user(uid):
    return User.query.get(int(uid))

# ─────────── 默认管理员 ───────────
def _ensure_admin():
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print('✅ 已创建默认管理员 admin / admin123')
    # 系统级管理员（只能内部创建）
    if not User.query.filter_by(username='sysadmin').first():
        sys_admin = User(username='sysadmin', role='system_admin')
        sys_admin.set_password('sysadmin123')
        db.session.add(sys_admin)

    db.session.commit()
    print('✅ 已确保管理员账户: admin/admin123, sysadmin/sysadmin123')

# ─────────── 登录 / 注册 / 找回密码 ───────────
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and u.check_password(request.form['password']):
            login_user(u, remember=False, fresh=True)
            session.permanent = False
            flash('登录成功', 'success')
            return redirect(request.args.get('next') or url_for('index'))
        flash('用户名或密码错误', 'error')
    return render_template('login.html')

@auth_bp.route('/passenger/register', methods=['GET', 'POST'])
def passenger_register():
    if request.method == 'POST':
        uname = request.form['username'].strip()
        pwd   = request.form['password']

        # 1) 检查用户是否已存在
        if User.query.filter_by(username=uname).first():
            flash('该账号已存在', 'error')
            return redirect(url_for('auth.passenger_register'))

        # 2) 创建乘客用户（无需注册码）
        passenger = User(username=uname, role='passenger')
        passenger.set_password(pwd)
        db.session.add(passenger)
        db.session.commit()

        flash('注册成功，请登录', 'success')
        return redirect(url_for('auth.passenger_login'))

    # GET 请求渲染页面
    return render_template('passenger_register.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        uname = request.form['username'].strip()
        pwd   = request.form['password']
        regc  = request.form.get('reg_code','').strip()

        if User.query.filter_by(username=uname).first():
            flash('用户名已存在', 'error')
        else:
            from models import RegistrationCode                  # 防循环导入
            code_row = RegistrationCode.query.filter_by(
                code=regc, is_used=False).first()
            if not code_row:
                flash('注册码无效或已被使用', 'error')
            else:
                user = User(username=uname, role='user', reg_code=regc)
                user.set_password(pwd)
                code_row.mark_used()
                db.session.add_all([user, code_row])
                db.session.commit()
                flash('注册成功，请登录', 'success')
                return redirect(url_for('auth.login'))
    return render_template('register.html')

@auth_bp.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        uname   = request.form['username'].strip()
        new_pwd = request.form['new_password']
        user = User.query.filter_by(username=uname).first()
        if not user:
            flash('用户不存在', 'error')
        else:
            user.set_password(new_pwd)
            db.session.commit()
            flash('密码已更新，请登录', 'success')
            return redirect(url_for('auth.login'))
    return render_template('reset_password.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('auth.login'))

# ─────────── Blueprint 初始化给主程序调用 ───────────
def init_auth(app):
    login_manager.init_app(app)
    app.register_blueprint(auth_bp)
    with app.app_context():
        db.create_all()
        _ensure_admin()
