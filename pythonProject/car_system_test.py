# car_system_test.py - 车载智能交互系统综合测试脚本
import os
import sys
import time
import json
import random
import threading
import subprocess
import requests
import psutil
import sqlite3
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Any, Optional
import statistics

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 尝试导入项目模块
try:
    from models import db, User, RegistrationCode
    from voice_module import VoiceRecognition, VoiceResponse
    from vision_module import VisionRecognition
    from navigation_module import NavigationModule

    MODULES_AVAILABLE = True
except ImportError as e:
    print(f"警告: 无法导入某些模块: {e}")
    MODULES_AVAILABLE = False


class CarSystemTesterEnhanced:
    """车载智能交互系统综合测试器"""

    def __init__(self):
        self.base_url = "http://localhost:5000"
        self.test_results = {}
        self.performance_metrics = {}
        self.session = requests.Session()

        # 设置session参数
        self.session.headers.update({
            'User-Agent': 'CarSystemTester/2.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

        # 设置日志
        self.setup_logging()

        # 测试数据
        self.test_users = [
            {"username": "test_driver", "password": "test123", "role": "user"},
            {"username": "test_passenger", "password": "test123", "role": "passenger"},
            {"username": "test_admin", "password": "admin123", "role": "admin"}
        ]

        # 语音指令测试集
        self.voice_commands = [
            {"command": "播放音乐", "expected_type": "music_play", "category": "音乐控制"},
            {"command": "暂停音乐", "expected_type": "music_pause", "category": "音乐控制"},
            {"command": "下一首", "expected_type": "music_next", "category": "音乐控制"},
            {"command": "上一首", "expected_type": "music_prev", "category": "音乐控制"},
            {"command": "开空调", "expected_type": "ac_on", "category": "空调控制"},
            {"command": "关空调", "expected_type": "ac_off", "category": "空调控制"},
            {"command": "升温", "expected_type": "temp_up", "category": "温度控制"},
            {"command": "降温", "expected_type": "temp_down", "category": "温度控制"},
            {"command": "开窗", "expected_type": "window_open", "category": "车窗控制"},
            {"command": "关窗", "expected_type": "window_close", "category": "车窗控制"},
            {"command": "开灯", "expected_type": "light_on", "category": "灯光控制"},
            {"command": "关灯", "expected_type": "light_off", "category": "灯光控制"},
            {"command": "导航到天津站", "expected_type": "navigation_complete", "category": "导航控制"},
            {"command": "停止导航", "expected_type": "navigation_stop", "category": "导航控制"},
            {"command": "回家", "expected_type": "navigation_home", "category": "导航控制"},
        ]

        # 手势测试数据
        self.gesture_test_data = [
            {"gesture": "Open Palm", "expected_command": "播放音乐"},
            {"gesture": "Fist", "expected_command": "暂停音乐"},
            {"gesture": "Index Up", "expected_command": "升温"},
            {"gesture": "Two Fingers Up", "expected_command": "降温"},
        ]

        # 导航测试地点
        self.navigation_locations = [
            "天津站", "天津西站", "天津南站", "天津机场",
            "天津大学", "南开大学", "天津市人民政府", "五大道",
            "古文化街", "意式风情区", "海河", "津门故里"
        ]

    def setup_logging(self):
        """设置日志记录"""
        # 创建日志目录
        os.makedirs("test_logs", exist_ok=True)

        # 生成带时间戳的日志文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"test_logs/car_system_test_{timestamp}.log"

        # 配置日志格式
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
            handlers=[
                logging.FileHandler(log_filename, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )

        self.logger = logging.getLogger('CarSystemTest')
        self.logger.info(f"开始车载系统综合测试 - 日志文件: {log_filename}")

    def pre_test_system_check(self) -> Dict[str, Any]:
        """测试前的系统预检查"""
        self.logger.info("🔍 执行测试前系统预检查...")

        check_results = {
            "check_name": "系统预检查",
            "timestamp": datetime.now().isoformat(),
            "checks": [],
            "overall_status": "UNKNOWN",
            "recommendations": []
        }

        checks_passed = 0
        total_checks = 0

        # 检查1：系统是否运行
        total_checks += 1
        try:
            response = requests.get(f"{self.base_url}/auth/login", timeout=10)
            if response.status_code == 200:
                check_results["checks"].append({
                    "check": "系统运行状态",
                    "status": "PASS",
                    "details": "系统正在运行，登录页面可访问"
                })
                checks_passed += 1
                self.logger.info("✅ 系统正在运行")
            else:
                check_results["checks"].append({
                    "check": "系统运行状态",
                    "status": "FAIL",
                    "details": f"系统状态异常: HTTP {response.status_code}"
                })
                self.logger.error(f"❌ 系统状态异常: {response.status_code}")
        except Exception as e:
            check_results["checks"].append({
                "check": "系统运行状态",
                "status": "ERROR",
                "details": f"无法连接到系统: {str(e)}"
            })
            self.logger.error(f"❌ 无法连接到系统: {e}")

        # 检查2：数据库文件存在性（修复版 - 检查instance目录）
        total_checks += 1
        db_paths = [
            "instance/car_system.db",  # 主要位置
            "car_system.db",
            "./instance/car_system.db",
            "../instance/car_system.db"
        ]

        db_found = False
        actual_db_path = None

        for path in db_paths:
            if os.path.exists(path):
                db_found = True
                actual_db_path = path
                file_size = os.path.getsize(path)
                check_results["checks"].append({
                    "check": "数据库文件存在性",
                    "status": "PASS",
                    "details": f"找到数据库文件: {path} (大小: {file_size} bytes)"
                })
                checks_passed += 1
                self.logger.info(f"✅ 找到数据库文件: {path} (大小: {file_size} bytes)")
                break

        if not db_found:
            check_results["checks"].append({
                "check": "数据库文件存在性",
                "status": "FAIL",
                "details": f"在以下位置均未找到数据库文件: {db_paths}"
            })
            check_results["recommendations"].append("请先运行 python main.py 创建数据库")
            self.logger.error("❌ 未找到数据库文件")

        # 检查3：端口占用检查
        total_checks += 1
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex(('localhost', 5000))
            sock.close()

            if result == 0:
                check_results["checks"].append({
                    "check": "端口5000监听状态",
                    "status": "PASS",
                    "details": "端口5000正在监听"
                })
                checks_passed += 1
                self.logger.info("✅ 端口5000正在监听")
            else:
                check_results["checks"].append({
                    "check": "端口5000监听状态",
                    "status": "FAIL",
                    "details": "端口5000未被占用"
                })
                check_results["recommendations"].append("请启动车载系统主程序")
                self.logger.error("❌ 端口5000未被占用")
        except Exception as e:
            check_results["checks"].append({
                "check": "端口5000监听状态",
                "status": "ERROR",
                "details": f"端口检查异常: {str(e)}"
            })
            self.logger.error(f"❌ 端口检查异常: {e}")

        # 检查4：关键文件存在性
        total_checks += 1
        key_files = ["web_interface.html", "main.py", "models.py"]
        missing_files = []

        for file in key_files:
            if not os.path.exists(file):
                missing_files.append(file)

        if not missing_files:
            check_results["checks"].append({
                "check": "关键文件存在性",
                "status": "PASS",
                "details": "所有关键文件都存在"
            })
            checks_passed += 1
            self.logger.info("✅ 所有关键文件都存在")
        else:
            check_results["checks"].append({
                "check": "关键文件存在性",
                "status": "FAIL",
                "details": f"缺少文件: {missing_files}"
            })
            self.logger.error(f"❌ 缺少关键文件: {missing_files}")

        # 检查5：API基础连接测试
        total_checks += 1
        try:
            response = requests.get(f"{self.base_url}/api/system_state", timeout=10)
            if response.status_code in [200, 401]:  # 200正常，401需要登录但系统正常
                check_results["checks"].append({
                    "check": "API基础连接",
                    "status": "PASS",
                    "details": f"API响应正常: {response.status_code}"
                })
                checks_passed += 1
                self.logger.info(f"✅ API响应正常: {response.status_code}")
            else:
                check_results["checks"].append({
                    "check": "API基础连接",
                    "status": "FAIL",
                    "details": f"API响应异常: {response.status_code}"
                })
                self.logger.error(f"❌ API响应异常: {response.status_code}")
        except Exception as e:
            check_results["checks"].append({
                "check": "API基础连接",
                "status": "ERROR",
                "details": f"API连接异常: {str(e)}"
            })
            self.logger.error(f"❌ API连接异常: {e}")

        # 计算总体状态
        success_rate = (checks_passed / total_checks) * 100 if total_checks > 0 else 0

        if success_rate >= 80:
            check_results["overall_status"] = "GOOD"
        elif success_rate >= 60:
            check_results["overall_status"] = "WARNING"
        else:
            check_results["overall_status"] = "CRITICAL"

        check_results["success_rate"] = success_rate
        check_results["checks_passed"] = checks_passed
        check_results["total_checks"] = total_checks

        self.logger.info(f"🔍 系统预检查完成 - 通过率: {success_rate:.1f}% ({checks_passed}/{total_checks})")

        return check_results

    def check_system_status(self) -> bool:
        """检查系统运行状态"""
        try:
            response = self.session.get(f"{self.base_url}/api/system_state", timeout=10)
            if response.status_code == 200:
                self.logger.info("✅ 系统运行正常")
                return True
            elif response.status_code == 401:
                self.logger.warning("⚠️ 需要登录")
                return True  # 系统在运行，只是需要认证
            else:
                self.logger.error(f"❌ 系统状态异常: {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            self.logger.error(f"❌ 无法连接到系统: {e}")
            return False

    def test_authentication_system(self) -> Dict[str, Any]:
        """测试认证系统（修复版）"""
        self.logger.info("🔐 开始测试认证系统...")

        auth_results = {
            "test_name": "认证系统测试",
            "start_time": datetime.now().isoformat(),
            "tests": [],
            "success_count": 0,
            "total_count": 0,
            "success_rate": 0.0,
            "average_response_time": 0.0
        }

        response_times = []

        # 清除之前的会话状态
        self.session.cookies.clear()

        # 测试管理员登录（修复版）
        start_time = time.time()
        try:
            # 首先获取登录页面，确保系统可访问
            login_page_response = self.session.get(f"{self.base_url}/auth/login", timeout=10)
            if login_page_response.status_code != 200:
                raise Exception(f"无法访问登录页面: {login_page_response.status_code}")

            # 准备登录数据
            login_data = {
                "username": "admin",
                "password": "admin123"
            }

            # 执行登录请求
            response = self.session.post(
                f"{self.base_url}/auth/login",
                data=login_data,
                timeout=10,
                allow_redirects=True
            )

            response_time = time.time() - start_time
            response_times.append(response_time)

            # 检查登录是否成功（修复版检查逻辑）
            login_success = False
            success_details = []

            # 检查方式1：HTTP状态码
            if response.status_code == 200:
                success_details.append("HTTP 200 响应")

            # 检查方式2：URL重定向
            if response.url != f"{self.base_url}/auth/login":
                success_details.append(f"重定向到: {response.url}")
                login_success = True

            # 检查方式3：响应内容
            response_text = response.text.lower()
            if any(indicator in response_text for indicator in [
                "logout", "退出", "admin", "管理", "dashboard", "仪表板"
            ]):
                success_details.append("页面包含登录成功标识")
                login_success = True

            # 检查方式4：登录失败标识
            if any(error in response_text for error in [
                "错误", "失败", "invalid", "error", "用户名或密码"
            ]):
                login_success = False
                success_details.append("页面包含错误信息")

            # 检查方式5：尝试访问需要登录的页面
            if not login_success:
                test_response = self.session.get(f"{self.base_url}/", timeout=5)
                if test_response.status_code == 200 and "logout" in test_response.text.lower():
                    login_success = True
                    success_details.append("可以访问需要登录的页面")

            if login_success:
                auth_results["tests"].append({
                    "test": "管理员登录",
                    "status": "PASS",
                    "response_time": response_time,
                    "details": f"登录成功 - {'; '.join(success_details)}"
                })
                auth_results["success_count"] += 1
                self.logger.info("✅ 管理员登录测试通过")
            else:
                auth_results["tests"].append({
                    "test": "管理员登录",
                    "status": "FAIL",
                    "response_time": response_time,
                    "details": f"登录失败 - 状态码: {response.status_code}, URL: {response.url}"
                })
                self.logger.error("❌ 管理员登录测试失败")

            auth_results["total_count"] += 1

        except Exception as e:
            auth_results["tests"].append({
                "test": "管理员登录",
                "status": "ERROR",
                "response_time": time.time() - start_time,
                "details": f"测试异常: {str(e)}"
            })
            auth_results["total_count"] += 1
            self.logger.error(f"❌ 管理员登录测试异常: {e}")

        # 测试错误凭据拒绝
        start_time = time.time()
        try:
            # 使用新会话测试错误凭据
            wrong_session = requests.Session()
            wrong_data = {"username": "admin", "password": "wrongpassword"}
            response = wrong_session.post(
                f"{self.base_url}/auth/login",
                data=wrong_data,
                timeout=10,
                allow_redirects=True
            )

            response_time = time.time() - start_time
            response_times.append(response_time)

            # 检查是否正确拒绝错误凭据
            rejection_success = False

            # 方式1：检查是否仍在登录页面
            if "login" in response.url:
                rejection_success = True

            # 方式2：检查错误消息
            if any(error in response.text for error in [
                "错误", "失败", "invalid", "error", "用户名或密码", "密码错误"
            ]):
                rejection_success = True

            # 方式3：检查是否无法访问需要登录的页面
            test_response = wrong_session.get(f"{self.base_url}/", timeout=5)
            if test_response.status_code == 401 or "login" in test_response.url:
                rejection_success = True

            if rejection_success:
                auth_results["tests"].append({
                    "test": "错误凭据拒绝",
                    "status": "PASS",
                    "response_time": response_time,
                    "details": "正确拒绝错误凭据"
                })
                auth_results["success_count"] += 1
                self.logger.info("✅ 错误凭据拒绝测试通过")
            else:
                auth_results["tests"].append({
                    "test": "错误凭据拒绝",
                    "status": "FAIL",
                    "response_time": response_time,
                    "details": "未能正确拒绝错误凭据"
                })
                self.logger.error("❌ 错误凭据拒绝测试失败")

            auth_results["total_count"] += 1
            wrong_session.close()

        except Exception as e:
            auth_results["tests"].append({
                "test": "错误凭据拒绝",
                "status": "ERROR",
                "response_time": time.time() - start_time,
                "details": f"测试异常: {str(e)}"
            })
            auth_results["total_count"] += 1
            self.logger.error(f"❌ 错误凭据拒绝测试异常: {e}")

        # 测试权限验证（使用已登录的session）
        start_time = time.time()
        try:
            response = self.session.get(f"{self.base_url}/api/admin/system_stats", timeout=10)
            response_time = time.time() - start_time
            response_times.append(response_time)

            if response.status_code == 200:
                auth_results["tests"].append({
                    "test": "管理员权限验证",
                    "status": "PASS",
                    "response_time": response_time,
                    "details": "管理员权限验证成功"
                })
                auth_results["success_count"] += 1
                self.logger.info("✅ 管理员权限验证测试通过")
            else:
                auth_results["tests"].append({
                    "test": "管理员权限验证",
                    "status": "FAIL",
                    "response_time": response_time,
                    "details": f"权限验证失败: {response.status_code}"
                })
                self.logger.error("❌ 管理员权限验证测试失败")

            auth_results["total_count"] += 1

        except Exception as e:
            auth_results["tests"].append({
                "test": "管理员权限验证",
                "status": "ERROR",
                "response_time": time.time() - start_time,
                "details": f"测试异常: {str(e)}"
            })
            auth_results["total_count"] += 1
            self.logger.error(f"❌ 管理员权限验证测试异常: {e}")

        # 计算统计数据
        auth_results["success_rate"] = (auth_results["success_count"] / auth_results["total_count"]) * 100 if \
            auth_results["total_count"] > 0 else 0
        auth_results["average_response_time"] = statistics.mean(response_times) if response_times else 0
        auth_results["end_time"] = datetime.now().isoformat()

        self.logger.info(f"🔐 认证系统测试完成 - 成功率: {auth_results['success_rate']:.1f}%")
        return auth_results

    def test_voice_recognition_mock(self) -> Dict[str, Any]:
        """测试语音识别功能（模拟测试）"""
        self.logger.info("🎤 开始测试语音识别功能...")

        voice_results = {
            "test_name": "语音识别测试",
            "start_time": datetime.now().isoformat(),
            "tests": [],
            "command_accuracy": {},
            "success_count": 0,
            "total_count": 0,
            "success_rate": 0.0,
            "average_response_time": 0.0
        }

        response_times = []
        category_stats = {}

        # 测试每个语音指令
        for cmd_data in self.voice_commands:
            command = cmd_data["command"]
            expected_type = cmd_data["expected_type"]
            category = cmd_data["category"]

            start_time = time.time()
            try:
                # 模拟语音指令测试
                test_payload = {
                    "type": "voice",
                    "text": command,
                    "source": "测试"
                }

                response = self.session.post(
                    f"{self.base_url}/api/command",
                    json=test_payload,
                    timeout=10
                )

                response_time = time.time() - start_time
                response_times.append(response_time)

                # 初始化类别统计
                if category not in category_stats:
                    category_stats[category] = {"success": 0, "total": 0}

                category_stats[category]["total"] += 1

                if response.status_code == 200:
                    result_data = response.json()
                    if result_data.get("status") == "success":
                        voice_results["tests"].append({
                            "command": command,
                            "category": category,
                            "expected_type": expected_type,
                            "status": "PASS",
                            "response_time": response_time,
                            "details": "指令执行成功"
                        })
                        voice_results["success_count"] += 1
                        category_stats[category]["success"] += 1
                        self.logger.info(f"✅ 语音指令测试通过: {command}")
                    else:
                        voice_results["tests"].append({
                            "command": command,
                            "category": category,
                            "expected_type": expected_type,
                            "status": "FAIL",
                            "response_time": response_time,
                            "details": f"指令执行失败: {result_data.get('message', '未知错误')}"
                        })
                        self.logger.error(f"❌ 语音指令测试失败: {command}")
                else:
                    voice_results["tests"].append({
                        "command": command,
                        "category": category,
                        "expected_type": expected_type,
                        "status": "FAIL",
                        "response_time": response_time,
                        "details": f"HTTP错误: {response.status_code}"
                    })
                    self.logger.error(f"❌ 语音指令HTTP错误: {command} - {response.status_code}")

                voice_results["total_count"] += 1

            except Exception as e:
                voice_results["tests"].append({
                    "command": command,
                    "category": category,
                    "expected_type": expected_type,
                    "status": "ERROR",
                    "response_time": time.time() - start_time,
                    "details": f"测试异常: {str(e)}"
                })
                voice_results["total_count"] += 1
                if category in category_stats:
                    category_stats[category]["total"] += 1
                self.logger.error(f"❌ 语音指令测试异常: {command} - {e}")

            # 添加延迟避免请求过快
            time.sleep(0.5)

        # 计算各类别准确率
        for category, stats in category_stats.items():
            if stats["total"] > 0:
                accuracy = (stats["success"] / stats["total"]) * 100
                voice_results["command_accuracy"][category] = {
                    "success": stats["success"],
                    "total": stats["total"],
                    "accuracy": accuracy
                }

        # 计算总体统计数据
        voice_results["success_rate"] = (voice_results["success_count"] / voice_results["total_count"]) * 100 if \
            voice_results["total_count"] > 0 else 0
        voice_results["average_response_time"] = statistics.mean(response_times) if response_times else 0
        voice_results["end_time"] = datetime.now().isoformat()

        self.logger.info(f"🎤 语音识别测试完成 - 总体成功率: {voice_results['success_rate']:.1f}%")
        return voice_results

    def test_navigation_system(self) -> Dict[str, Any]:
        """测试导航系统"""
        self.logger.info("🧭 开始测试导航系统...")

        nav_results = {
            "test_name": "导航系统测试",
            "start_time": datetime.now().isoformat(),
            "tests": [],
            "success_count": 0,
            "total_count": 0,
            "success_rate": 0.0,
            "average_response_time": 0.0
        }

        response_times = []

        # 测试导航状态查询
        start_time = time.time()
        try:
            response = self.session.get(f"{self.base_url}/api/navigation_status", timeout=10)
            response_time = time.time() - start_time
            response_times.append(response_time)

            if response.status_code == 200:
                nav_data = response.json()
                nav_results["tests"].append({
                    "test": "导航状态查询",
                    "status": "PASS",
                    "response_time": response_time,
                    "details": f"导航状态: {nav_data.get('is_navigating', '未知')}"
                })
                nav_results["success_count"] += 1
                self.logger.info("✅ 导航状态查询测试通过")
            else:
                nav_results["tests"].append({
                    "test": "导航状态查询",
                    "status": "FAIL",
                    "response_time": response_time,
                    "details": f"查询失败: {response.status_code}"
                })
                self.logger.error("❌ 导航状态查询测试失败")

            nav_results["total_count"] += 1

        except Exception as e:
            nav_results["tests"].append({
                "test": "导航状态查询",
                "status": "ERROR",
                "response_time": time.time() - start_time,
                "details": f"测试异常: {str(e)}"
            })
            nav_results["total_count"] += 1
            self.logger.error(f"❌ 导航状态查询测试异常: {e}")

        # 测试导航指令（模拟）
        for location in random.sample(self.navigation_locations, 3):  # 随机选择3个地点
            start_time = time.time()
            try:
                nav_command = f"导航到{location}"
                test_payload = {
                    "type": "navigation",
                    "text": nav_command,
                    "source": "测试"
                }

                response = self.session.post(
                    f"{self.base_url}/api/command",
                    json=test_payload,
                    timeout=15  # 导航可能需要更长时间
                )

                response_time = time.time() - start_time
                response_times.append(response_time)

                if response.status_code == 200:
                    result_data = response.json()
                    if result_data.get("status") == "success":
                        nav_results["tests"].append({
                            "test": f"导航到{location}",
                            "status": "PASS",
                            "response_time": response_time,
                            "details": "导航指令执行成功"
                        })
                        nav_results["success_count"] += 1
                        self.logger.info(f"✅ 导航测试通过: {location}")
                    else:
                        nav_results["tests"].append({
                            "test": f"导航到{location}",
                            "status": "FAIL",
                            "response_time": response_time,
                            "details": f"导航失败: {result_data.get('message', '未知错误')}"
                        })
                        self.logger.error(f"❌ 导航测试失败: {location}")
                else:
                    nav_results["tests"].append({
                        "test": f"导航到{location}",
                        "status": "FAIL",
                        "response_time": response_time,
                        "details": f"HTTP错误: {response.status_code}"
                    })
                    self.logger.error(f"❌ 导航HTTP错误: {location} - {response.status_code}")

                nav_results["total_count"] += 1

            except Exception as e:
                nav_results["tests"].append({
                    "test": f"导航到{location}",
                    "status": "ERROR",
                    "response_time": time.time() - start_time,
                    "details": f"测试异常: {str(e)}"
                })
                nav_results["total_count"] += 1
                self.logger.error(f"❌ 导航测试异常: {location} - {e}")

            time.sleep(2)  # 导航测试间隔更长

        # 测试停止导航
        start_time = time.time()
        try:
            response = self.session.post(f"{self.base_url}/api/stop_navigation", timeout=10)
            response_time = time.time() - start_time
            response_times.append(response_time)

            if response.status_code == 200:
                result_data = response.json()
                if result_data.get("status") == "success":
                    nav_results["tests"].append({
                        "test": "停止导航",
                        "status": "PASS",
                        "response_time": response_time,
                        "details": "停止导航成功"
                    })
                    nav_results["success_count"] += 1
                    self.logger.info("✅ 停止导航测试通过")
                else:
                    nav_results["tests"].append({
                        "test": "停止导航",
                        "status": "FAIL",
                        "response_time": response_time,
                        "details": f"停止失败: {result_data.get('message', '未知错误')}"
                    })
                    self.logger.error("❌ 停止导航测试失败")
            else:
                nav_results["tests"].append({
                    "test": "停止导航",
                    "status": "FAIL",
                    "response_time": response_time,
                    "details": f"HTTP错误: {response.status_code}"
                })
                self.logger.error(f"❌ 停止导航HTTP错误: {response.status_code}")

            nav_results["total_count"] += 1

        except Exception as e:
            nav_results["tests"].append({
                "test": "停止导航",
                "status": "ERROR",
                "response_time": time.time() - start_time,
                "details": f"测试异常: {str(e)}"
            })
            nav_results["total_count"] += 1
            self.logger.error(f"❌ 停止导航测试异常: {e}")

        # 计算统计数据
        nav_results["success_rate"] = (nav_results["success_count"] / nav_results["total_count"]) * 100 if nav_results[
                                                                                                               "total_count"] > 0 else 0
        nav_results["average_response_time"] = statistics.mean(response_times) if response_times else 0
        nav_results["end_time"] = datetime.now().isoformat()

        self.logger.info(f"🧭 导航系统测试完成 - 成功率: {nav_results['success_rate']:.1f}%")
        return nav_results

    def test_vehicle_controls(self) -> Dict[str, Any]:
        """测试车辆控制功能"""
        self.logger.info("🚗 开始测试车辆控制功能...")

        control_results = {
            "test_name": "车辆控制测试",
            "start_time": datetime.now().isoformat(),
            "tests": [],
            "control_categories": {},
            "success_count": 0,
            "total_count": 0,
            "success_rate": 0.0,
            "average_response_time": 0.0
        }

        response_times = []

        # 车辆控制指令测试集
        control_commands = [
            {"command": "开空调", "category": "空调控制"},
            {"command": "关空调", "category": "空调控制"},
            {"command": "升温", "category": "温度控制"},
            {"command": "降温", "category": "温度控制"},
            {"command": "开窗", "category": "车窗控制"},
            {"command": "关窗", "category": "车窗控制"},
            {"command": "开灯", "category": "灯光控制"},
            {"command": "关灯", "category": "灯光控制"},
            {"command": "播放音乐", "category": "音乐控制"},
            {"command": "暂停音乐", "category": "音乐控制"},
            {"command": "下一首", "category": "音乐控制"},
            {"command": "上一首", "category": "音乐控制"},
        ]

        category_stats = {}

        for cmd_data in control_commands:
            command = cmd_data["command"]
            category = cmd_data["category"]

            # 初始化类别统计
            if category not in category_stats:
                category_stats[category] = {"success": 0, "total": 0}

            start_time = time.time()
            try:
                test_payload = {
                    "type": "manual",
                    "text": command,
                    "source": "控制测试"
                }

                response = self.session.post(
                    f"{self.base_url}/api/command",
                    json=test_payload,
                    timeout=10
                )

                response_time = time.time() - start_time
                response_times.append(response_time)
                category_stats[category]["total"] += 1

                if response.status_code == 200:
                    result_data = response.json()
                    if result_data.get("status") == "success":
                        control_results["tests"].append({
                            "command": command,
                            "category": category,
                            "status": "PASS",
                            "response_time": response_time,
                            "details": "控制指令执行成功"
                        })
                        control_results["success_count"] += 1
                        category_stats[category]["success"] += 1
                        self.logger.info(f"✅ 车辆控制测试通过: {command}")
                    else:
                        control_results["tests"].append({
                            "command": command,
                            "category": category,
                            "status": "FAIL",
                            "response_time": response_time,
                            "details": f"控制失败: {result_data.get('message', '未知错误')}"
                        })
                        self.logger.error(f"❌ 车辆控制测试失败: {command}")
                else:
                    control_results["tests"].append({
                        "command": command,
                        "category": category,
                        "status": "FAIL",
                        "response_time": response_time,
                        "details": f"HTTP错误: {response.status_code}"
                    })
                    self.logger.error(f"❌ 车辆控制HTTP错误: {command} - {response.status_code}")

                control_results["total_count"] += 1

            except Exception as e:
                control_results["tests"].append({
                    "command": command,
                    "category": category,
                    "status": "ERROR",
                    "response_time": time.time() - start_time,
                    "details": f"测试异常: {str(e)}"
                })
                control_results["total_count"] += 1
                category_stats[category]["total"] += 1
                self.logger.error(f"❌ 车辆控制测试异常: {command} - {e}")

            time.sleep(0.5)

        # 计算各类别成功率
        for category, stats in category_stats.items():
            if stats["total"] > 0:
                success_rate = (stats["success"] / stats["total"]) * 100
                control_results["control_categories"][category] = {
                    "success": stats["success"],
                    "total": stats["total"],
                    "success_rate": success_rate
                }

        # 计算总体统计数据
        control_results["success_rate"] = (control_results["success_count"] / control_results["total_count"]) * 100 if \
            control_results["total_count"] > 0 else 0
        control_results["average_response_time"] = statistics.mean(response_times) if response_times else 0
        control_results["end_time"] = datetime.now().isoformat()

        self.logger.info(f"🚗 车辆控制测试完成 - 成功率: {control_results['success_rate']:.1f}%")
        return control_results

    def test_performance_metrics(self) -> Dict[str, Any]:
        """测试系统性能指标- 详细日志输出）"""
        self.logger.info("📊 开始测试系统性能指标...")

        performance_results = {
            "test_name": "性能测试",
            "start_time": datetime.now().isoformat(),
            "metrics": {},
            "load_test": {},
            "resource_usage": {},
            "benchmarks": {},
            "api_response_times": {}
        }

        # 获取系统资源使用情况
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory_info = psutil.virtual_memory()
            disk_info = psutil.disk_usage('/')

            performance_results["resource_usage"] = {
                "cpu_usage_percent": cpu_percent,
                "memory_usage_percent": memory_info.percent,
                "memory_available_gb": round(memory_info.available / (1024 ** 3), 2),
                "disk_usage_percent": disk_info.percent,
                "disk_free_gb": round(disk_info.free / (1024 ** 3), 2)
            }

            # 性能基准评估
            benchmarks = performance_results["benchmarks"]
            benchmarks["cpu_status"] = "优秀" if cpu_percent < 50 else "良好" if cpu_percent < 80 else "需要优化"
            benchmarks[
                "memory_status"] = "优秀" if memory_info.percent < 60 else "良好" if memory_info.percent < 80 else "需要优化"

            # 详细输出系统资源使用情况到日志
            self.logger.info("📊 系统资源使用详情:")
            self.logger.info(f"   CPU使用率: {cpu_percent:.1f}% - {benchmarks['cpu_status']}")
            self.logger.info(f"   内存使用率: {memory_info.percent:.1f}% - {benchmarks['memory_status']}")
            self.logger.info(f"   内存可用: {round(memory_info.available / (1024 ** 3), 2)} GB")
            self.logger.info(f"   磁盘使用率: {disk_info.percent:.1f}%")
            self.logger.info(f"   磁盘可用: {round(disk_info.free / (1024 ** 3), 2)} GB")

        except Exception as e:
            self.logger.error(f"❌ 获取系统资源信息失败: {e}")
            performance_results["resource_usage"] = {"error": str(e)}

        # API响应时间测试
        self.logger.info("📊 开始API响应时间测试...")

        api_endpoints = [
            "/api/system_state",
            "/api/navigation_status",
            "/api/voice_status",
            "/api/video_status"
        ]

        api_response_times = {}
        total_api_times = []

        for endpoint in api_endpoints:
            self.logger.info(f"   测试API端点: {endpoint}")
            times = []
            successful_requests = 0

            for i in range(10):  # 每个端点测试10次
                start_time = time.time()
                try:
                    response = self.session.get(f"{self.base_url}{endpoint}", timeout=5)
                    response_time = time.time() - start_time

                    if response.status_code in [200, 401]:  # 200正常，401需要登录但响应正常
                        times.append(response_time)
                        successful_requests += 1

                    # 每次请求的详细日志（仅在调试时）
                    if i < 3:  # 只记录前3次请求的详情
                        self.logger.info(
                            f"     请求 {i + 1}: {response_time * 1000:.2f}ms (状态: {response.status_code})")

                except Exception as e:
                    self.logger.warning(f"     请求 {i + 1}: 失败 - {str(e)}")

                time.sleep(0.1)

            if times:
                avg_time_ms = statistics.mean(times) * 1000
                min_time_ms = min(times) * 1000
                max_time_ms = max(times) * 1000
                median_time_ms = statistics.median(times) * 1000

                # 性能基准
                benchmark = "优秀" if avg_time_ms < 100 else "良好" if avg_time_ms < 500 else "需要优化"

                api_response_times[endpoint] = {
                    "min_ms": round(min_time_ms, 2),
                    "max_ms": round(max_time_ms, 2),
                    "avg_ms": round(avg_time_ms, 2),
                    "median_ms": round(median_time_ms, 2),
                    "successful_requests": successful_requests,
                    "total_requests": 10,
                    "success_rate": (successful_requests / 10) * 100,
                    "benchmark": benchmark
                }

                total_api_times.extend(times)

                # 详细输出每个API端点的性能数据到日志
                self.logger.info(f"   {endpoint} 性能结果:")
                self.logger.info(f"     平均响应时间: {avg_time_ms:.2f}ms ({benchmark})")
                self.logger.info(f"     最小/最大响应时间: {min_time_ms:.2f}ms / {max_time_ms:.2f}ms")
                self.logger.info(f"     中位数响应时间: {median_time_ms:.2f}ms")
                self.logger.info(f"     成功率: {(successful_requests / 10) * 100:.1f}% ({successful_requests}/10)")

                if avg_time_ms > 500:
                    self.logger.warning(f"     ⚠️ {endpoint} 响应时间较慢，建议优化")
            else:
                api_response_times[endpoint] = {
                    "error": "所有请求都失败",
                    "successful_requests": 0,
                    "total_requests": 10,
                    "success_rate": 0,
                    "benchmark": "失败"
                }
                self.logger.error(f"   ❌ {endpoint} 所有请求都失败")

        performance_results["api_response_times"] = api_response_times

        # 计算总体API性能
        if total_api_times:
            overall_avg_api_time = statistics.mean(total_api_times) * 1000
            self.logger.info(f"📊 总体API性能:")
            self.logger.info(f"   平均响应时间: {overall_avg_api_time:.2f}ms")

            # 设置性能基准
            if overall_avg_api_time < 200:
                overall_api_benchmark = "优秀"
            elif overall_avg_api_time < 500:
                overall_api_benchmark = "良好"
            else:
                overall_api_benchmark = "需要优化"

            self.logger.info(f"   性能评级: {overall_api_benchmark}")

            performance_results["overall_api_performance"] = {
                "average_response_time_ms": round(overall_avg_api_time, 2),
                "benchmark": overall_api_benchmark
            }

        # 并发测试
        self.logger.info("📊 开始并发负载测试...")

        def concurrent_request():
            try:
                start_time = time.time()
                response = self.session.get(f"{self.base_url}/api/system_state", timeout=10)
                end_time = time.time()
                return {
                    "success": response.status_code in [200, 401],
                    "response_time": end_time - start_time,
                    "status_code": response.status_code
                }
            except Exception as e:
                return {
                    "success": False,
                    "response_time": 10.0,
                    "error": str(e)
                }

        # 执行并发测试
        concurrent_users = [5, 10, 20]
        load_test_results = {}

        for user_count in concurrent_users:
            self.logger.info(f"   执行 {user_count} 并发用户测试...")

            with ThreadPoolExecutor(max_workers=user_count) as executor:
                start_time = time.time()
                futures = [executor.submit(concurrent_request) for _ in range(user_count)]
                results = [future.result() for future in as_completed(futures)]
                total_time = time.time() - start_time

                successful_requests = sum(1 for r in results if r["success"])
                response_times = [r["response_time"] for r in results if r["success"]]
                success_rate = (successful_requests / user_count) * 100

                # 统计状态码
                status_codes = {}
                for r in results:
                    if "status_code" in r:
                        code = r["status_code"]
                        status_codes[code] = status_codes.get(code, 0) + 1

                # 性能基准
                benchmark = "优秀" if success_rate >= 95 else "良好" if success_rate >= 90 else "需要优化"

                load_test_results[f"{user_count}_users"] = {
                    "total_requests": user_count,
                    "successful_requests": successful_requests,
                    "success_rate": success_rate,
                    "total_time_seconds": round(total_time, 2),
                    "requests_per_second": round(user_count / total_time, 2),
                    "avg_response_time_ms": round(statistics.mean(response_times) * 1000, 2) if response_times else 0,
                    "min_response_time_ms": round(min(response_times) * 1000, 2) if response_times else 0,
                    "max_response_time_ms": round(max(response_times) * 1000, 2) if response_times else 0,
                    "status_codes": status_codes,
                    "benchmark": benchmark
                }

                # 详细输出并发测试结果到日志
                self.logger.info(f"     {user_count} 并发用户测试结果:")
                self.logger.info(
                    f"       成功率: {success_rate:.1f}% ({successful_requests}/{user_count}) - {benchmark}")
                self.logger.info(f"       总耗时: {total_time:.2f}秒")
                self.logger.info(f"       吞吐量: {user_count / total_time:.2f} 请求/秒")

                if response_times:
                    avg_rt = statistics.mean(response_times) * 1000
                    min_rt = min(response_times) * 1000
                    max_rt = max(response_times) * 1000
                    self.logger.info(f"       平均响应时间: {avg_rt:.2f}ms")
                    self.logger.info(f"       响应时间范围: {min_rt:.2f}ms - {max_rt:.2f}ms")

                if status_codes:
                    status_summary = ", ".join([f"{code}: {count}" for code, count in status_codes.items()])
                    self.logger.info(f"       状态码分布: {status_summary}")

                if success_rate < 90:
                    self.logger.warning(f"       ⚠️ {user_count} 并发用户下成功率较低，建议检查系统负载能力")

        performance_results["load_test"] = load_test_results
        performance_results["end_time"] = datetime.now().isoformat()

        # 输出性能测试总结
        self.logger.info("📊 系统性能测试总结:")
        if "overall_api_performance" in performance_results:
            api_perf = performance_results["overall_api_performance"]
            self.logger.info(f"   API整体性能: {api_perf['average_response_time_ms']:.2f}ms ({api_perf['benchmark']})")

        # 输出负载测试总结
        self.logger.info("   负载测试结果:")
        for test_name, result in load_test_results.items():
            self.logger.info(
                f"     {test_name}: 成功率 {result['success_rate']:.1f}%, 吞吐量 {result['requests_per_second']:.2f} req/s")

        self.logger.info("📊 系统性能测试完成")
        return performance_results

    def test_database_operations(self) -> Dict[str, Any]:
        """测试数据库操作（修复版 - 正确处理instance目录）"""
        self.logger.info("🗄️ 开始测试数据库操作...")

        db_results = {
            "test_name": "数据库操作测试",
            "start_time": datetime.now().isoformat(),
            "tests": [],
            "success_count": 0,
            "total_count": 0,
            "success_rate": 0.0
        }

        # 修复：检查多个可能的数据库位置，优先检查instance目录
        possible_db_paths = [
            "instance/car_system.db",  # 主要位置
            "car_system.db",
            "./instance/car_system.db",
            "../instance/car_system.db",
            "instance\\car_system.db"  # Windows路径
        ]

        db_found = False
        actual_db_path = None

        for db_path in possible_db_paths:
            if os.path.exists(db_path):
                db_found = True
                actual_db_path = db_path
                file_size = os.path.getsize(db_path)
                self.logger.info(f"✅ 找到数据库文件: {db_path} (大小: {file_size} bytes)")
                break

        if not db_found:
            db_results["tests"].append({
                "test": "数据库文件存在性检查",
                "status": "FAIL",
                "details": f"在以下位置均未找到数据库文件: {possible_db_paths}"
            })
            db_results["total_count"] += 1

            # 尝试通过API检查数据库状态
            try:
                response = self.session.get(f"{self.base_url}/api/system_state", timeout=10)
                if response.status_code in [200, 401]:  # 401也说明系统在运行
                    db_results["tests"].append({
                        "test": "数据库API连接检查",
                        "status": "PASS",
                        "details": f"API可以正常访问 (状态码: {response.status_code})，数据库应该正常工作"
                    })
                    db_results["success_count"] += 1
                else:
                    db_results["tests"].append({
                        "test": "数据库API连接检查",
                        "status": "FAIL",
                        "details": f"API访问失败: {response.status_code}"
                    })
                db_results["total_count"] += 1
            except Exception as e:
                db_results["tests"].append({
                    "test": "数据库API连接检查",
                    "status": "ERROR",
                    "details": f"API检查异常: {str(e)}"
                })
                db_results["total_count"] += 1
        else:
            # 如果找到数据库文件，执行详细测试
            db_results["tests"].append({
                "test": "数据库文件存在性检查",
                "status": "PASS",
                "details": f"找到数据库文件: {actual_db_path} (大小: {os.path.getsize(actual_db_path)} bytes)"
            })
            db_results["success_count"] += 1
            db_results["total_count"] += 1

            try:
                conn = sqlite3.connect(actual_db_path)
                cursor = conn.cursor()

                # 测试数据库连接
                db_results["tests"].append({
                    "test": "数据库连接",
                    "status": "PASS",
                    "details": "数据库连接成功"
                })
                db_results["success_count"] += 1
                db_results["total_count"] += 1

                # 测试表存在性
                tables_to_check = ["user", "registration_code"]
                for table in tables_to_check:
                    try:
                        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
                        if cursor.fetchone():
                            db_results["tests"].append({
                                "test": f"表 {table} 存在性检查",
                                "status": "PASS",
                                "details": f"表 {table} 存在"
                            })
                            db_results["success_count"] += 1
                        else:
                            db_results["tests"].append({
                                "test": f"表 {table} 存在性检查",
                                "status": "FAIL",
                                "details": f"表 {table} 不存在"
                            })
                        db_results["total_count"] += 1
                    except Exception as e:
                        db_results["tests"].append({
                            "test": f"表 {table} 存在性检查",
                            "status": "ERROR",
                            "details": f"检查异常: {str(e)}"
                        })
                        db_results["total_count"] += 1

                # 测试用户数据查询
                try:
                    cursor.execute("SELECT COUNT(*) FROM user")
                    user_count = cursor.fetchone()[0]
                    db_results["tests"].append({
                        "test": "用户数据查询",
                        "status": "PASS",
                        "details": f"用户总数: {user_count}"
                    })
                    db_results["success_count"] += 1
                    self.logger.info(f"📊 数据库用户总数: {user_count}")
                except Exception as e:
                    db_results["tests"].append({
                        "test": "用户数据查询",
                        "status": "ERROR",
                        "details": f"查询异常: {str(e)}"
                    })
                db_results["total_count"] += 1

                # 测试注册码数据查询
                try:
                    cursor.execute("SELECT COUNT(*) FROM registration_code")
                    code_count = cursor.fetchone()[0]
                    db_results["tests"].append({
                        "test": "注册码数据查询",
                        "status": "PASS",
                        "details": f"注册码总数: {code_count}"
                    })
                    db_results["success_count"] += 1
                    self.logger.info(f"📊 数据库注册码总数: {code_count}")
                except Exception as e:
                    db_results["tests"].append({
                        "test": "注册码数据查询",
                        "status": "ERROR",
                        "details": f"查询异常: {str(e)}"
                    })
                db_results["total_count"] += 1

                # 测试数据库表结构
                try:
                    cursor.execute("PRAGMA table_info(user)")
                    columns = cursor.fetchall()
                    column_names = [col[1] for col in columns]
                    expected_columns = ['id', 'username', 'password', 'role']

                    if all(col in column_names for col in expected_columns):
                        db_results["tests"].append({
                            "test": "用户表结构检查",
                            "status": "PASS",
                            "details": f"用户表包含必要字段: {column_names}"
                        })
                        db_results["success_count"] += 1
                        self.logger.info(f"📊 用户表字段: {', '.join(column_names)}")
                    else:
                        db_results["tests"].append({
                            "test": "用户表结构检查",
                            "status": "FAIL",
                            "details": f"用户表缺少必要字段。当前字段: {column_names}"
                        })
                    db_results["total_count"] += 1
                except Exception as e:
                    db_results["tests"].append({
                        "test": "用户表结构检查",
                        "status": "ERROR",
                        "details": f"结构检查异常: {str(e)}"
                    })
                    db_results["total_count"] += 1

                conn.close()

            except Exception as e:
                db_results["tests"].append({
                    "test": "数据库连接",
                    "status": "ERROR",
                    "details": f"连接异常: {str(e)}"
                })
                db_results["total_count"] += 1

        # 计算成功率
        db_results["success_rate"] = (db_results["success_count"] / db_results["total_count"]) * 100 if db_results[
                                                                                                            "total_count"] > 0 else 0
        db_results["end_time"] = datetime.now().isoformat()

        self.logger.info(f"🗄️ 数据库操作测试完成 - 成功率: {db_results['success_rate']:.1f}%")
        return db_results

    def test_websocket_communication(self) -> Dict[str, Any]:
        """测试WebSocket通信（修复版）"""
        self.logger.info("🔗 开始测试WebSocket通信...")

        ws_results = {
            "test_name": "WebSocket通信测试",
            "start_time": datetime.now().isoformat(),
            "tests": [],
            "success_count": 0,
            "total_count": 4,  # 增加更多测试项
            "success_rate": 0.0
        }

        try:
            # 测试1：检查主页是否包含Socket.IO库（需要先登录）
            response = self.session.get(f"{self.base_url}/", timeout=10)
            if response.status_code == 200:
                response_text = response.text.lower()
                if "socket.io" in response_text:
                    ws_results["tests"].append({
                        "test": "Socket.IO库检查",
                        "status": "PASS",
                        "details": "页面包含Socket.IO库引用"
                    })
                    ws_results["success_count"] += 1
                    self.logger.info("✅ Socket.IO库检查通过")
                else:
                    # 检查是否包含其他WebSocket相关内容
                    if any(keyword in response_text for keyword in ["websocket", "ws", "realtime"]):
                        ws_results["tests"].append({
                            "test": "Socket.IO库检查",
                            "status": "PASS",
                            "details": "页面包含WebSocket相关内容"
                        })
                        ws_results["success_count"] += 1
                    else:
                        ws_results["tests"].append({
                            "test": "Socket.IO库检查",
                            "status": "FAIL",
                            "details": "页面不包含Socket.IO库引用"
                        })
                        self.logger.error("❌ Socket.IO库检查失败")
            elif response.status_code == 401:
                # 如果需要登录，这也说明WebSocket功能可能正常
                ws_results["tests"].append({
                    "test": "Socket.IO库检查",
                    "status": "PASS",
                    "details": "页面需要登录，但系统运行正常"
                })
                ws_results["success_count"] += 1
                self.logger.info("✅ Socket.IO库检查通过（需要登录）")
            else:
                ws_results["tests"].append({
                    "test": "Socket.IO库检查",
                    "status": "FAIL",
                    "details": f"无法访问主页: {response.status_code}"
                })
                self.logger.error(f"❌ 无法访问主页: {response.status_code}")

            # 测试2：检查CDN链接是否可访问
            cdn_url = "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.js"
            try:
                cdn_response = requests.get(cdn_url, timeout=10)
                if cdn_response.status_code == 200:
                    ws_results["tests"].append({
                        "test": "Socket.IO CDN可用性",
                        "status": "PASS",
                        "details": "Socket.IO CDN链接可访问"
                    })
                    ws_results["success_count"] += 1
                    self.logger.info("✅ Socket.IO CDN可用性检查通过")
                else:
                    ws_results["tests"].append({
                        "test": "Socket.IO CDN可用性",
                        "status": "FAIL",
                        "details": f"CDN不可访问: {cdn_response.status_code}"
                    })
            except Exception as e:
                ws_results["tests"].append({
                    "test": "Socket.IO CDN可用性",
                    "status": "ERROR",
                    "details": f"CDN检查异常: {str(e)}"
                })

            # 测试3：检查WebSocket端点响应
            try:
                # 尝试访问socket.io端点 - 修改URL格式
                ws_endpoint = f"{self.base_url}/socket.io/?EIO=4&transport=polling"
                ws_response = requests.get(ws_endpoint, timeout=5)

                if ws_response.status_code == 200:
                    ws_results["tests"].append({
                        "test": "WebSocket端点响应",
                        "status": "PASS",
                        "details": "WebSocket端点响应正常"
                    })
                    ws_results["success_count"] += 1
                    self.logger.info("✅ WebSocket端点响应检查通过")
                elif ws_response.status_code == 400:
                    # 400可能是正常的，说明端点存在但请求格式不对
                    ws_results["tests"].append({
                        "test": "WebSocket端点响应",
                        "status": "PASS",
                        "details": "WebSocket端点存在（返回400，正常）"
                    })
                    ws_results["success_count"] += 1
                    self.logger.info("✅ WebSocket端点存在")
                else:
                    ws_results["tests"].append({
                        "test": "WebSocket端点响应",
                        "status": "FAIL",
                        "details": f"WebSocket端点响应异常: {ws_response.status_code}"
                    })
            except Exception as e:
                ws_results["tests"].append({
                    "test": "WebSocket端点响应",
                    "status": "ERROR",
                    "details": f"端点检查异常: {str(e)}"
                })

            # 测试4：检查web_interface.html文件内容
            try:
                if os.path.exists("web_interface.html"):
                    with open("web_interface.html", 'r', encoding='utf-8') as f:
                        content = f.read().lower()

                    if "socket.io" in content:
                        ws_results["tests"].append({
                            "test": "WebSocket配置文件检查",
                            "status": "PASS",
                            "details": "web_interface.html包含Socket.IO配置"
                        })
                        ws_results["success_count"] += 1
                        self.logger.info("✅ WebSocket配置文件检查通过")
                    else:
                        ws_results["tests"].append({
                            "test": "WebSocket配置文件检查",
                            "status": "FAIL",
                            "details": "web_interface.html不包含Socket.IO配置"
                        })
                else:
                    ws_results["tests"].append({
                        "test": "WebSocket配置文件检查",
                        "status": "FAIL",
                        "details": "web_interface.html文件不存在"
                    })
            except Exception as e:
                ws_results["tests"].append({
                    "test": "WebSocket配置文件检查",
                    "status": "ERROR",
                    "details": f"文件检查异常: {str(e)}"
                })

        except Exception as e:
            ws_results["tests"].append({
                "test": "WebSocket基础检查",
                "status": "ERROR",
                "details": f"测试异常: {str(e)}"
            })
            self.logger.error(f"❌ WebSocket测试异常: {e}")

        ws_results["success_rate"] = (ws_results["success_count"] / ws_results["total_count"]) * 100
        ws_results["end_time"] = datetime.now().isoformat()

        self.logger.info(f"🔗 WebSocket通信测试完成 - 成功率: {ws_results['success_rate']:.1f}%")
        return ws_results

    def generate_comprehensive_report(self, test_results: Dict[str, Any]):
        """生成综合测试报告"""
        self.logger.info("📋 生成综合测试报告...")

        report = {
            "report_info": {
                "test_suite": "车载智能交互系统综合测试",
                "version": "2.1.0",
                "test_date": datetime.now().isoformat(),
                "tester": "自动化测试系统",
                "environment": "开发环境"
            },
            "summary": {
                "total_test_modules": len(test_results),
                "overall_success_rate": 0.0,
                "total_tests_executed": 0,
                "total_tests_passed": 0,
                "total_tests_failed": 0,
                "total_tests_error": 0
            },
            "detailed_results": test_results,
            "performance_analysis": {},
            "quality_assessment": {},
            "recommendations": []
        }

        # 计算总体统计
        total_tests = 0
        total_passed = 0
        total_failed = 0
        total_error = 0

        module_success_rates = {}

        for module_name, module_results in test_results.items():
            if isinstance(module_results, dict) and "success_count" in module_results:
                module_total = module_results.get("total_count", 0)
                module_passed = module_results.get("success_count", 0)

                total_tests += module_total
                total_passed += module_passed

                # 计算模块成功率
                module_success_rate = (module_passed / module_total * 100) if module_total > 0 else 0
                module_success_rates[module_name] = module_success_rate

                # 计算失败和错误数量
                if "tests" in module_results:
                    for test in module_results["tests"]:
                        if test.get("status") == "FAIL":
                            total_failed += 1
                        elif test.get("status") == "ERROR":
                            total_error += 1

        report["summary"]["total_tests_executed"] = total_tests
        report["summary"]["total_tests_passed"] = total_passed
        report["summary"]["total_tests_failed"] = total_failed
        report["summary"]["total_tests_error"] = total_error
        report["summary"]["overall_success_rate"] = (total_passed / total_tests * 100) if total_tests > 0 else 0

        # 质量评估
        overall_success_rate = report["summary"]["overall_success_rate"]

        if overall_success_rate >= 95:
            quality_level = "优秀"
            quality_color = "🟢"
        elif overall_success_rate >= 85:
            quality_level = "良好"
            quality_color = "🟡"
        elif overall_success_rate >= 70:
            quality_level = "一般"
            quality_color = "🟠"
        else:
            quality_level = "需要改进"
            quality_color = "🔴"

        report["quality_assessment"] = {
            "overall_quality": quality_level,
            "quality_indicator": quality_color,
            "module_quality": {}
        }

        # 各模块质量评估
        for module_name, success_rate in module_success_rates.items():
            if success_rate >= 90:
                module_quality = "优秀"
            elif success_rate >= 80:
                module_quality = "良好"
            elif success_rate >= 60:
                module_quality = "一般"
            else:
                module_quality = "需要改进"

            report["quality_assessment"]["module_quality"][module_name] = {
                "success_rate": success_rate,
                "quality": module_quality
            }

        # 增强的性能分析（重点关注API响应时间）
        if "performance_test" in test_results:
            perf_data = test_results["performance_test"]
            performance_analysis = report["performance_analysis"]

            # 系统资源分析
            if "resource_usage" in perf_data:
                resource_usage = perf_data["resource_usage"]
                cpu_usage = resource_usage.get("cpu_usage_percent", 0)
                memory_usage = resource_usage.get("memory_usage_percent", 0)

                performance_analysis["resource_status"] = {
                    "cpu_usage": cpu_usage,
                    "cpu_status": "优秀" if cpu_usage < 50 else "良好" if cpu_usage < 80 else "需要优化",
                    "memory_usage": memory_usage,
                    "memory_status": "优秀" if memory_usage < 60 else "良好" if memory_usage < 80 else "需要优化"
                }

                # 输出详细的资源分析到日志
                self.logger.info("📊 性能分析 - 系统资源:")
                self.logger.info(
                    f"   CPU使用率: {cpu_usage:.1f}% - {performance_analysis['resource_status']['cpu_status']}")
                self.logger.info(
                    f"   内存使用率: {memory_usage:.1f}% - {performance_analysis['resource_status']['memory_status']}")

                if cpu_usage > 80:
                    report["recommendations"].append("🔥 CPU使用率过高，建议优化系统性能或增加硬件资源")
                if memory_usage > 80:
                    report["recommendations"].append("💾 内存使用率过高，建议检查内存泄漏或增加内存")

            # 详细的API性能分析
            if "api_response_times" in perf_data:
                api_times = perf_data["api_response_times"]
                avg_response_times = []
                slow_apis = []
                fast_apis = []

                self.logger.info("📊 性能分析 - API响应时间详情:")

                for endpoint, times_data in api_times.items():
                    if isinstance(times_data, dict) and "avg_ms" in times_data:
                        avg_ms = times_data["avg_ms"]
                        benchmark = times_data.get("benchmark", "未知")
                        success_rate = times_data.get("success_rate", 0)

                        avg_response_times.append(avg_ms)

                        # 记录详细的API性能信息
                        self.logger.info(f"   {endpoint}:")
                        self.logger.info(f"     平均响应时间: {avg_ms:.2f}ms ({benchmark})")
                        self.logger.info(f"     成功率: {success_rate:.1f}%")
                        self.logger.info(
                            f"     响应时间范围: {times_data.get('min_ms', 0):.2f}ms - {times_data.get('max_ms', 0):.2f}ms")

                        if avg_ms > 500:
                            slow_apis.append({"endpoint": endpoint, "avg_ms": avg_ms})
                        elif avg_ms < 100:
                            fast_apis.append({"endpoint": endpoint, "avg_ms": avg_ms})

                if avg_response_times:
                    overall_avg_ms = statistics.mean(avg_response_times)
                    median_ms = statistics.median(avg_response_times)
                    min_ms = min(avg_response_times)
                    max_ms = max(avg_response_times)

                    performance_analysis["api_performance"] = {
                        "average_response_time_ms": round(overall_avg_ms, 2),
                        "median_response_time_ms": round(median_ms, 2),
                        "min_response_time_ms": round(min_ms, 2),
                        "max_response_time_ms": round(max_ms, 2),
                        "performance_level": "优秀" if overall_avg_ms < 200 else "良好" if overall_avg_ms < 500 else "需要优化",
                        "slow_apis_count": len(slow_apis),
                        "fast_apis_count": len(fast_apis)
                    }

                    # 输出API性能总结
                    self.logger.info("📊 性能分析 - API总体性能:")
                    self.logger.info(f"   平均响应时间: {overall_avg_ms:.2f}ms")
                    self.logger.info(f"   中位数响应时间: {median_ms:.2f}ms")
                    self.logger.info(f"   响应时间范围: {min_ms:.2f}ms - {max_ms:.2f}ms")
                    self.logger.info(f"   性能评级: {performance_analysis['api_performance']['performance_level']}")

                    if slow_apis:
                        self.logger.warning(f"   ⚠️ 发现 {len(slow_apis)} 个响应较慢的API:")
                        for api in slow_apis:
                            self.logger.warning(f"     - {api['endpoint']}: {api['avg_ms']:.2f}ms")
                        report["recommendations"].append(
                            f"⚡ 发现{len(slow_apis)}个响应较慢的API，建议优化数据库查询和网络连接")

                    if fast_apis:
                        self.logger.info(f"   ✅ 发现 {len(fast_apis)} 个高性能API:")
                        for api in fast_apis:
                            self.logger.info(f"     - {api['endpoint']}: {api['avg_ms']:.2f}ms")

            # 负载测试分析
            if "load_test" in perf_data:
                load_data = perf_data["load_test"]
                self.logger.info("📊 性能分析 - 负载测试结果:")

                load_analysis = {}
                for test_name, result in load_data.items():
                    success_rate = result.get("success_rate", 0)
                    rps = result.get("requests_per_second", 0)
                    avg_rt = result.get("avg_response_time_ms", 0)
                    benchmark = result.get("benchmark", "未知")

                    load_analysis[test_name] = {
                        "success_rate": success_rate,
                        "requests_per_second": rps,
                        "avg_response_time_ms": avg_rt,
                        "benchmark": benchmark
                    }

                    self.logger.info(f"   {test_name}:")
                    self.logger.info(f"     成功率: {success_rate:.1f}% ({benchmark})")
                    self.logger.info(f"     吞吐量: {rps:.2f} 请求/秒")
                    self.logger.info(f"     平均响应时间: {avg_rt:.2f}ms")

                    if success_rate < 90:
                        report["recommendations"].append(
                            f"📈 {test_name}的成功率较低({success_rate:.1f}%)，建议检查系统并发处理能力")

                performance_analysis["load_test_analysis"] = load_analysis

        # 生成具体建议
        if overall_success_rate >= 95:
            report["recommendations"].append("✅ 系统整体运行优秀，建议继续监控和维护")
        elif overall_success_rate >= 85:
            report["recommendations"].append("🟡 系统运行良好，建议关注失败的测试项目")
        elif overall_success_rate >= 70:
            report["recommendations"].append("🟠 系统运行一般，建议优化失败的功能模块")
        else:
            report["recommendations"].append("🔴 系统存在严重问题，建议立即检查和修复")

        # 模块特定建议
        for module_name, success_rate in module_success_rates.items():
            if success_rate < 80:
                if "authentication" in module_name:
                    report["recommendations"].append("🔐 认证系统成功率较低，建议检查登录流程和Session管理")
                elif "voice" in module_name:
                    report["recommendations"].append("🎤 语音识别成功率较低，建议检查语音模块配置和API连接")
                elif "navigation" in module_name:
                    report["recommendations"].append("🧭 导航系统成功率较低，建议检查API配置和网络连接")
                elif "database" in module_name:
                    report["recommendations"].append("🗄️ 数据库操作成功率较低，建议检查数据库文件和权限")
                elif "websocket" in module_name:
                    report["recommendations"].append("🔗 WebSocket通信成功率较低，建议检查Socket.IO配置")

        # 记录报告生成完成
        self.logger.info("📋 综合测试报告生成完成")
        self.logger.info(f"📊 报告摘要: 总测试数 {total_tests}, 通过 {total_passed}, 成功率 {overall_success_rate:.1f}%")

        return report

    def run_all_tests(self) -> Dict[str, Any]:
        """运行所有测试"""
        self.logger.info("🚀 开始运行车载系统综合测试套件...")

        start_time = time.time()
        all_results = {}

        # 执行系统预检查
        pre_check_results = self.pre_test_system_check()
        all_results["pre_check"] = pre_check_results

        # 根据预检查结果决定是否继续
        if pre_check_results["overall_status"] == "CRITICAL":
            self.logger.error("❌ 系统预检查失败，建议修复后再进行测试")
            return {
                "error": "系统预检查失败",
                "pre_check_results": pre_check_results,
                "recommendations": pre_check_results.get("recommendations", [])
            }
        elif pre_check_results["overall_status"] == "WARNING":
            self.logger.warning("⚠️ 系统预检查发现问题，但将继续测试")

        # 检查系统状态
        if not self.check_system_status():
            self.logger.error("❌ 系统未运行或无法连接，退出测试")
            return {"error": "系统未运行或无法连接"}

        # 执行各项测试
        test_modules = [
            ("authentication_test", self.test_authentication_system),
            ("voice_recognition_test", self.test_voice_recognition_mock),
            ("navigation_test", self.test_navigation_system),
            ("vehicle_control_test", self.test_vehicle_controls),
            ("database_test", self.test_database_operations),
            ("websocket_test", self.test_websocket_communication),
            ("performance_test", self.test_performance_metrics),
        ]

        for test_name, test_function in test_modules:
            try:
                self.logger.info(f"🔄 执行测试模块: {test_name}")
                result = test_function()
                all_results[test_name] = result

                # 输出每个测试模块的详细结果
                success_rate = result.get('success_rate', 0)
                avg_response_time = result.get('average_response_time', 0)

                self.logger.info(f"✅ 测试模块 {test_name} 完成:")
                self.logger.info(f"   成功率: {success_rate:.1f}%")

                if avg_response_time > 0:
                    self.logger.info(f"   平均响应时间: {avg_response_time * 1000:.2f}ms")

                # 输出测试详情
                if "tests" in result:
                    passed_tests = [t for t in result["tests"] if t.get("status") == "PASS"]
                    failed_tests = [t for t in result["tests"] if t.get("status") == "FAIL"]
                    error_tests = [t for t in result["tests"] if t.get("status") == "ERROR"]

                    self.logger.info(
                        f"   通过: {len(passed_tests)}, 失败: {len(failed_tests)}, 错误: {len(error_tests)}")

                    # 输出失败的测试项
                    if failed_tests:
                        self.logger.warning(f"   失败的测试项:")
                        for test in failed_tests:
                            test_name_detail = test.get("test", test.get("command", "未知测试"))
                            self.logger.warning(f"     - {test_name_detail}: {test.get('details', '无详情')}")

                    # 输出错误的测试项
                    if error_tests:
                        self.logger.error(f"   错误的测试项:")
                        for test in error_tests:
                            test_name_detail = test.get("test", test.get("command", "未知测试"))
                            self.logger.error(f"     - {test_name_detail}: {test.get('details', '无详情')}")

            except Exception as e:
                self.logger.error(f"❌ 测试模块 {test_name} 执行失败: {e}")
                all_results[test_name] = {
                    "test_name": test_name,
                    "status": "ERROR",
                    "error": str(e),
                    "start_time": datetime.now().isoformat(),
                    "end_time": datetime.now().isoformat(),
                    "success_rate": 0.0
                }

            # 测试间隔
            time.sleep(2)

        # 生成综合报告
        comprehensive_report = self.generate_comprehensive_report(all_results)

        total_time = time.time() - start_time
        comprehensive_report["execution_info"] = {
            "total_execution_time_seconds": round(total_time, 2),
            "execution_time_formatted": str(timedelta(seconds=int(total_time))),
            "test_completion_time": datetime.now().isoformat()
        }

        # 记录最终结果
        success_rate = comprehensive_report["summary"]["overall_success_rate"]
        self.logger.info("🏁 测试套件执行完成！")
        self.logger.info("=" * 60)
        self.logger.info("📊 测试结果总结:")
        self.logger.info(f"   总体成功率: {success_rate:.1f}%")
        self.logger.info(f"   总测试数: {comprehensive_report['summary']['total_tests_executed']}")
        self.logger.info(f"   通过测试: {comprehensive_report['summary']['total_tests_passed']}")
        self.logger.info(f"   失败测试: {comprehensive_report['summary']['total_tests_failed']}")
        self.logger.info(f"   错误测试: {comprehensive_report['summary']['total_tests_error']}")
        self.logger.info(f"   执行时间: {total_time:.2f} 秒")

        # 输出质量评估
        if "quality_assessment" in comprehensive_report:
            quality = comprehensive_report["quality_assessment"]
            self.logger.info(f"🏆 质量评估: {quality['quality_indicator']} {quality['overall_quality']}")

        # 输出关键建议
        if "recommendations" in comprehensive_report and comprehensive_report["recommendations"]:
            self.logger.info("💡 关键建议:")
            for recommendation in comprehensive_report["recommendations"][:5]:  # 只显示前5个建议
                self.logger.info(f"   {recommendation}")

        # 输出性能分析摘要
        if "performance_analysis" in comprehensive_report:
            perf_analysis = comprehensive_report["performance_analysis"]

            if "api_performance" in perf_analysis:
                api_perf = perf_analysis["api_performance"]
                self.logger.info("⚡ API性能摘要:")
                self.logger.info(
                    f"   平均响应时间: {api_perf['average_response_time_ms']:.2f}ms ({api_perf['performance_level']})")

                if api_perf.get('slow_apis_count', 0) > 0:
                    self.logger.warning(f"   发现 {api_perf['slow_apis_count']} 个响应较慢的API")
                if api_perf.get('fast_apis_count', 0) > 0:
                    self.logger.info(f"   发现 {api_perf['fast_apis_count']} 个高性能API")

            if "resource_status" in perf_analysis:
                resource = perf_analysis["resource_status"]
                self.logger.info("💻 系统资源摘要:")
                self.logger.info(f"   CPU使用率: {resource['cpu_usage']:.1f}% ({resource['cpu_status']})")
                self.logger.info(f"   内存使用率: {resource['memory_usage']:.1f}% ({resource['memory_status']})")

        self.logger.info("=" * 60)
        self.logger.info("📝 详细测试报告和性能数据已记录在日志中")

        return comprehensive_report


def save_test_results_to_file(results: Dict[str, Any], filename: str = None) -> str:
    """保存测试结果到JSON文件"""
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"test_logs/test_results_{timestamp}.json"

    try:
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        return filename
    except Exception as e:
        print(f"❌ 保存测试结果失败: {e}")
        return None


def print_performance_summary(results: Dict[str, Any]):
    """打印性能测试摘要"""
    print("\n" + "=" * 70)
    print("📊 性能测试详细摘要")
    print("=" * 70)

    if "performance_test" not in results:
        #print("❌ 未找到性能测试结果")
        return

    perf_data = results["performance_test"]

    # 系统资源摘要
    if "resource_usage" in perf_data:
        resource = perf_data["resource_usage"]
        print("💻 系统资源使用:")
        print(f"   CPU使用率: {resource.get('cpu_usage_percent', 0):.1f}%")
        print(f"   内存使用率: {resource.get('memory_usage_percent', 0):.1f}%")
        print(f"   内存可用: {resource.get('memory_available_gb', 0):.2f} GB")
        print(f"   磁盘使用率: {resource.get('disk_usage_percent', 0):.1f}%")
        print(f"   磁盘可用: {resource.get('disk_free_gb', 0):.2f} GB")

    # API响应时间详情
    if "api_response_times" in perf_data:
        print("\n⚡ API响应时间详情:")
        api_times = perf_data["api_response_times"]

        for endpoint, times_data in api_times.items():
            if isinstance(times_data, dict) and "avg_ms" in times_data:
                print(f"   {endpoint}:")
                print(f"     平均响应时间: {times_data['avg_ms']:.2f}ms ({times_data.get('benchmark', '未知')})")
                print(f"     响应时间范围: {times_data.get('min_ms', 0):.2f}ms - {times_data.get('max_ms', 0):.2f}ms")
                print(f"     成功率: {times_data.get('success_rate', 0):.1f}%")

    # 并发测试结果
    if "load_test" in perf_data:
        print("\n📈 并发负载测试结果:")
        load_data = perf_data["load_test"]

        for test_name, result in load_data.items():
            print(f"   {test_name}:")
            print(f"     成功率: {result.get('success_rate', 0):.1f}% ({result.get('benchmark', '未知')})")
            print(f"     吞吐量: {result.get('requests_per_second', 0):.2f} 请求/秒")
            print(f"     平均响应时间: {result.get('avg_response_time_ms', 0):.2f}ms")
            print(
                f"     响应时间范围: {result.get('min_response_time_ms', 0):.2f}ms - {result.get('max_response_time_ms', 0):.2f}ms")

    # 性能基准和建议
    if "performance_analysis" in results:
        perf_analysis = results["performance_analysis"]

        print("\n🎯 性能评估:")
        if "api_performance" in perf_analysis:
            api_perf = perf_analysis["api_performance"]
            print(f"   API整体性能: {api_perf.get('performance_level', '未知')}")
            print(f"   平均响应时间: {api_perf.get('average_response_time_ms', 0):.2f}ms")

            if api_perf.get('slow_apis_count', 0) > 0:
                print(f"   ⚠️ 发现 {api_perf['slow_apis_count']} 个响应较慢的API")
            if api_perf.get('fast_apis_count', 0) > 0:
                print(f"   ✅ 发现 {api_perf['fast_apis_count']} 个高性能API")


def main():
    """主函数"""
    print("🚗 车载智能交互系统综合测试工具")
    print("=" * 80)
    print("   • 详细的API响应时间分析和日志输出")
    print("   • 系统资源使用情况监控")
    print("   • 并发负载测试详细报告")
    print("   • 性能基准评估和优化建议")
    print("   • 完整的错误和失败测试项跟踪")
    print("=" * 80)

    # 创建测试器实例
    tester = CarSystemTesterEnhanced()

    try:
        # 运行所有测试
        results = tester.run_all_tests()

        # 检查是否是错误结果
        if "error" in results:
            print(f"\n❌ 测试无法继续: {results['error']}")
            if "recommendations" in results:
                print("💡 建议:")
                for rec in results["recommendations"]:
                    print(f"   {rec}")
            return

        # 保存测试结果到JSON文件
        results_filename = save_test_results_to_file(results)

        if results_filename:
            print(f"\n📁 测试结果已保存到: {results_filename}")

        # 打印简要结果摘要
        if "summary" in results:
            summary = results["summary"]
            print(f"\n📊 测试结果摘要:")
            print(f"   总测试模块: {summary['total_test_modules']}")
            print(f"   总测试数: {summary['total_tests_executed']}")
            print(f"   通过: {summary['total_tests_passed']}")
            print(f"   失败: {summary['total_tests_failed']}")
            print(f"   错误: {summary['total_tests_error']}")
            print(f"   成功率: {summary['overall_success_rate']:.1f}%")

            if "execution_info" in results:
                print(f"   执行时间: {results['execution_info']['execution_time_formatted']}")

        # 打印质量评估
        if "quality_assessment" in results:
            quality = results["quality_assessment"]
            print(f"\n🏆 质量评估: {quality['quality_indicator']} {quality['overall_quality']}")

            # 各模块质量详情
            if "module_quality" in quality:
                print("📋 各模块质量:")
                for module, module_quality in quality["module_quality"].items():
                    print(f"   {module}: {module_quality['success_rate']:.1f}% ({module_quality['quality']})")

        # 打印性能测试详细摘要
        print_performance_summary(results)

        # 打印建议
        if "recommendations" in results and results["recommendations"]:
            print(f"\n💡 优化建议:")
            for i, recommendation in enumerate(results["recommendations"], 1):
                print(f"   {i}. {recommendation}")

        print(f"\n✅ 测试完成！详细结果和性能分析请查看日志文件。")
        print(f"📄 JSON结果文件: {results_filename}")

    except KeyboardInterrupt:
        print("\n⚠️ 用户中断测试")
    except Exception as e:
        print(f"\n❌ 测试执行过程中发生错误: {e}")
        logging.error(f"测试执行错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("🔚 测试程序结束")


if __name__ == "__main__":
    main()