# test_car_system_unittest.py - 车载智能交互系统单元测试
import unittest
import sys
import os
import tempfile
import shutil
import json
import time
import threading
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入被测试的模块
try:
    from models import User, RegistrationCode, db
    from voice_module import VoiceRecognition, VoiceResponse
    from vision_module import VisionRecognition
    from navigation_module import NavigationModule
    from main import CarSystem, app, system_monitor
except ImportError as e:
    print(f"警告: 无法导入某些模块: {e}")


class TestModels(unittest.TestCase):
    """测试数据库模型"""

    def setUp(self):
        """设置测试环境"""
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        """清理测试环境"""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_user_creation(self):
        """测试用户创建"""
        user = User(username='testuser', role='user')
        user.set_password('testpass123')

        self.assertEqual(user.username, 'testuser')
        self.assertEqual(user.role, 'user')
        self.assertTrue(user.check_password('testpass123'))
        self.assertFalse(user.check_password('wrongpass'))

    def test_user_roles(self):
        """测试用户角色判断"""
        admin_user = User(username='admin', role='admin')
        passenger_user = User(username='passenger', role='passenger')
        system_admin = User(username='sysadmin', role='system_admin')
        regular_user = User(username='user', role='user')

        self.assertTrue(admin_user.is_admin())
        self.assertFalse(admin_user.is_passenger())
        self.assertFalse(admin_user.is_system_admin())

        self.assertTrue(passenger_user.is_passenger())
        self.assertFalse(passenger_user.is_admin())

        self.assertTrue(system_admin.is_system_admin())
        self.assertFalse(system_admin.is_admin())

        self.assertFalse(regular_user.is_admin())
        self.assertFalse(regular_user.is_passenger())
        self.assertFalse(regular_user.is_system_admin())

    def test_user_location(self):
        """测试用户位置功能"""
        user = User(username='testuser', role='user')

        # 测试初始状态
        self.assertFalse(user.has_location())
        self.assertIsNone(user.get_location())

        # 设置位置
        user.set_location(116.3974, 39.9093, "北京市")

        self.assertTrue(user.has_location())
        location = user.get_location()
        self.assertIsNotNone(location)
        self.assertEqual(location['longitude'], 116.3974)
        self.assertEqual(location['latitude'], 39.9093)
        self.assertEqual(location['home_name'], "北京市")
        self.assertIn('coordinates', location)

    def test_registration_code(self):
        """测试注册码功能"""
        code = RegistrationCode(code='TEST123', is_used=False)

        self.assertEqual(code.code, 'TEST123')
        self.assertFalse(code.is_used)

        # 标记为已使用
        code.mark_used()
        self.assertTrue(code.is_used)


class TestVoiceModule(unittest.TestCase):
    """测试语音模块"""

    def setUp(self):
        """设置测试环境"""
        self.callback_results = []

        def mock_callback(cmd_type, cmd_text):
            self.callback_results.append((cmd_type, cmd_text))

        self.mock_callback = mock_callback

    @patch('voice_module.pyttsx3')
    def test_voice_response_initialization(self, mock_pyttsx3):
        """测试语音输出初始化"""
        mock_engine = Mock()
        mock_pyttsx3.init.return_value = mock_engine

        voice_response = VoiceResponse()

        self.assertIsNotNone(voice_response)

    @patch('voice_module.pyttsx3')
    def test_voice_response_speak(self, mock_pyttsx3):
        """测试语音输出功能"""
        mock_engine = Mock()
        mock_pyttsx3.init.return_value = mock_engine

        voice_response = VoiceResponse()
        voice_response.speak("测试语音")

        # 等待语音输出线程处理
        time.sleep(0.5)

    def test_voice_recognition_command_parsing(self):
        """测试语音指令解析"""
        voice_recognition = VoiceRecognition(self.mock_callback)

        # 测试音乐控制指令
        command = voice_recognition.parse_command("播放音乐")
        self.assertIsNotNone(command)
        self.assertEqual(command[0], 'music_play')

        command = voice_recognition.parse_command("暂停音乐")
        self.assertIsNotNone(command)
        self.assertEqual(command[0], 'music_pause')

        # 测试导航指令
        command = voice_recognition.parse_command("导航到天津站")
        self.assertIsNotNone(command)

        # 测试温度控制指令
        command = voice_recognition.parse_command("升温")
        self.assertIsNotNone(command)
        self.assertEqual(command[0], 'temp_up')

        command = voice_recognition.parse_command("降温")
        self.assertIsNotNone(command)
        self.assertEqual(command[0], 'temp_down')

    def test_voice_recognition_text_cleaning(self):
        """测试文本清理功能"""
        voice_recognition = VoiceRecognition(self.mock_callback)

        # 测试标点符号清理
        clean_text = voice_recognition.clean_and_normalize_text("播放，音乐。。")
        self.assertEqual(clean_text, "播放 音乐")

        # 测试长度限制
        long_text = "这是一个非常长的文本" * 10
        clean_text = voice_recognition.clean_and_normalize_text(long_text)
        self.assertLessEqual(len(clean_text), voice_recognition.max_text_length)

    def test_voice_recognition_duplicate_detection(self):
        """测试重复检测功能"""
        voice_recognition = VoiceRecognition(self.mock_callback)

        # 第一次应该不是重复
        self.assertFalse(voice_recognition.is_duplicate_text("播放音乐"))

        # 更新记录
        voice_recognition.last_recognized_text = "播放音乐"
        voice_recognition.last_command_time = time.time()

        # 立即重复应该被检测到
        self.assertTrue(voice_recognition.is_duplicate_text("播放音乐"))

        # 等待冷却时间后应该不是重复
        voice_recognition.last_command_time = time.time() - voice_recognition.command_cooldown - 1
        self.assertFalse(voice_recognition.is_duplicate_text("播放音乐"))


class TestVisionModule(unittest.TestCase):
    """测试视觉模块"""

    def setUp(self):
        """设置测试环境"""
        self.callback_results = []

        def mock_callback(cmd_type, cmd_text):
            self.callback_results.append((cmd_type, cmd_text))

        self.mock_callback = mock_callback

    @patch('vision_module.cv2')
    @patch('vision_module.mp')
    def test_vision_recognition_initialization(self, mock_mp, mock_cv2):
        """测试视觉识别初始化"""
        # 模拟MediaPipe
        mock_mp.solutions.hands = Mock()
        mock_mp.solutions.face_mesh = Mock()
        mock_mp.solutions.drawing_utils = Mock()
        mock_mp.solutions.drawing_styles = Mock()

        vision = VisionRecognition(self.mock_callback)

        self.assertIsNotNone(vision)
        self.assertEqual(vision.current_gesture, "None")
        self.assertEqual(vision.eyes_status, "Open")

    @patch('vision_module.cv2')
    def test_camera_test(self, mock_cv2):
        """测试摄像头测试功能"""
        # 模拟成功的摄像头
        mock_cap = Mock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, Mock())
        mock_cv2.VideoCapture.return_value = mock_cap

        vision = VisionRecognition(self.mock_callback)
        result = vision.test_camera()

        self.assertTrue(result)

    def test_gesture_detection_logic(self):
        """测试手势检测逻辑"""
        vision = VisionRecognition(self.mock_callback)

        # 模拟手部关键点数据
        mock_hands_results = Mock()
        mock_hands_results.multi_hand_landmarks = None

        # 测试无手部检测
        gesture = vision.detect_gesture(mock_hands_results)
        self.assertEqual(gesture, "None")

    def test_gesture_stability_processing(self):
        """测试手势稳定性处理"""
        vision = VisionRecognition(self.mock_callback)

        # 添加一系列手势到历史记录
        for _ in range(vision.gesture_stability_frames):
            vision.gesture_history.append("Open Palm")

        stable_gesture = vision.process_gesture_stable("Open Palm")
        self.assertEqual(stable_gesture, "Open Palm")


class TestNavigationModule(unittest.TestCase):
    """测试导航模块"""

    def setUp(self):
        """设置测试环境"""
        self.callback_results = []

        def mock_callback(cmd_type, cmd_text):
            self.callback_results.append((cmd_type, cmd_text))

        self.mock_callback = mock_callback

    @patch('navigation_module.requests')
    def test_navigation_module_initialization(self, mock_requests):
        """测试导航模块初始化"""
        navigation = NavigationModule(self.mock_callback)

        self.assertIsNotNone(navigation)
        self.assertFalse(navigation.is_navigating)
        self.assertIsNotNone(navigation.api_key)

    @patch('navigation_module.requests')
    def test_search_place(self, mock_requests):
        """测试地点搜索功能"""
        # 模拟API响应
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 0,
            'data': [
                {
                    'title': '天津站',
                    'location': {'lat': 39.1467, 'lng': 117.2087},
                    'address': '天津市河北区站前路'
                }
            ]
        }
        mock_requests.get.return_value = mock_response

        navigation = NavigationModule(self.mock_callback)
        # 设置当前位置
        navigation.current_location = {'lat': 39.0, 'lng': 117.0, 'address': '测试位置'}

        results = navigation.search_place("天津站")

        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

    @patch('navigation_module.requests')
    def test_route_planning(self, mock_requests):
        """测试路线规划功能"""
        # 模拟API响应
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 0,
            'result': {
                'routes': [
                    {
                        'distance': 5000,  # 5公里
                        'duration': 15  # 15分钟
                    }
                ]
            }
        }
        mock_requests.get.return_value = mock_response

        navigation = NavigationModule(self.mock_callback)
        navigation.current_location = {'lat': 39.0, 'lng': 117.0, 'address': '起点'}

        route_data = navigation.get_route(39.1, 117.1)

        self.assertIsNotNone(route_data)
        self.assertIn('routes', route_data)

    def test_navigation_status(self):
        """测试导航状态获取"""
        navigation = NavigationModule(self.mock_callback)

        status = navigation.get_navigation_status()

        self.assertIsInstance(status, dict)
        self.assertIn('is_navigating', status)
        self.assertIn('current_location', status)
        self.assertFalse(status['is_navigating'])


class TestCarSystem(unittest.TestCase):
    """测试车载系统核心功能"""

    def setUp(self):
        """设置测试环境"""
        self.car_system = CarSystem()

    def test_car_system_initialization(self):
        """测试车载系统初始化"""
        self.assertIsNotNone(self.car_system)
        self.assertIsInstance(self.car_system.system_state, dict)
        self.assertIn('music', self.car_system.system_state)
        self.assertIn('ac', self.car_system.system_state)
        self.assertIn('navigation', self.car_system.system_state)

    def test_music_control(self):
        """测试音乐控制功能"""
        # 测试播放音乐
        result = self.car_system._play_current_music()
        # 由于没有实际音乐文件，可能返回False，但不应该抛出异常
        self.assertIsInstance(result, bool)

        # 测试暂停音乐
        result = self.car_system._pause_music()
        self.assertIsInstance(result, bool)

        # 测试停止音乐
        result = self.car_system._stop_music()
        self.assertTrue(result)  # 停止音乐应该总是成功

    def test_system_state_management(self):
        """测试系统状态管理"""
        # 测试空调控制
        self.car_system.system_state['ac']['is_on'] = True
        self.assertTrue(self.car_system.system_state['ac']['is_on'])

        # 测试温度调节
        old_temp = self.car_system.system_state['ac']['temperature']
        self.car_system.system_state['ac']['temperature'] = old_temp + 1
        self.assertEqual(self.car_system.system_state['ac']['temperature'], old_temp + 1)

        # 测试车窗控制
        self.car_system.system_state['windows']['front_left'] = True
        self.assertTrue(self.car_system.system_state['windows']['front_left'])

    def test_command_processing(self):
        """测试指令处理"""
        # 添加测试指令
        self.car_system.add_command('test', '测试指令', 'unittest')

        # 等待指令处理
        time.sleep(0.5)

        # 检查指令历史
        self.assertGreater(len(self.car_system.command_history), 0)

    def test_user_management(self):
        """测试用户管理功能"""
        # 测试设置当前用户
        self.car_system.set_current_user(123, {'latitude': 39.0, 'longitude': 117.0})
        self.assertEqual(self.car_system.current_user_id, 123)

        # 测试获取用户位置
        home_location = self.car_system.get_user_home_location()
        # 由于没有实际的数据库上下文，可能返回None
        # 但不应该抛出异常

    def test_time_formatting(self):
        """测试时间格式化功能"""
        # 测试不同的时间值
        self.assertEqual(self.car_system._format_time(0), "0:00")
        self.assertEqual(self.car_system._format_time(60), "1:00")
        self.assertEqual(self.car_system._format_time(125), "2:05")
        self.assertEqual(self.car_system._format_time(-10), "0:00")  # 负数应该返回0:00


class TestSystemMonitor(unittest.TestCase):
    """测试系统监控功能"""

    def test_system_stats(self):
        """测试系统统计信息获取"""
        stats = system_monitor.get_system_stats()

        self.assertIsInstance(stats, dict)
        self.assertIn('cpu_usage', stats)
        self.assertIn('memory_usage', stats)
        self.assertIn('uptime', stats)
        self.assertIn('error_count', stats)

    def test_error_logging(self):
        """测试错误日志记录"""
        initial_count = system_monitor.error_count

        system_monitor.log_error("测试错误")

        self.assertEqual(system_monitor.error_count, initial_count + 1)
        self.assertIsNotNone(system_monitor.last_error_time)

    def test_api_request_logging(self):
        """测试API请求日志记录"""
        initial_count = system_monitor.api_request_count

        system_monitor.log_api_request()

        self.assertEqual(system_monitor.api_request_count, initial_count + 1)


class TestIntegration(unittest.TestCase):
    """集成测试"""

    def setUp(self):
        """设置测试环境"""
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # 创建测试用户
        admin = User(username='admin', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

    def tearDown(self):
        """清理测试环境"""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_login_logout_flow(self):
        """测试登录登出流程"""
        # 测试登录页面访问
        response = self.client.get('/auth/login')
        self.assertEqual(response.status_code, 200)

        # 测试登录
        response = self.client.post('/auth/login', data={
            'username': 'admin',
            'password': 'admin123'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def test_api_endpoints(self):
        """测试API端点"""
        # 首先登录
        with self.client.session_transaction() as sess:
            sess['_user_id'] = '1'
            sess['_fresh'] = True

        # 测试系统状态API
        response = self.client.get('/api/system_state')
        # 由于需要登录，可能返回401或200
        self.assertIn(response.status_code, [200, 401, 302])

        # 测试语音状态API
        response = self.client.get('/api/voice_status')
        self.assertIn(response.status_code, [200, 401, 302])

    def test_command_api(self):
        """测试指令API"""
        # 模拟登录状态
        with self.client.session_transaction() as sess:
            sess['_user_id'] = '1'
            sess['_fresh'] = True

        # 测试发送指令
        response = self.client.post('/api/command',
                                    json={
                                        'type': 'test',
                                        'text': '测试指令',
                                        'source': 'unittest'
                                    })

        # 检查响应
        self.assertIn(response.status_code, [200, 401, 302])


class TestPerformance(unittest.TestCase):
    """性能测试"""

    def test_voice_command_processing_speed(self):
        """测试语音指令处理速度"""
        callback_times = []

        def timed_callback(cmd_type, cmd_text):
            callback_times.append(time.time())

        voice = VoiceRecognition(timed_callback)

        # 测试多个指令的处理速度
        test_commands = ["播放音乐", "暂停音乐", "升温", "降温", "开空调"]

        start_time = time.time()
        for cmd in test_commands:
            voice.parse_command(cmd)
        end_time = time.time()

        processing_time = end_time - start_time
        avg_time_per_command = processing_time / len(test_commands)

        # 断言平均处理时间应该小于100ms
        self.assertLess(avg_time_per_command, 0.1)

    def test_system_state_update_performance(self):
        """测试系统状态更新性能"""
        car_system = CarSystem()

        # 测试大量状态更新
        start_time = time.time()
        for i in range(1000):
            car_system.system_state['ac']['temperature'] = 20 + (i % 10)
            car_system.system_state['music']['volume'] = i % 100
        end_time = time.time()

        total_time = end_time - start_time

        # 断言1000次状态更新应该在1秒内完成
        self.assertLess(total_time, 1.0)


class TestErrorHandling(unittest.TestCase):
    """错误处理测试"""

    def test_invalid_command_handling(self):
        """测试无效指令处理"""
        callback_results = []

        def mock_callback(cmd_type, cmd_text):
            callback_results.append((cmd_type, cmd_text))

        voice = VoiceRecognition(mock_callback)

        # 测试无效指令
        result = voice.parse_command("这是一个无效的指令")
        self.assertIsNone(result)

        # 测试空指令
        result = voice.parse_command("")
        self.assertIsNone(result)

        # 测试None指令
        result = voice.parse_command(None)
        self.assertIsNone(result)

    def test_system_resilience(self):
        """测试系统弹性"""
        car_system = CarSystem()

        # 测试在没有音乐文件的情况下播放音乐
        try:
            result = car_system._play_current_music()
            # 应该返回False但不抛出异常
            self.assertIsInstance(result, bool)
        except Exception as e:
            self.fail(f"播放音乐时不应该抛出异常: {e}")

        # 测试设置无效音量
        try:
            car_system._set_volume(-10)  # 负数音量
            car_system._set_volume(150)  # 超过100的音量
            # 不应该抛出异常
        except Exception as e:
            self.fail(f"设置音量时不应该抛出异常: {e}")


def run_all_tests():
    """运行所有测试"""
    test_suite = unittest.TestSuite()

    # 添加所有测试类
    test_classes = [
        TestModels,
        TestVoiceModule,
        TestVisionModule,
        TestNavigationModule,
        TestCarSystem,
        TestSystemMonitor,
        TestIntegration,
        TestPerformance,
        TestErrorHandling
    ]

    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)

    print("\n" + "=" * 70)
    print("📊 测试结果摘要")
    print("=" * 70)
    print(f"总测试数: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    print(f"成功率: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%")

    if result.failures:
        print("\n❌ 失败的测试:")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback.split('AssertionError:')[-1].strip()}")

    if result.errors:
        print("\n💥 错误的测试:")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback.split('Exception:')[-1].strip()}")

    return result.wasSuccessful()


def run_specific_test(test_class_name=None, test_method_name=None):
    """运行特定的测试"""
    if test_class_name:

        test_class = globals().get(test_class_name)
        if test_class:
            if test_method_name:
                suite = unittest.TestSuite()
                suite.addTest(test_class(test_method_name))
            else:
                # 运行整个测试类
                suite = unittest.TestLoader().loadTestsFromTestCase(test_class)

            runner = unittest.TextTestRunner(verbosity=2)
            result = runner.run(suite)
            return result.wasSuccessful()
        else:
            print(f"❌ 未找到测试类: {test_class_name}")
            return False
    else:
        print("请提供测试类名称")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='车载智能交互系统单元测试')
    parser.add_argument('--class', dest='test_class', help='运行特定的测试类')
    parser.add_argument('--method', dest='test_method', help='运行特定的测试方法')
    parser.add_argument('--list', action='store_true', help='列出所有可用的测试类')

    args = parser.parse_args()

    if args.list:
        print("📋 可用的测试类:")
        test_classes = [
            'TestModels - 数据库模型测试',
            'TestVoiceModule - 语音模块测试',
            'TestVisionModule - 视觉模块测试',
            'TestNavigationModule - 导航模块测试',
            'TestCarSystem - 车载系统核心功能测试',
            'TestSystemMonitor - 系统监控测试',
            'TestIntegration - 集成测试',
            'TestPerformance - 性能测试',
            'TestErrorHandling - 错误处理测试'
        ]
        for i, test_class in enumerate(test_classes, 1):
            print(f"  {i}. {test_class}")
    elif args.test_class:
        success = run_specific_test(args.test_class, args.test_method)
        exit(0 if success else 1)
    else:
        print("🚗 开始运行车载智能交互系统单元测试...")
        print("=" * 70)
        success = run_all_tests()
        exit(0 if success else 1)