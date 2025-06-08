import json
import time
import threading
import queue
import logging
import os
import sys
import psutil
import io
import secrets
from datetime import datetime, timedelta
from flask import Flask,render_template_string, jsonify, request, Response, send_file, session, redirect, url_for, \
    flash, render_template
from flask_socketio import SocketIO, emit
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, RegistrationCode          # ← 统一引用
from werkzeug.security import generate_password_hash, check_password_hash
import cv2
import pyttsx3
from auth import init_auth, login_manager  # 新增
import secrets
import string
from werkzeug.security import generate_password_hash

# 确保模块能被导入
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 替换标准输出为 UTF-8 编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('car_system.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 导入自定义模块
try:
    from voice_module import VoiceRecognition
    from vision_module import VisionRecognition
    from navigation_module import NavigationModule

    logger.info("✅ 模块导入成功")
except ImportError as e:
    logger.error(f"❌ 模块导入失败: {e}")
    print("请确保 voice_module.py、vision_module.py 和 navigation_module.py 在同一目录下")
    sys.exit(1)


# ============== 系统监控类 ==============
class SystemMonitor:
    def __init__(self):
        self.start_time = datetime.now()
        self.error_count = 0
        self.last_error_time = None
        self.api_request_count = 0
        self.websocket_connections = 0

    def get_system_stats(self):
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            uptime = datetime.now() - self.start_time

            return {
                'cpu_usage': cpu_percent,
                'memory_usage': memory.percent,
                'disk_usage': disk.percent,
                'uptime': str(uptime).split('.')[0],
                'start_time': self.start_time.isoformat(),
                'error_count': self.error_count,
                'last_error_time': self.last_error_time.isoformat() if self.last_error_time else None,
                'api_requests': self.api_request_count,
                'websocket_connections': self.websocket_connections
            }
        except Exception as e:
            logger.error(f"获取系统统计失败: {e}")
            return {
                'cpu_usage': 0, 'memory_usage': 0, 'disk_usage': 0,
                'uptime': '00:00:00', 'start_time': self.start_time.isoformat(),
                'error_count': self.error_count, 'last_error_time': None,
                'api_requests': self.api_request_count, 'websocket_connections': self.websocket_connections
            }

    def log_error(self, error_msg):
        self.error_count += 1
        self.last_error_time = datetime.now()
        logger.error(error_msg)

    def log_api_request(self):
        self.api_request_count += 1

    def update_websocket_connections(self, count):
        self.websocket_connections = count


# ============== 车载系统类 ==============
class CarSystem:
    def __init__(self, socketio_instance=None):
        self.socketio = socketio_instance

        # 新增：当前用户缓存
        self.current_user_id = None
        self.current_user_home = None
        self.app_context = None  # 用于存储应用上下文

        # 初始化pygame音频模块
        try:
            import pygame
            pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            logger.info("🎵 音频模块初始化成功")
        except Exception as e:
            logger.error(f"❌ 音频模块初始化失败: {e}")

        # 本地音乐文件夹路径
        self.music_folder = "local_music"
        self.music_files = []
        self.current_music_index = 0

        # 音乐播放状态跟踪
        self.music_start_time = 0
        self.music_pause_time = 0
        self.music_paused_duration = 0

        # 扫描本地音乐文件
        self._scan_music_files()

        self.system_state = {
            # 音乐系统 - 增强版
            'music': {
                'title': self.music_files[0]['title'] if self.music_files else '无音乐',
                'artist': self.music_files[0]['artist'] if self.music_files else '未知',
                'album': self.music_files[0]['album'] if self.music_files else '未知专辑',
                'file_path': self.music_files[0]['path'] if self.music_files else '',
                'is_playing': False,
                'is_paused': False,
                'progress': 0,
                'duration': self.music_files[0]['duration'] if self.music_files else 0,
                'progress_percentage': 0,
                'volume': 50,
                'total_files': len(self.music_files),
                'current_index': 0,
                'shuffle_mode': False,
                'repeat_mode': 'none',
                'current_time_str': '0:00',
                'total_time_str': '0:00',
                'playlist': self.music_files
            },
            # 空调系统
            'ac': {
                'temperature': 22,
                'is_on': False,
                'mode': 'auto'
            },
            # 车窗状态
            'windows': {
                'front_left': False,
                'front_right': False,
                'rear_left': False,
                'rear_right': False
            },
            # 灯光状态
            'lights': {
                'headlights': False,
                'interior': False
            },
            # 驾驶员状态
            'driver': {
                'state': '正常',
                'alertness': 'normal'
            },
            # 手势识别
            'gesture': {
                'current': '无',
                'last_time': ''
            },
            # 导航状态
            'navigation': {
                'is_navigating': False,
                'current_location': None,
                'destination': None,
                'distance': 0,
                'duration': 0,
                'map_ready': False
            }
        }

        self.command_history = []
        self.command_queue = queue.Queue()

        # 启动命令处理线程
        self.command_thread = threading.Thread(target=self._process_commands, daemon=True)
        self.command_thread.start()

        # 启动音乐状态监控线程
        self.music_monitor_thread = threading.Thread(target=self._monitor_music, daemon=True)
        self.music_monitor_thread.start()

        # 分心警告系统 - 简化版本
        self.is_driver_distracted = False
        self.distraction_alert_thread = None
        self.distraction_alert_stop_event = threading.Event()
        self.distraction_alert_count = 0

        # TTS队列系统（在_init_simple_tts中初始化）
        self.tts_queue = None
        self.tts_worker_thread = None

        # 简单语音提醒系统初始化
        self.tts_engine = None
        self.tts_lock = threading.Lock()
        self._init_simple_tts()

        logger.info("🚗 车载智能系统已初始化")

    def set_current_user(self, user_id, home_location=None):
        """设置当前用户信息（在有Flask上下文时调用）"""
        self.current_user_id = user_id
        self.current_user_home = home_location
        logger.info(f"🔧 已设置当前用户: {user_id}, 家位置: {'已设置' if home_location else '未设置'}")

    def get_user_home_location(self):
        """获取当前用户的家位置"""
        if not self.current_user_id:
            logger.warning("⚠️ 没有设置当前用户ID")
            return None

        try:
            # 使用应用上下文查询数据库
            if self.app_context:
                with self.app_context:
                    from models import User
                    user = User.query.get(self.current_user_id)
                    if user and user.has_location():
                        return user.get_location()
            return None
        except Exception as e:
            logger.error(f"❌ 获取用户家位置失败: {e}")
            return None

    def _format_time(self, seconds):
        """将秒数格式化为 MM:SS"""
        if seconds < 0:
            seconds = 0
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        return f"{minutes}:{seconds:02d}"

    def _get_audio_duration(self, file_path):
        """获取音频文件时长"""
        try:
            import mutagen
            audio_file = mutagen.File(file_path)
            if audio_file is not None:
                return int(audio_file.info.length)
            return 0
        except:
            try:
                import pygame
                sound = pygame.mixer.Sound(file_path)
                return int(sound.get_length())
            except:
                return 270  # 默认4分30秒

    def _scan_music_files(self):
        """扫描本地音乐文件"""
        self.music_files = []

        if not os.path.exists(self.music_folder):
            logger.info(f"📁 创建音乐文件夹: {self.music_folder}")
            os.makedirs(self.music_folder)
            # 如果没有音乐文件，添加一些示例
            self.music_files = [
                {
                    'title': '晴天',
                    'artist': '周杰伦',
                    'album': '叶惠美',
                    'path': '',
                    'duration': 270,  # 4分30秒
                    'filename': 'demo1.mp3'
                },
                {
                    'title': '稻香',
                    'artist': '周杰伦',
                    'album': '魔杰座',
                    'path': '',
                    'duration': 223,  # 3分43秒
                    'filename': 'demo2.mp3'
                },
            ]
            return

        # 支持的音频格式
        supported_formats = ['.mp3', '.wav', '.ogg', '.m4a', '.flac']

        try:
            for filename in os.listdir(self.music_folder):
                if any(filename.lower().endswith(fmt) for fmt in supported_formats):
                    file_path = os.path.join(self.music_folder, filename)
                    name_without_ext = os.path.splitext(filename)[0]

                    # 优先用文件名分割
                    if ' - ' in name_without_ext:
                        artist, title = name_without_ext.split(' - ', 1)
                    else:
                        # 尝试读取元数据
                        try:
                            import mutagen
                            audio_file = mutagen.File(file_path)
                            if audio_file:
                                title = audio_file.get('TIT2', [name_without_ext])[0] if audio_file.get(
                                    'TIT2') else name_without_ext
                                artist = audio_file.get('TPE1', ['未知艺术家'])[0] if audio_file.get(
                                    'TPE1') else '未知艺术家'
                            else:
                                title = name_without_ext
                                artist = '未知艺术家'
                        except:
                            title = name_without_ext
                            artist = '未知艺术家'

                    # 专辑和时长
                    try:
                        import mutagen
                        audio_file = mutagen.File(file_path)
                        album = audio_file.get('TALB', ['未知专辑'])[0] if audio_file and audio_file.get(
                            'TALB') else '未知专辑'
                        duration = int(
                            audio_file.info.length) if audio_file and audio_file.info else self._get_audio_duration(
                            file_path)
                    except:
                        album = '未知专辑'
                        duration = self._get_audio_duration(file_path)

                    self.music_files.append({
                        'title': title,
                        'artist': artist,
                        'album': album,
                        'path': file_path,
                        'filename': filename,
                        'duration': duration
                    })

            if self.music_files:
                logger.info(f"🎵 扫描到 {len(self.music_files)} 首音乐:")
                for i, music in enumerate(self.music_files):
                    duration_str = self._format_time(music['duration'])
                    logger.info(f"   {i + 1}. {music['artist']} - {music['title']} ({duration_str})")
            else:
                logger.warning("⚠️ 未找到音乐文件，请将音乐文件放入 local_music 文件夹")

        except Exception as e:
            logger.error(f"❌ 扫描音乐文件失败: {e}")

    def _init_simple_tts(self):
        """初始化简单的TTS语音引擎"""
        try:
            self.tts_engine = pyttsx3.init()
            # 设置语音参数
            self.tts_engine.setProperty('rate', 150)  # 语速
            self.tts_engine.setProperty('volume', 0.9)  # 音量

            # 尝试设置中文语音
            voices = self.tts_engine.getProperty('voices')
            if voices:
                for voice in voices:
                    if any(keyword in voice.name.lower() for keyword in ['chinese', 'zh', 'mandarin']):
                        self.tts_engine.setProperty('voice', voice.id)
                        break

            # 添加TTS队列处理
            self.tts_queue = queue.Queue()
            self.tts_worker_thread = threading.Thread(target=self._tts_worker, daemon=True)
            self.tts_worker_thread.start()

            logger.info("✅ 简单语音提醒系统初始化成功")
        except Exception as e:
            logger.error(f"❌ 语音提醒系统初始化失败: {e}")
            self.tts_engine = None

    def _tts_worker(self):
        """TTS工作线程，串行处理语音播放"""
        while True:
            try:
                # 获取语音任务
                message = self.tts_queue.get(timeout=1)
                if message is None:  # 停止信号
                    break

                # 播放语音
                self._speak_direct(message)
                self.tts_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"❌ TTS工作线程错误: {e}")

    def _speak_direct(self, message):
        """直接播放语音（在TTS工作线程中调用）"""
        try:
            if not self.tts_engine:
                logger.warning("⚠️ TTS引擎未初始化")
                return

            logger.info(f"🔊 开始播放语音: {message}")

            # 重新初始化引擎以避免状态问题
            try:
                self.tts_engine.stop()
            except:
                pass

            self.tts_engine.say(message)
            self.tts_engine.runAndWait()

            logger.info(f"✅ 语音播放完成: {message}")

        except Exception as e:
            logger.error(f"❌ 语音播放失败: {e}")
            # 尝试重新初始化TTS引擎
            try:
                self.tts_engine.stop()
                self.tts_engine = pyttsx3.init()
                self.tts_engine.setProperty('rate', 150)
                self.tts_engine.setProperty('volume', 0.9)
                logger.info("🔄 TTS引擎已重新初始化")
            except Exception as reinit_error:
                logger.error(f"❌ TTS引擎重新初始化失败: {reinit_error}")

    def speak_alert(self, message):
        """播放语音提醒（简化版本，每次独立调用）"""
        if not message or not message.strip():
            return

        def speak_in_thread():
            try:
                logger.info(f"🔊 开始播放语音: {message}")

                # 每次都创建新的TTS引擎实例，避免状态冲突
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty('rate', 150)
                engine.setProperty('volume', 0.9)

                # 尝试设置中文语音
                try:
                    voices = engine.getProperty('voices')
                    if voices:
                        for voice in voices:
                            if any(keyword in voice.name.lower() for keyword in ['chinese', 'zh', 'mandarin']):
                                engine.setProperty('voice', voice.id)
                                break
                except:
                    pass

                # 播放语音
                engine.say(message)
                engine.runAndWait()

                # 手动清理引擎
                try:
                    engine.stop()
                    del engine
                except:
                    pass

                logger.info(f"✅ 语音播放完成: {message}")

            except Exception as e:
                logger.error(f"❌ 语音播放失败: {e}")

        # 在独立线程中播放
        thread = threading.Thread(target=speak_in_thread, daemon=True)
        thread.start()

    def start_distraction_alert(self):
        """开始循环分心警告 - 调试版本"""
        if self.is_driver_distracted:
            logger.warning("⚠️ 分心警告已在运行中，忽略重复启动")
            return

        self.is_driver_distracted = True
        self.distraction_alert_stop_event.clear()
        self.distraction_alert_count = 0

        def distraction_alert_loop():
            """分心警告循环线程"""
            try:
                logger.info("🚨 开始循环分心警告")

                while not self.distraction_alert_stop_event.is_set() and self.is_driver_distracted:
                    self.distraction_alert_count += 1

                    # 详细调试信息
                    logger.info(f"🚨 === 第 {self.distraction_alert_count} 次警告开始 ===")
                    logger.info(f"🚨 当前状态: is_driver_distracted={self.is_driver_distracted}")
                    logger.info(f"🚨 停止事件状态: {self.distraction_alert_stop_event.is_set()}")

                    # 测试简单的print输出
                    print(f"🚨 CONSOLE: 第 {self.distraction_alert_count} 次分心警告!")

                    # 调用语音
                    logger.info(f"🚨 准备调用speak_alert...")
                    self.speak_alert("请注意路况")
                    logger.info(f"🚨 speak_alert调用完成")

                    # 额外的语音测试 - 用系统自带的方式
                    try:
                        import os
                        if os.name == 'nt':  # Windows
                            logger.info("🚨 尝试Windows系统语音...")
                            os.system(
                                f'echo 请注意路况 | powershell -Command "Add-Type -AssemblyName System.Speech; $speak = New-Object System.Speech.Synthesis.SpeechSynthesizer; $speak.Speak([Console]::ReadLine())"')
                    except Exception as sys_voice_error:
                        logger.error(f"❌ 系统语音失败: {sys_voice_error}")

                    logger.info(f"🚨 === 第 {self.distraction_alert_count} 次警告完成，等待5秒 ===")

                    # 等待3秒
                    for i in range(30):
                        if self.distraction_alert_stop_event.is_set():
                            logger.info(f"🚨 在等待第{i * 0.1:.1f}秒时收到停止信号")
                            return
                        time.sleep(0.1)

                logger.info(f"🚨 分心警告循环正常结束，共播放 {self.distraction_alert_count} 次")

            except Exception as e:
                logger.error(f"❌ 分心警告循环线程错误: {e}")
                import traceback
                logger.error(f"❌ 错误详情: {traceback.format_exc()}")
            finally:
                self.is_driver_distracted = False
                logger.info("🚨 分心警告状态已重置")

        # 启动警告线程
        self.distraction_alert_thread = threading.Thread(target=distraction_alert_loop, daemon=True)
        self.distraction_alert_thread.start()
        logger.info("🚨 分心警告系统已启动")

    def stop_distraction_alert(self):
        """停止循环分心警告"""
        if not self.is_driver_distracted:
            logger.info("ℹ️ 分心警告未在运行，无需停止")
            return

        logger.info(f"🛑 开始停止分心警告... (已播放{self.distraction_alert_count}次)")

        # 设置停止标志
        self.is_driver_distracted = False
        self.distraction_alert_stop_event.set()

        # 等待警告线程结束
        if self.distraction_alert_thread and self.distraction_alert_thread.is_alive():
            logger.info("⏳ 等待分心警告线程结束...")
            self.distraction_alert_thread.join(timeout=3)
            if self.distraction_alert_thread.is_alive():
                logger.warning("⚠️ 分心警告线程未能在3秒内结束")

        logger.info(f"✅ 分心警告系统已停止，总共播放了 {self.distraction_alert_count} 次")


    def _monitor_music(self):
        """监控音乐播放状态"""
        while True:
            try:
                if self.system_state['music']['is_playing'] and not self.system_state['music']['is_paused']:
                    import pygame
                    if pygame.mixer.music.get_busy():
                        # 计算播放进度
                        current_time = time.time()
                        elapsed = current_time - self.music_start_time - self.music_paused_duration

                        # 更新进度
                        duration = self.system_state['music']['duration']
                        if duration > 0:
                            progress = min(elapsed, duration)
                            progress_percentage = (progress / duration) * 100

                            self.system_state['music']['progress'] = progress
                            self.system_state['music']['progress_percentage'] = progress_percentage
                            self.system_state['music']['current_time_str'] = self._format_time(progress)
                            self.system_state['music']['total_time_str'] = self._format_time(duration)

                            # 发送进度更新（每秒一次）
                            if hasattr(self, '_last_progress_update'):
                                if current_time - self._last_progress_update >= 1.0:
                                    self._send_progress_update()
                                    self._last_progress_update = current_time
                            else:
                                self._last_progress_update = current_time
                    else:
                        # 音乐播放完毕
                        logger.info("🎵 当前音乐播放完毕")
                        self._handle_song_ended()

                time.sleep(0.5)  # 每0.5秒检查一次

            except Exception as e:
                logger.error(f"❌ 音乐监控错误: {e}")
                time.sleep(5)

    def _handle_song_ended(self):
        """处理歌曲结束"""
        repeat_mode = self.system_state['music']['repeat_mode']

        if repeat_mode == 'single':
            # 单曲循环
            self._play_current_music()
        elif repeat_mode == 'all':
            # 列表循环
            self._next_song()
            self._play_current_music()
        elif repeat_mode == 'none':
            # 不循环，播放下一首
            if self.current_music_index < len(self.music_files) - 1:
                self._next_song()
                self._play_current_music()
            else:
                # 播放列表结束
                self.system_state['music']['is_playing'] = False
                self.system_state['music']['progress'] = 0
                self.system_state['music']['progress_percentage'] = 0
                self.system_state['music']['current_time_str'] = '0:00'
                self._send_update_to_clients("播放列表已结束")

    def _send_progress_update(self):
        """发送播放进度更新"""
        if self.socketio:
            progress_data = {
                'type': 'progress_update',
                'progress': self.system_state['music']['progress'],
                'progress_percentage': self.system_state['music']['progress_percentage'],
                'current_time_str': self.system_state['music']['current_time_str'],
                'total_time_str': self.system_state['music']['total_time_str']
            }
            self.socketio.emit('music_progress', progress_data)

    def _play_current_music(self):
        """播放当前音乐"""
        try:
            import pygame
            if not self.music_files:
                logger.warning("⚠️ 没有可播放的音乐文件")
                return False

            current_music = self.music_files[self.current_music_index]

            if not current_music['path'] or not os.path.exists(current_music['path']):
                logger.warning(f"⚠️ 音乐文件不存在: {current_music['path']}")
                # 如果是示例文件，模拟播放
                if not current_music['path']:
                    logger.info("🎵 播放示例音乐（模拟）")
                    self.music_start_time = time.time()
                    self.music_paused_duration = 0
                    self.system_state['music']['is_playing'] = True
                    self.system_state['music']['is_paused'] = False
                    self._update_current_music_info()
                    return True
                return False

            # 停止当前播放
            pygame.mixer.music.stop()

            # 加载并播放音乐
            pygame.mixer.music.load(current_music['path'])

            # 设置音量
            volume = self.system_state['music']['volume'] / 100.0
            pygame.mixer.music.set_volume(volume)

            # 开始播放
            pygame.mixer.music.play()

            # 记录播放开始时间
            self.music_start_time = time.time()
            self.music_paused_duration = 0

            # 更新状态
            self.system_state['music']['is_playing'] = True
            self.system_state['music']['is_paused'] = False
            self._update_current_music_info()

            logger.info(f"🎵 正在播放: {current_music['artist']} - {current_music['title']}")
            return True

        except Exception as e:
            logger.error(f"❌ 播放音乐失败: {e}")
            return False

    def _update_current_music_info(self):
        """更新当前音乐信息"""
        if self.music_files and 0 <= self.current_music_index < len(self.music_files):
            current_music = self.music_files[self.current_music_index]
            self.system_state['music']['title'] = current_music['title']
            self.system_state['music']['artist'] = current_music['artist']
            self.system_state['music']['album'] = current_music['album']
            self.system_state['music']['file_path'] = current_music['path']
            self.system_state['music']['duration'] = current_music['duration']
            self.system_state['music']['current_index'] = self.current_music_index
            self.system_state['music']['total_time_str'] = self._format_time(current_music['duration'])
            self.system_state['music']['progress'] = 0
            self.system_state['music']['progress_percentage'] = 0
            self.system_state['music']['current_time_str'] = '0:00'

    def _pause_music(self):
        """暂停音乐"""
        try:
            import pygame
            if self.system_state['music']['is_playing'] and not self.system_state['music']['is_paused']:
                pygame.mixer.music.pause()
                self.music_pause_time = time.time()
                self.system_state['music']['is_paused'] = True
                logger.info("⏸️ 音乐已暂停")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ 暂停音乐失败: {e}")
            return False

    def _resume_music(self):
        """恢复音乐播放"""
        try:
            import pygame
            if self.system_state['music']['is_playing'] and self.system_state['music']['is_paused']:
                pygame.mixer.music.unpause()
                # 累计暂停时间
                if self.music_pause_time > 0:
                    self.music_paused_duration += time.time() - self.music_pause_time
                    self.music_pause_time = 0
                self.system_state['music']['is_paused'] = False
                logger.info("▶️ 音乐已恢复播放")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ 恢复播放失败: {e}")
            return False

    def _stop_music(self):
        """停止音乐"""
        try:
            import pygame
            pygame.mixer.music.stop()
            self.system_state['music']['is_playing'] = False
            self.system_state['music']['is_paused'] = False
            self.system_state['music']['progress'] = 0
            self.system_state['music']['progress_percentage'] = 0
            self.system_state['music']['current_time_str'] = '0:00'
            self.music_start_time = 0
            self.music_pause_time = 0
            self.music_paused_duration = 0
            logger.info("⏹️ 音乐已停止")
            return True
        except Exception as e:
            logger.error(f"❌ 停止音乐失败: {e}")
            return False

    def _set_volume(self, volume):
        """设置音量"""
        try:
            import pygame
            volume = max(0, min(100, volume))  # 限制在0-100范围内
            pygame.mixer.music.set_volume(volume / 100.0)
            self.system_state['music']['volume'] = volume
            logger.info(f"🔊 音量已设置为: {volume}%")
            return True
        except Exception as e:
            logger.error(f"❌ 设置音量失败: {e}")
            return False

    def toggle_play_pause(self):
        """切换播放/暂停状态"""
        if self.system_state['music']['is_playing']:
            if self.system_state['music']['is_paused']:
                return self._resume_music()
            else:
                return self._pause_music()
        else:
            return self._play_current_music()

    def set_repeat_mode(self, mode):
        """设置重复模式"""
        valid_modes = ['none', 'single', 'all']
        if mode in valid_modes:
            self.system_state['music']['repeat_mode'] = mode
            logger.info(f"🔄 重复模式已设置为: {mode}")
            return True
        return False

    def toggle_shuffle(self):
        """切换随机播放模式"""
        self.system_state['music']['shuffle_mode'] = not self.system_state['music']['shuffle_mode']
        logger.info(f"🔀 随机播放: {'开启' if self.system_state['music']['shuffle_mode'] else '关闭'}")
        return self.system_state['music']['shuffle_mode']

    def seek_to_position(self, position_seconds):
        """跳转到指定位置（秒）"""
        try:
            duration = self.system_state['music']['duration']
            if 0 <= position_seconds <= duration:
                # 注意：pygame.mixer.music 不支持直接跳转
                # 这里只是更新状态，实际跳转需要其他音频库
                self.system_state['music']['progress'] = position_seconds
                progress_percentage = (position_seconds / duration) * 100 if duration > 0 else 0
                self.system_state['music']['progress_percentage'] = progress_percentage
                self.system_state['music']['current_time_str'] = self._format_time(position_seconds)

                # 调整播放开始时间以匹配新位置
                if self.system_state['music']['is_playing']:
                    self.music_start_time = time.time() - position_seconds
                    self.music_paused_duration = 0

                logger.info(f"⏯️ 跳转到: {self._format_time(position_seconds)}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ 跳转失败: {e}")
            return False

    def refresh_music_library(self):
        """重新扫描音乐库"""
        logger.info("🔄 重新扫描音乐库...")
        old_count = len(self.music_files)
        self._scan_music_files()
        new_count = len(self.music_files)

        if new_count != old_count:
            logger.info(f"📚 音乐库已更新: {old_count} -> {new_count} 首")
            # 重置当前索引如果超出范围
            if self.current_music_index >= new_count and new_count > 0:
                self.current_music_index = 0
                current_music = self.music_files[0]
                self.system_state['music']['title'] = current_music['title']
                self.system_state['music']['artist'] = current_music['artist']
                self.system_state['music']['file_path'] = current_music['path']

        self.system_state['music']['total_files'] = new_count
        return new_count

    def add_command(self, command_type: str, command_text: str, source: str = "系统"):
        command = {
            'type': command_type,
            'text': command_text,
            'source': source,
            'time': datetime.now().strftime('%H:%M:%S'),
            'timestamp': time.time()
        }
        self.command_queue.put(command)
        logger.info(f"📝 收到指令: [{source}] {command_text}")

    def _process_commands(self):
        while True:
            try:
                command = self.command_queue.get(timeout=1)
                self._execute_command(command)
                self.command_history.insert(0, command)
                if len(self.command_history) > 10:
                    self.command_history.pop()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"命令处理错误: {e}")

    def _execute_command(self, command):
        """执行具体指令"""
        text = command['text'].lower()
        original_text = command['text']
        result = "未识别的指令"

        try:
            # 处理分心警告相关指令
            if command.get('type') == 'driver_distraction_start':
                logger.info(f"🚨 收到分心开始指令: {original_text}")
                self.start_distraction_alert()
                # 更新系统状态
                self.system_state['driver']['state'] = '分心'
                self.system_state['driver']['alertness'] = 'distracted'
                result = "检测到驾驶员分心，开始语音警告"
                self._send_update_to_clients(result)
                return

            elif command.get('type') == 'driver_distraction_end':
                logger.info(f"✅ 收到分心结束指令: {original_text}")
                self.stop_distraction_alert()
                # 更新系统状态
                self.system_state['driver']['state'] = '正常'
                self.system_state['driver']['alertness'] = 'normal'
                result = "驾驶员注意力恢复正常，停止语音警告"
                self._send_update_to_clients(result)
                return

            elif command.get('type') == 'voice_warning':
                logger.info(f"🔊 收到语音提醒指令: {original_text}")
                self.speak_alert(original_text)
                result = f"语音提醒: {original_text}"
                self._send_update_to_clients(result)
                return

            # 导航指令处理
            if any(keyword in text for keyword in ['导航', '前往']):
                if hasattr(self, 'navigation_module') and self.navigation_module:
                    destination = None
                    for keyword in ['导航到', '前往']:
                        if keyword in original_text:
                            parts = original_text.split(keyword, 1)
                            if len(parts) > 1:
                                destination = parts[1].strip()
                                break

                    if destination:
                        if self.navigation_module.start_navigation(destination):
                            nav_status = self.navigation_module.get_navigation_status()
                            self.system_state['navigation'] = nav_status
                            result = f"开始导航到 {destination}"
                        else:
                            result = f"无法找到地点: {destination}"
                    else:
                        result = "请说明具体的目的地"

            elif any(keyword in text for keyword in ['停止导航', '结束导航', '取消导航']):
                if hasattr(self, 'navigation_module') and self.navigation_module:
                    if self.navigation_module.stop_navigation():
                        nav_status = self.navigation_module.get_navigation_status()
                        self.system_state['navigation'] = nav_status
                        result = "导航已停止"

            # 修改后的回家导航指令处理
            elif any(keyword in text for keyword in
                     ['回家', '导航回家', '我要回家', '开车回家', '回到家', '导航到家', '带我回家', '开始回家',
                      '出发回家', '回家去']):
                if hasattr(self, 'navigation_module') and self.navigation_module:
                    # 检查是否有当前用户信息
                    if not self.current_user_id:
                        result = "用户未登录，无法获取家位置"
                        logger.error(f"❌ 用户未设置，无法回家")
                    else:
                        # 获取当前用户的家位置
                        home_location = self.get_user_home_location()

                        if home_location:
                            logger.info(f"🏠 用户家位置信息: {home_location}")

                            # 使用导航模块导航到家
                            if self.navigation_module.start_navigation_to_coordinates(
                                    home_location['latitude'],
                                    home_location['longitude'],
                                    home_location['home_name'] or "我的家"
                            ):
                                nav_status = self.navigation_module.get_navigation_status()
                                self.system_state['navigation'] = nav_status
                                result = f"开始导航回家：{home_location['home_name'] or '我的家'}"
                                logger.info(f"✅ 开始导航回家: {home_location['home_name']}")
                            else:
                                result = "无法规划回家路线"
                                logger.error(f"❌ 无法规划回家路线")
                        else:
                            result = "您还没有设置家位置，请先设置家位置"
                            logger.warning(f"⚠️ 用户未设置家位置")
                else:
                    result = "导航模块未启用，无法回家"
                    logger.error(f"❌ 导航模块未启用")

            # 修改后的设置家位置指令处理
            elif any(keyword in text for keyword in
                     ['这里是我家', '设置为我家', '这是我家', '记住这里是我家', '保存为我家']):

                logger.info(f"🏠 收到设置家位置指令: {original_text}")

                if hasattr(self, 'navigation_module') and self.navigation_module:
                    # 检查是否正在导航或有目的地信息
                    nav_status = self.navigation_module.get_navigation_status()
                    logger.info(f"🧭 当前导航状态: {nav_status}")

                    if nav_status and nav_status.get('destination'):
                        destination = nav_status['destination']
                        logger.info(f"🎯 获取到目的地信息: {destination}")

                        # 准备位置数据
                        location_data = {
                            'home_name': destination.get('name') or destination.get('address', '我的家'),
                            'latitude': destination.get('lat'),
                            'longitude': destination.get('lng')
                        }
                        logger.info(f"📍 准备保存的位置数据: {location_data}")

                        # 验证位置数据
                        if location_data['latitude'] is not None and location_data['longitude'] is not None:
                            logger.info(f"✅ 位置数据有效，发送设置请求")

                            # 通过WebSocket发送设置家位置的事件到前端
                            if self.socketio:
                                self.socketio.emit('set_home_location_request', {
                                    'location_data': location_data,
                                    'message': f"是否将 {location_data['home_name']} 设置为您的家？"
                                })
                                logger.info(f"📡 已发送家位置设置请求到前端")

                            result = f"正在为您设置家位置：{location_data['home_name']}"
                            logger.info(f"✅ 设置家位置指令处理完成: {location_data['home_name']}")
                        else:
                            result = "无法获取有效的位置信息，请确保正在导航"
                            logger.error(
                                f"❌ 位置数据无效: lat={location_data['latitude']}, lng={location_data['longitude']}")
                    else:
                        result = "请先导航到目的地，再设置为家位置"
                        logger.warning(f"⚠️ 没有目的地信息，当前导航状态: {nav_status}")
                else:
                    result = "导航模块未启用，无法设置家位置"
                    logger.error(f"❌ 导航模块未启用")

            # 音乐控制 - 使用实际播放方法
            elif any(keyword in text for keyword in ['暂停', '停止播放', '暂停音乐', '停止音乐']):
                logger.info(f"🎵 执行暂停指令: {original_text}")
                if self._pause_music():
                    result = "音乐已暂停"
                    logger.info("✅ 音乐暂停成功")
                else:
                    result = "暂停失败"
                    logger.error("❌ 音乐暂停失败")

                # 2. 再处理播放（避免"暂停音乐"被错误匹配）
            elif any(keyword in text for keyword in ['播放', '开始播放']) or text == '音乐':
                logger.info(f"🎵 执行播放指令: {original_text}")
                if self.system_state['music']['is_paused']:
                    self._resume_music()
                    result = "音乐已恢复播放"
                else:
                    if self._play_current_music():
                        current = self.system_state['music']
                        result = f"正在播放: {current['artist']} - {current['title']}"
                    else:
                        result = "播放失败"

                # 3. 处理停止
            elif any(keyword in text for keyword in ['停止', '停止音乐']) and '播放' not in text:
                self._stop_music()
                result = "音乐已停止"

                # 4. 处理下一首
            elif any(keyword in text for keyword in ['下一首', '下首', '换歌', '切歌']):
                self._next_song()
                if self.system_state['music']['is_playing']:
                    self._play_current_music()
                current = self.system_state['music']
                result = f"切换到: {current['artist']} - {current['title']}"

                # 5. 处理上一首
            elif any(keyword in text for keyword in ['上一首', '上首', '前一首']):
                self._prev_song()
                if self.system_state['music']['is_playing']:
                    self._play_current_music()
                current = self.system_state['music']
                result = f"切换到: {current['artist']} - {current['title']}"

            # 空调控制
            elif any(keyword in text for keyword in ['空调', '制冷', '制热']):
                if '开' in text:
                    self.system_state['ac']['is_on'] = True
                    result = "空调已开启"
                elif '关' in text:
                    self.system_state['ac']['is_on'] = False
                    result = "空调已关闭"

            elif any(keyword in text for keyword in ['升温', '加热', '调高']):
                old_temp = self.system_state['ac']['temperature']
                self.system_state['ac']['temperature'] = min(32, old_temp + 1)
                result = f"温度已调至 {self.system_state['ac']['temperature']}°C"

            elif any(keyword in text for keyword in ['降温', '制冷', '调低']):
                old_temp = self.system_state['ac']['temperature']
                self.system_state['ac']['temperature'] = max(16, old_temp - 1)
                result = f"温度已调至 {self.system_state['ac']['temperature']}°C"

            # 车窗和灯光控制
            elif any(keyword in text for keyword in ['开窗', '车窗']):
                if '开' in text:
                    self.system_state['windows']['front_left'] = True
                    self.system_state['windows']['front_right'] = True
                    result = "车窗已开启"
                elif '关' in text:
                    self.system_state['windows']['front_left'] = False
                    self.system_state['windows']['front_right'] = False
                    result = "车窗已关闭"

            elif any(keyword in text for keyword in ['大灯', '头灯']):
                if '开' in text:
                    self.system_state['lights']['headlights'] = True
                    result = "大灯已开启"
                elif '关' in text:
                    self.system_state['lights']['headlights'] = False
                    result = "大灯已关闭"

            # 状态更新
            elif command.get('type') == 'driver_state':
                self.system_state['driver']['state'] = command['text']
                result = f"驾驶员状态: {command['text']}"

            elif command.get('type') == 'gesture':
                self.system_state['gesture']['current'] = command['text']
                self.system_state['gesture']['last_time'] = command['time']
                result = f"检测到手势: {command['text']}"

        except Exception as e:
            logger.error(f"指令执行错误: {e}")
            result = f"执行错误: {str(e)}"

        self._send_update_to_clients(result)

    def _send_update_to_clients(self, result_message):
        try:
            if self.socketio:
                update_data = {
                    'state': self.system_state,
                    'command_history': self.command_history,
                    'result': result_message,
                    'timestamp': time.time()
                }
                self.socketio.emit('system_update', update_data)
        except Exception as e:
            logger.error(f"发送更新失败: {e}")

    def _next_song(self):
        """切换到下一首歌"""
        if not self.music_files:
            return

        self.current_music_index = (self.current_music_index + 1) % len(self.music_files)
        self._update_current_music_info()

    def _prev_song(self):
        """切换到上一首歌"""
        if not self.music_files:
            return

        self.current_music_index = (self.current_music_index - 1) % len(self.music_files)
        self._update_current_music_info()

    def get_system_state(self):
        return {
            'state': self.system_state,
            'command_history': self.command_history,
            'timestamp': time.time()
        }


# ============== Flask应用初始化 ==============
app = Flask(__name__)
app.config.update(
    SECRET_KEY=secrets.token_urlsafe(32),
    SQLALCHEMY_DATABASE_URI='sqlite:///car_system.db',
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_PERMANENT=False,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=False,
)

# 初始化扩展
db.init_app(app)
init_auth(app)
#login_manager = LoginManager()
#login_manager.init_app(app)
#login_manager.login_view = 'login'
#login_manager.login_message_category = 'info'

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 初始化系统
system_monitor = SystemMonitor()
car_system = CarSystem(socketio)

# 语音、视觉、导航识别实例
voice_recognition = None
vision_recognition = None
navigation_module = None


#@login_manager.user_loader
#def load_user(user_id):
    #return User.query.get(int(user_id))


def create_default_admin():
    """创建默认管理员"""
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        logger.info('✅ 已创建默认管理员 admin / admin123')
    else:
        # 如果管理员已存在，更新密码（适用于从明文密码迁移的情况）
        admin.set_password('admin123')
        db.session.commit()
        logger.info('✅ 已更新管理员密码')


def check_column_exists(table, column):
    """检查数据库列是否存在"""
    try:
        # 使用原始SQL查询检查列是否存在
        result = db.session.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in result.fetchall()]
        return column in columns
    except Exception as e:
        logger.error(f"检查列 {column} 是否存在时出错: {e}")
        return False



# ============== 错误处理器 ==============
@app.errorhandler(401)
def handle_unauthorized(error):
    """处理未授权访问"""
    # 如果是API请求，返回JSON错误
    if request.path.startswith('/api/'):
        return jsonify({
            'status': 'error',
            'message': '需要登录',
            'code': 401
        }), 401

    # 否则重定向到登录页面
    return redirect(url_for('auth.login'))


@app.errorhandler(403)
def handle_forbidden(error):
    """处理权限不足"""
    # 如果是API请求，返回JSON错误
    if request.path.startswith('/api/'):
        return jsonify({
            'status': 'error',
            'message': '权限不足',
            'code': 403
        }), 403

    # 否则显示错误页面
    flash('权限不足', 'error')
    return redirect(url_for('index'))


@app.before_request
def check_authentication():
    """在每个请求前检查认证状态"""
    # 跳过静态文件和登录相关的路由
    if (request.endpoint and
            (request.endpoint.startswith('static') or
             request.endpoint in ['auth.login', 'auth.register','auth.passenger_register', 'auth.reset_password'])):
        return

    # 如果是API请求且用户未认证
    if request.path.startswith('/api/') and not current_user.is_authenticated:
        return jsonify({
            'status': 'error',
            'message': '需要登录',
            'code': 401
        }), 401

    # 检查管理员权限
    if (request.path.startswith('/api/admin/') and
            (not current_user.is_authenticated or not (current_user.is_admin() or current_user.is_system_admin()))):
        return jsonify({
            'status': 'error',
            'message': '需要管理员权限',
            'code': 403
        }), 403


# ============== 认证路由 ==============



# ============== 主要路由 ==============
@app.route('/')
@login_required
def index():
    """用户主页面"""
    if current_user.is_admin():
        return redirect(url_for('admin_dashboard'))

    # 更新当前用户信息到 car_system
    try:
        if current_user.is_authenticated:
            home_location = None
            if current_user.has_location():
                home_location = current_user.get_location()

            car_system.set_current_user(current_user.id, home_location)
            car_system.app_context = app.app_context()
    except Exception as e:
        logger.error(f"❌ 更新用户信息到car_system失败: {e}")

    try:
        with open('web_interface.html', 'r', encoding='utf-8') as f:
            html_content = f.read()

        return render_template_string(html_content)
    except FileNotFoundError:
        return "<h1>错误：未找到 web_interface.html 文件</h1>"


@app.route('/admin')
@login_required
def admin_dashboard():
    """管理员页面"""
    if not current_user.is_admin():
        flash('权限不足', 'error')
        return redirect(url_for('index'))

    try:
        with open('admin_interface.html', 'r', encoding='utf-8') as f:
            html_content = f.read()

        # 使用 render_template_string 来渲染模板变量
        return render_template_string(html_content)
    except FileNotFoundError:
        return "<h1>错误：未找到 admin_interface.html 文件</h1>"


@app.route('/map')
@login_required
def serve_map():
    """提供地图页面"""
    if navigation_module and navigation_module.map_html_path:
        try:
            return send_file(navigation_module.map_html_path)
        except Exception as e:
            logger.error(f"提供地图文件失败: {e}")
            return "地图文件不可用", 404
    else:
        return "地图未准备就绪", 404


# ============== API路由 ==============
def log_api_request():
    """API请求记录装饰器"""
    def decorator(f):
        def decorated_function(*args, **kwargs):
            system_monitor.log_api_request()
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    return decorator


def require_admin():
    """管理员权限验证装饰器"""
    def decorator(f):
        def decorated_function(*args, **kwargs):
            # 修改：允许 admin 和 system_admin 角色
            if not current_user.is_authenticated or not (current_user.is_admin() or current_user.is_system_admin()):
                return jsonify({'error': '需要管理员权限', 'code': 401}), 401
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    return decorator


@app.route('/api/user_info')
@login_required
@log_api_request()
def get_user_info():
    """获取当前用户信息"""
    return jsonify({
        'status': 'success',
        'user': {
            'username': current_user.username,
            'role': current_user.role,
            'is_admin': current_user.is_admin(),
            'is_authenticated': current_user.is_authenticated
        }
    })


# 5. 在相关的路由中更新用户信息到 car_system
@app.route('/api/system_state')
@login_required
@log_api_request()
def get_system_state():
    # 更新当前用户信息到 car_system
    try:
        if current_user.is_authenticated:
            home_location = None
            if current_user.has_location():
                home_location = current_user.get_location()

            car_system.set_current_user(current_user.id, home_location)

            # 设置应用上下文供后续使用
            car_system.app_context = app.app_context()
    except Exception as e:
        logger.error(f"❌ 更新用户信息到car_system失败: {e}")

    return jsonify(car_system.get_system_state())


@app.route('/api/navigation_status')
@login_required
def get_navigation_status():
    global navigation_module
    if navigation_module:
        status = navigation_module.get_navigation_status()
        return jsonify(status)
    else:
        return jsonify({
            'navigation_enabled': False,
            'is_navigating': False,
            'current_location': None,
            'destination': None,
            'map_available': False
        })


@app.route('/api/stop_navigation', methods=['POST'])
@login_required
def stop_navigation():
    global navigation_module
    try:
        if navigation_module:
            success = navigation_module.stop_navigation()
            return jsonify({
                'status': 'success' if success else 'error',
                'message': '导航已停止' if success else '停止导航失败'
            })
        else:
            return jsonify({'status': 'error', 'message': '导航模块未启用'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/voice_status')
@login_required
@log_api_request()
def get_voice_status():
    global voice_recognition
    status = {
        'voice_recognition_enabled': voice_recognition is not None,
        'is_running': False, 'is_connected': False, 'is_recording': False,
        'last_command_time': 0, 'command_cooldown': 0
    }
    if voice_recognition:
        status.update({
            'is_running': voice_recognition.is_running,
            'is_connected': voice_recognition.is_connected,
            'is_recording': voice_recognition.is_recording,
            'last_command_time': getattr(voice_recognition, 'last_command_time', 0),
            'command_cooldown': getattr(voice_recognition, 'command_cooldown', 0)
        })
    return jsonify(status)


@app.route('/api/video_status')
@login_required
@log_api_request()
def get_video_status():
    global vision_recognition
    status = {
        'vision_recognition_enabled': vision_recognition is not None,
        'is_running': False, 'has_camera': False, 'current_frame_available': False
    }
    if vision_recognition:
        status.update({
            'is_running': vision_recognition.is_running,
            'has_camera': vision_recognition.camera_cap is not None,
            'current_frame_available': vision_recognition.get_current_frame() is not None
        })
    return jsonify(status)


@app.route('/api/command', methods=['POST'])
@login_required
@log_api_request()
def execute_command():
    try:
        data = request.get_json()
        command_type = data.get('type', 'manual')
        command_text = data.get('text', '')
        source = data.get('source', 'Web界面')
        car_system.add_command(command_type, command_text, source)
        return jsonify({'status': 'success', 'message': '指令已接收'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/test_voice', methods=['POST'])
@login_required
@log_api_request()
def test_voice():
    """测试语音识别功能"""
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({
                'status': 'error',
                'message': '缺少测试文本'
            }), 400

        test_text = data['text']
        logger.info(f"🧪 收到语音测试请求: {test_text}")

        # 检查语音识别模块是否可用
        global voice_recognition
        if voice_recognition is None:
            return jsonify({
                'status': 'error',
                'message': '语音识别模块未启动'
            })

        # 检查语音识别状态
        if not voice_recognition.is_running:
            return jsonify({
                'status': 'error',
                'message': '语音识别服务未运行'
            })

        # 模拟语音指令处理
        try:
            car_system.add_command('test', test_text, '管理后台测试')
            logger.info(f"✅ 语音测试指令已发送: {test_text}")

            return jsonify({
                'status': 'success',
                'message': '语音测试成功',
                'test_text': test_text,
                'voice_status': {
                    'is_running': voice_recognition.is_running,
                    'is_connected': voice_recognition.is_connected,
                    'is_recording': voice_recognition.is_recording
                }
            })

        except Exception as e:
            logger.error(f"❌ 语音测试执行失败: {e}")
            return jsonify({
                'status': 'error',
                'message': f'语音测试执行失败: {str(e)}'
            })

    except Exception as e:
        logger.error(f"❌ 语音测试API错误: {e}")
        return jsonify({
            'status': 'error',
            'message': f'测试失败: {str(e)}'
        }), 500


@app.route('/api/voice_reset', methods=['POST'])
@login_required
@log_api_request()
def reset_voice():
    """重置语音识别"""
    try:
        global voice_recognition
        if voice_recognition is None:
            return jsonify({
                'status': 'error',
                'message': '语音识别模块未启动'
            })

        # 重置语音识别状态
        try:
            voice_recognition.reset_recognition_state()
            logger.info("🔄 语音识别状态已重置")

            return jsonify({
                'status': 'success',
                'message': '语音识别已重置'
            })

        except Exception as e:
            logger.error(f"❌ 重置语音识别失败: {e}")
            return jsonify({
                'status': 'error',
                'message': f'重置失败: {str(e)}'
            })

    except Exception as e:
        logger.error(f"❌ 语音重置API错误: {e}")
        return jsonify({
            'status': 'error',
            'message': f'重置失败: {str(e)}'
        }), 500


# ============== 管理员API ==============
@app.route('/api/admin/system_stats')
@login_required
@require_admin()
@log_api_request()
def get_system_stats():
    try:
        stats = system_monitor.get_system_stats()
        return jsonify({'status': 'success', 'data': stats})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/service_control', methods=['POST'])
@login_required
@require_admin()
@log_api_request()
def service_control():
    global voice_recognition, vision_recognition
    try:
        data = request.get_json()
        service = data.get('service')
        action = data.get('action')

        if service == 'voice':
            if action == 'start':
                if voice_recognition is None:
                    result = start_voice_recognition()
                    message = '语音服务已启动' if result else '语音服务启动失败'
                    return jsonify({'status': 'success' if result else 'error', 'message': message})
                else:
                    return jsonify({'status': 'warning', 'message': '语音服务已在运行'})
            elif action == 'stop':
                if voice_recognition:
                    voice_recognition.stop()
                    voice_recognition = None
                    return jsonify({'status': 'success', 'message': '语音服务已停止'})
                else:
                    return jsonify({'status': 'warning', 'message': '语音服务未运行'})

        elif service == 'vision':
            if action == 'start':
                if vision_recognition is None:
                    result = start_vision_recognition()
                    message = '视觉服务已启动' if result else '视觉服务启动失败'
                    return jsonify({'status': 'success' if result else 'error', 'message': message})
                else:
                    return jsonify({'status': 'warning', 'message': '视觉服务已在运行'})
            elif action == 'stop':
                if vision_recognition:
                    vision_recognition.stop()
                    vision_recognition = None
                    return jsonify({'status': 'success', 'message': '视觉服务已停止'})
                else:
                    return jsonify({'status': 'warning', 'message': '视觉服务未运行'})

        return jsonify({'status': 'error', 'message': '无效的服务或操作'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/system_logs')
@login_required
@require_admin()
@log_api_request()
def get_system_logs():
    try:
        log_file_path = 'car_system.log'
        logs = []

        if os.path.exists(log_file_path):
            with open(log_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                recent_lines = lines[-100:] if len(lines) > 100 else lines

                for line in recent_lines:
                    if line.strip():
                        if 'ERROR' in line:
                            level = 'error'
                        elif 'WARNING' in line:
                            level = 'warning'
                        elif 'INFO' in line:
                            level = 'info'
                        else:
                            level = 'debug'

                        logs.append({
                            'level': level,
                            'message': line.strip(),
                            'timestamp': datetime.now().isoformat()
                        })

        return jsonify({'status': 'success', 'logs': logs})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/clear_logs', methods=['POST'])
@login_required
@require_admin()
@log_api_request()
def clear_logs():
    """清空日志文件"""
    try:
        log_file_path = 'car_system.log'
        if os.path.exists(log_file_path):
            with open(log_file_path, 'w', encoding='utf-8') as f:
                f.write('')
            logger.info('📝 系统日志已清空')
            return jsonify({'status': 'success', 'message': '日志已清空'})
        else:
            return jsonify({'status': 'warning', 'message': '日志文件不存在'})
    except Exception as e:
        logger.error(f"❌ 清空日志失败: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/system_test', methods=['POST'])
@login_required
@require_admin()
@log_api_request()
def run_system_test():
    try:
        data = request.get_json()
        test_type = data.get('test_type', 'full')
        test_results = {}

        # 测试语音识别
        if test_type in ['full', 'voice']:
            try:
                voice_status = get_voice_status().get_json()
                test_results['voice'] = {
                    'status': 'pass' if voice_status.get('voice_recognition_enabled') else 'fail',
                    'message': '语音识别服务正常' if voice_status.get(
                        'voice_recognition_enabled') else '语音识别服务未启用',
                    'details': voice_status
                }
            except Exception as e:
                test_results['voice'] = {
                    'status': 'fail',
                    'message': f'语音识别测试失败: {str(e)}'
                }

        # 测试视觉识别
        if test_type in ['full', 'vision']:
            try:
                vision_status = get_video_status().get_json()
                test_results['vision'] = {
                    'status': 'pass' if vision_status.get('vision_recognition_enabled') else 'fail',
                    'message': '视觉识别服务正常' if vision_status.get(
                        'vision_recognition_enabled') else '视觉识别服务未启用',
                    'details': vision_status
                }
            except Exception as e:
                test_results['vision'] = {
                    'status': 'fail',
                    'message': f'视觉识别测试失败: {str(e)}'
                }

        return jsonify({
            'status': 'success',
            'test_results': test_results,
            'summary': f'{test_type} 测试完成'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ============== WebSocket事件 ==============
@socketio.on('connect')
def handle_connect():
    logger.info(f"🔗 客户端连接成功: {request.sid}")
    system_monitor.websocket_connections += 1
    current_state = car_system.get_system_state()
    emit('system_update', current_state)
    emit('test_message', {
        'message': '连接成功',
        'timestamp': time.time(),
        'client_id': request.sid
    })


@socketio.on('disconnect')
def handle_disconnect():
    logger.info(f"🔌 客户端断开连接: {request.sid}")
    system_monitor.websocket_connections = max(0, system_monitor.websocket_connections - 1)


@socketio.on('manual_command')
def handle_manual_command(data):
    logger.info(f"📝 收到手动指令: {data}")
    command_type = data.get('type', 'manual')
    command_text = data.get('text', '')
    if command_text:
        car_system.add_command(command_type, command_text, "手动操作")


# ============== 数据库管理页面路由 ==============
@app.route('/database')
@login_required
def database_management():
    """数据库管理页面 - 专门为adminsystem用户设计"""
    if not (current_user.is_admin() or current_user.is_system_admin()):
        flash('权限不足，需要管理员权限', 'error')
        return redirect(url_for('index'))

    try:
        # 专用欢迎页面
        html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>数据库管理 - 车载系统</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            color: #ffffff;
            min-height: 100vh;
        }}

        .db-container {{
            min-height: 100vh;
        }}

        .db-header {{
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            padding: 15px 25px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 100;
        }}

        .db-title {{
            font-size: 24px;
            font-weight: 700;
            background: linear-gradient(45deg, #00d4ff, #5b86e5);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .db-nav {{
            display: flex;
            gap: 15px;
        }}

        .nav-btn {{
            padding: 8px 16px;
            background: rgba(0, 212, 255, 0.2);
            border: 1px solid rgba(0, 212, 255, 0.3);
            border-radius: 8px;
            color: #00d4ff;
            text-decoration: none;
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 14px;
        }}

        .nav-btn:hover {{
            background: rgba(0, 212, 255, 0.3);
            transform: translateY(-1px);
        }}

        .nav-btn.danger {{
            background: rgba(255, 107, 107, 0.2);
            border-color: rgba(255, 107, 107, 0.3);
            color: #ff6b6b;
        }}

        .nav-btn.danger:hover {{
            background: rgba(255, 107, 107, 0.3);
        }}

        .welcome-card {{
            margin: 25px;
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border-radius: 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 40px;
            text-align: center;
        }}

        .welcome-title {{
            font-size: 28px;
            margin-bottom: 20px;
            background: linear-gradient(45deg, #00d4ff, #5b86e5);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .welcome-text {{
            font-size: 16px;
            color: rgba(255, 255, 255, 0.8);
            margin-bottom: 30px;
            line-height: 1.6;
        }}

        .action-buttons {{
            display: flex;
            gap: 20px;
            justify-content: center;
            flex-wrap: wrap;
        }}

        .action-btn {{
            padding: 15px 30px;
            background: linear-gradient(135deg, #00d4ff, #5b86e5);
            border: none;
            border-radius: 12px;
            color: white;
            text-decoration: none;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            display: inline-block;
        }}

        .action-btn:hover {{
            transform: translateY(-3px);
            box-shadow: 0 10px 30px rgba(0, 212, 255, 0.4);
        }}

        .action-btn.secondary {{
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0.05));
            border: 1px solid rgba(255, 255, 255, 0.2);
        }}

        .stats-preview {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 40px;
        }}

        .stat-card {{
            background: rgba(255, 255, 255, 0.08);
            border-radius: 15px;
            padding: 20px;
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}

        .stat-number {{
            font-size: 32px;
            font-weight: 700;
            color: #00d4ff;
            margin-bottom: 8px;
        }}

        .stat-label {{
            font-size: 14px;
            color: rgba(255, 255, 255, 0.7);
        }}

        .user-info-card {{
            background: rgba(0, 255, 136, 0.1);
            border: 1px solid rgba(0, 255, 136, 0.3);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 30px;
        }}

        .user-info-title {{
            color: #00ff88;
            font-size: 18px;
            margin-bottom: 10px;
        }}

        @media (max-width: 768px) {{
            .welcome-card {{
                margin: 15px;
                padding: 30px 20px;
            }}

            .action-buttons {{
                flex-direction: column;
                align-items: center;
            }}

            .action-btn {{
                width: 100%;
                max-width: 300px;
            }}
        }}
    </style>
</head>
<body>
    <div class="db-container">
        <header class="db-header">
            <div class="db-title">🗄️ 数据库管理控制台</div>
            <div class="db-nav">
                <a href="/admin" class="nav-btn">🔧 管理后台</a>
                <a href="/" class="nav-btn">🚗 用户界面</a>
                <a href="{url_for('auth.logout')}" class="nav-btn danger">退出登录</a>
            </div>
        </header>

        <div class="welcome-card">
            <div class="user-info-card">
                <div class="user-info-title">👋 欢迎，数据库管理员</div>
                <div>当前登录用户：{current_user.username} ({current_user.role})</div>
                <div>登录时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
            </div>

            <div class="welcome-title">🎯 车载系统数据库管理中心</div>
            <div class="welcome-text">
                您已使用专用管理账户登录，可以执行以下数据库管理操作：<br>
                • 用户管理：查看、添加、编辑、删除系统用户<br>
                • 权限控制：修改用户角色和权限等级<br>
                • 注册码管理：生成、查看、删除注册码<br>
                • 数据统计：查看系统用户和注册码统计信息
            </div>

            <div class="action-buttons">
                <button class="action-btn" onclick="window.location.href='/database_full'">
                    🗄️ 进入数据库管理
                </button>
                <button class="action-btn secondary" onclick="window.location.href='/admin'">
                    🔧 系统监控后台
                </button>
            </div>

            <div class="stats-preview" id="statsPreview">
                <div class="stat-card">
                    <div class="stat-number" id="totalUsers">...</div>
                    <div class="stat-label">总用户数</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number" id="adminUsers">...</div>
                    <div class="stat-label">管理员</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number" id="totalCodes">...</div>
                    <div class="stat-label">注册码总数</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number" id="unusedCodes">...</div>
                    <div class="stat-label">未使用注册码</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // 加载统计数据
        async function loadStats() {{
            try {{
                // 加载用户统计
                const usersResponse = await fetch('/api/database/users');
                if (usersResponse.ok) {{
                    const usersData = await usersResponse.json();
                    if (usersData.status === 'success') {{
                        const users = usersData.users;
                        document.getElementById('totalUsers').textContent = users.length;
                        document.getElementById('adminUsers').textContent = 
                            users.filter(u => u.role === 'admin' || u.role === 'system_admin').length;
                    }}
                }}

                // 加载注册码统计
                const codesResponse = await fetch('/api/database/codes');
                if (codesResponse.ok) {{
                    const codesData = await codesResponse.json();
                    if (codesData.status === 'success') {{
                        const codes = codesData.codes;
                        document.getElementById('totalCodes').textContent = codes.length;
                        document.getElementById('unusedCodes').textContent = 
                            codes.filter(c => !c.is_used).length;
                    }}
                }}
            }} catch (error) {{
                console.error('加载统计数据失败:', error);
            }}
        }}

        // 页面加载时获取统计数据
        document.addEventListener('DOMContentLoaded', loadStats);
    </script>
</body>
</html>'''
        return html_content
    except Exception as e:
        logger.error(f"加载数据库管理页面失败: {e}")
        return f"<h1>错误：加载数据库管理页面失败 - {str(e)}</h1>"


@app.route('/database_full')
@login_required
def database_full():
    """完整的数据库管理界面"""
    if not (current_user.is_admin() or current_user.is_system_admin()):
        flash('权限不足，需要管理员权限', 'error')
        return redirect(url_for('index'))

    # 返回完整的数据库管理页面
    try:
        # 尝试从文件读取，如果文件不存在则显示提示
        try:
            with open('database_management.html', 'r', encoding='utf-8') as f:
                html_content = f.read()
            return render_template_string(html_content)
        except FileNotFoundError:
            return render_template_string('''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>数据库管理 - 车载系统</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            color: white;
            text-align: center;
            padding: 50px;
        }}
        .error-container {{
            background: rgba(255, 107, 107, 0.1);
            border: 1px solid rgba(255, 107, 107, 0.3);
            border-radius: 15px;
            padding: 40px;
            max-width: 600px;
            margin: 0 auto;
        }}
        .error-title {{
            font-size: 24px;
            color: #ff6b6b;
            margin-bottom: 20px;
        }}
        .help-text {{
            margin-top: 30px;
            padding: 20px;
            background: rgba(0, 212, 255, 0.1);
            border-radius: 10px;
        }}
        .nav-btn {{
            display: inline-block;
            margin: 10px;
            padding: 10px 20px;
            background: rgba(0, 212, 255, 0.3);
            color: #00d4ff;
            text-decoration: none;
            border-radius: 8px;
        }}
    </style>
</head>
<body>
    <div class="error-container">
        <div class="error-title">⚠️ 数据库管理页面文件缺失</div>
        <p>请确保将 <code>database_management.html</code> 文件保存到项目根目录。</p>

        <div class="help-text">
            <strong>解决步骤：</strong><br>
            1. 将提供的 database_management.html 文件保存到项目根目录<br>
            2. 重启应用程序<br>
            3. 重新访问此页面
        </div>

        <div>
            <a href="/database" class="nav-btn">🔙 返回管理首页</a>
            <a href="/admin" class="nav-btn">🔧 管理后台</a>
            <a href="{url_for('auth.logout')}" class="nav-btn">🚪 退出登录</a>
        </div>
    </div>
</body>
</html>''')
    except Exception as e:
        logger.error(f"加载数据库管理页面失败: {e}")
        return f"<h1>错误：{str(e)}</h1>"


# ============== 数据库管理API路由 ==============



@app.route('/api/database/codes', methods=['GET'])
@login_required
@require_admin()
@log_api_request()
def get_all_codes():
    """获取所有注册码"""
    try:
        codes = RegistrationCode.query.all()
        codes_data = []
        for code in codes:
            codes_data.append({
                'id': code.id,
                'code': code.code,
                'is_used': code.is_used
            })

        return jsonify({
            'status': 'success',
            'codes': codes_data
        })
    except Exception as e:
        logger.error(f"获取注册码列表失败: {e}")
        return jsonify({
            'status': 'error',
            'message': f'获取注册码列表失败: {str(e)}'
        }), 500


@app.route('/api/database/codes', methods=['POST'])
@login_required
@require_admin()
@log_api_request()
def generate_codes():
    """生成注册码"""
    try:
        data = request.get_json()
        count = data.get('count', 1)
        length = data.get('length', 16)

        # 验证输入
        if not isinstance(count, int) or count <= 0 or count > 100:
            return jsonify({
                'status': 'error',
                'message': '生成数量必须是1-100之间的整数'
            }), 400

        if length not in [8, 16, 32]:
            return jsonify({
                'status': 'error',
                'message': '注册码长度只能是8、16或32位'
            }), 400

        # 生成注册码
        generated_codes = []
        for i in range(count):
            # 生成随机注册码
            characters = string.ascii_letters + string.digits
            code = ''.join(secrets.choice(characters) for _ in range(length))

            # 确保注册码唯一
            while RegistrationCode.query.filter_by(code=code).first():
                code = ''.join(secrets.choice(characters) for _ in range(length))

            new_code = RegistrationCode(code=code, is_used=False)
            db.session.add(new_code)
            generated_codes.append(code)

        db.session.commit()

        logger.info(f"管理员 {current_user.username} 生成了 {count} 个注册码")

        return jsonify({
            'status': 'success',
            'message': f'成功生成 {count} 个注册码',
            'codes': generated_codes
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"生成注册码失败: {e}")
        return jsonify({
            'status': 'error',
            'message': f'生成注册码失败: {str(e)}'
        }), 500


@app.route('/api/database/codes/<int:code_id>', methods=['DELETE'])
@login_required
@require_admin()
@log_api_request()
def delete_code(code_id):
    """删除注册码"""
    try:
        code = RegistrationCode.query.get(code_id)
        if not code:
            return jsonify({
                'status': 'error',
                'message': '注册码不存在'
            }), 404

        code_str = code.code
        db.session.delete(code)
        db.session.commit()

        logger.info(f"管理员 {current_user.username} 删除了注册码: {code_str}")

        return jsonify({
            'status': 'success',
            'message': f'注册码 {code_str} 删除成功'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"删除注册码失败: {e}")
        return jsonify({
            'status': 'error',
            'message': f'删除注册码失败: {str(e)}'
        }), 500


# ============== 数据库管理API路由 - 修改版本 ==============

@app.route('/api/database/users', methods=['GET'])
@login_required
@require_admin()
@log_api_request()
def get_all_users():
    """获取所有用户"""
    try:
        users = User.query.all()
        users_data = []
        for user in users:
            user_dict = {
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'reg_code': user.reg_code,
                'longitude': user.longitude,
                'latitude': user.latitude,
                'home_name': user.home_name,
                'has_location': user.has_location(),
                'coordinates': f"{user.latitude:.6f}, {user.longitude:.6f}" if user.has_location() else None
            }
            users_data.append(user_dict)

        return jsonify({
            'status': 'success',
            'users': users_data
        })
    except Exception as e:
        logger.error(f"获取用户列表失败: {e}")
        return jsonify({
            'status': 'error',
            'message': f'获取用户列表失败: {str(e)}'
        }), 500


@app.route('/api/database/users', methods=['POST'])
@login_required
@require_admin()
@log_api_request()
def add_user():
    """添加用户"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        role = data.get('role', 'user')
        reg_code = data.get('reg_code', '').strip() or None

        # 新增位置信息字段
        longitude = data.get('longitude')
        latitude = data.get('latitude')
        home_name = data.get('home_name', '').strip() or None

        # 验证输入
        if not username or not password:
            return jsonify({
                'status': 'error',
                'message': '用户名和密码不能为空'
            }), 400

        if role not in ['user', 'passenger', 'admin', 'system_admin']:
            return jsonify({
                'status': 'error',
                'message': '无效的用户角色'
            }), 400

        # 验证位置信息
        if longitude is not None or latitude is not None:
            try:
                if longitude is not None:
                    longitude = float(longitude)
                    if not (-180 <= longitude <= 180):
                        return jsonify({
                            'status': 'error',
                            'message': '经度必须在-180到180之间'
                        }), 400

                if latitude is not None:
                    latitude = float(latitude)
                    if not (-90 <= latitude <= 90):
                        return jsonify({
                            'status': 'error',
                            'message': '纬度必须在-90到90之间'
                        }), 400

                # 如果设置了其中一个坐标，另一个也必须设置
                if (longitude is None) != (latitude is None):
                    return jsonify({
                        'status': 'error',
                        'message': '经度和纬度必须同时设置或同时为空'
                    }), 400

            except (ValueError, TypeError):
                return jsonify({
                    'status': 'error',
                    'message': '经度和纬度必须是有效的数字'
                }), 400

        # 检查用户名是否已存在
        if User.query.filter_by(username=username).first():
            return jsonify({
                'status': 'error',
                'message': '用户名已存在'
            }), 400

        # 验证注册码（非乘客角色需要注册码）
        if role != 'passenger':
            if not reg_code:
                return jsonify({
                    'status': 'error',
                    'message': '非乘客角色需要提供注册码'
                }), 400

            # 检查注册码是否有效
            code_row = RegistrationCode.query.filter_by(code=reg_code, is_used=False).first()
            if not code_row:
                return jsonify({
                    'status': 'error',
                    'message': '注册码无效或已被使用'
                }), 400

            # 标记注册码为已使用
            code_row.mark_used()

        # 创建用户
        new_user = User(
            username=username,
            role=role,
            reg_code=reg_code,
            longitude=longitude,
            latitude=latitude,
            home_name=home_name
        )
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        logger.info(f"管理员 {current_user.username} 添加了新用户: {username} (角色: {role})")

        location_info = ""
        if new_user.has_location():
            location_info = f", 位置: {home_name or '未命名'} ({latitude:.6f}, {longitude:.6f})"

        return jsonify({
            'status': 'success',
            'message': f'用户 {username} 添加成功{location_info}'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"添加用户失败: {e}")
        return jsonify({
            'status': 'error',
            'message': f'添加用户失败: {str(e)}'
        }), 500


@app.route('/api/database/users/<int:user_id>', methods=['PUT'])
@login_required
@require_admin()
@log_api_request()
def update_user(user_id):
    """更新用户信息"""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({
                'status': 'error',
                'message': '用户不存在'
            }), 404

        data = request.get_json()

        # 修复：安全处理可能为 None 的字段
        username = data.get('username') or ''
        username = username.strip() if username else ''

        password = data.get('password') or ''
        password = password.strip() if password else ''

        role = data.get('role', user.role)

        reg_code = data.get('reg_code') or ''
        reg_code = reg_code.strip() if reg_code else None

        # 新增位置信息字段
        longitude = data.get('longitude')
        latitude = data.get('latitude')

        home_name = data.get('home_name') or ''
        home_name = home_name.strip() if home_name else None

        # 验证输入
        if not username:
            return jsonify({
                'status': 'error',
                'message': '用户名不能为空'
            }), 400

        if role not in ['user', 'passenger', 'admin', 'system_admin']:
            return jsonify({
                'status': 'error',
                'message': '无效的用户角色'
            }), 400

        # 验证位置信息
        if longitude is not None or latitude is not None:
            try:
                if longitude is not None:
                    if longitude == '' or longitude == 'null':  # 处理空字符串和字符串'null'
                        longitude = None
                    else:
                        longitude = float(longitude)
                        if not (-180 <= longitude <= 180):
                            return jsonify({
                                'status': 'error',
                                'message': '经度必须在-180到180之间'
                            }), 400

                if latitude is not None:
                    if latitude == '' or latitude == 'null':  # 处理空字符串和字符串'null'
                        latitude = None
                    else:
                        latitude = float(latitude)
                        if not (-90 <= latitude <= 90):
                            return jsonify({
                                'status': 'error',
                                'message': '纬度必须在-90到90之间'
                            }), 400

                # 如果设置了其中一个坐标，另一个也必须设置（除非都是空）
                if (longitude is None) != (latitude is None):
                    return jsonify({
                        'status': 'error',
                        'message': '经度和纬度必须同时设置或同时清空'
                    }), 400

            except (ValueError, TypeError):
                return jsonify({
                    'status': 'error',
                    'message': '经度和纬度必须是有效的数字'
                }), 400

        # 检查用户名是否与其他用户冲突
        existing_user = User.query.filter_by(username=username).first()
        if existing_user and existing_user.id != user_id:
            return jsonify({
                'status': 'error',
                'message': '用户名已被其他用户使用'
            }), 400

        # 处理注册码逻辑
        if role != 'passenger' and reg_code and reg_code != user.reg_code:
            # 如果角色不是乘客且提供了新的注册码
            code_row = RegistrationCode.query.filter_by(code=reg_code, is_used=False).first()
            if not code_row:
                return jsonify({
                    'status': 'error',
                    'message': '注册码无效或已被使用'
                }), 400

            # 释放旧注册码（如果有的话）
            if user.reg_code:
                old_code = RegistrationCode.query.filter_by(code=user.reg_code).first()
                if old_code:
                    old_code.is_used = False

            # 标记新注册码为已使用
            code_row.mark_used()

        # 更新用户信息
        user.username = username
        if password:  # 只有提供密码时才更新
            user.set_password(password)
        user.role = role
        user.reg_code = reg_code

        # 更新位置信息
        user.longitude = longitude
        user.latitude = latitude
        user.home_name = home_name

        db.session.commit()

        logger.info(f"管理员 {current_user.username} 更新了用户: {username} (ID: {user_id})")

        location_info = ""
        if user.has_location():
            location_info = f", 位置: {home_name or '未命名'} ({latitude:.6f}, {longitude:.6f})"
        elif longitude is None and latitude is None:
            location_info = ", 位置信息已清除"

        return jsonify({
            'status': 'success',
            'message': f'用户 {username} 更新成功{location_info}'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"更新用户失败: {e}")
        return jsonify({
            'status': 'error',
            'message': f'更新用户失败: {str(e)}'
        }), 500


@app.route('/api/database/users/<int:user_id>', methods=['DELETE'])
@login_required
@require_admin()
@log_api_request()
def delete_user(user_id):
    """删除用户"""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({
                'status': 'error',
                'message': '用户不存在'
            }), 404

        # 防止删除当前登录的用户
        if user.id == current_user.id:
            return jsonify({
                'status': 'error',
                'message': '不能删除当前登录的用户'
            }), 400

        # 防止删除最后一个管理员
        if user.is_admin():
            admin_count = User.query.filter_by(role='admin').count()
            system_admin_count = User.query.filter_by(role='system_admin').count()
            if admin_count + system_admin_count <= 1:
                return jsonify({
                    'status': 'error',
                    'message': '不能删除最后一个管理员账户'
                }), 400

        username = user.username
        location_info = ""
        if user.has_location():
            location_info = f" (位置: {user.home_name or '未命名'})"

        # 释放注册码（如果有的话）
        if user.reg_code:
            code_row = RegistrationCode.query.filter_by(code=user.reg_code).first()
            if code_row:
                code_row.is_used = False

        db.session.delete(user)
        db.session.commit()

        logger.info(f"管理员 {current_user.username} 删除了用户: {username} (ID: {user_id}){location_info}")

        return jsonify({
            'status': 'success',
            'message': f'用户 {username} 删除成功'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"删除用户失败: {e}")
        return jsonify({
            'status': 'error',
            'message': f'删除用户失败: {str(e)}'
        }), 500


# 新增：批量更新用户位置信息的API
@app.route('/api/database/users/batch_location', methods=['POST'])
@login_required
@require_admin()
@log_api_request()
def batch_update_user_locations():
    """批量更新用户位置信息"""
    try:
        data = request.get_json()
        updates = data.get('updates', [])

        if not updates:
            return jsonify({
                'status': 'error',
                'message': '没有提供更新数据'
            }), 400

        success_count = 0
        error_count = 0
        errors = []

        for update in updates:
            try:
                user_id = update.get('user_id')
                longitude = update.get('longitude')
                latitude = update.get('latitude')
                home_name = update.get('home_name', '').strip() or None

                user = User.query.get(user_id)
                if not user:
                    errors.append(f"用户ID {user_id} 不存在")
                    error_count += 1
                    continue

                # 验证坐标
                if longitude is not None and latitude is not None:
                    longitude = float(longitude)
                    latitude = float(latitude)

                    if not (-180 <= longitude <= 180):
                        errors.append(f"用户 {user.username} 的经度无效")
                        error_count += 1
                        continue

                    if not (-90 <= latitude <= 90):
                        errors.append(f"用户 {user.username} 的纬度无效")
                        error_count += 1
                        continue

                # 更新位置信息
                user.longitude = longitude
                user.latitude = latitude
                user.home_name = home_name

                success_count += 1

            except Exception as e:
                errors.append(f"更新用户ID {update.get('user_id', 'unknown')} 失败: {str(e)}")
                error_count += 1

        db.session.commit()

        logger.info(f"管理员 {current_user.username} 批量更新了 {success_count} 个用户的位置信息")

        return jsonify({
            'status': 'success',
            'message': f'批量更新完成: 成功 {success_count} 个，失败 {error_count} 个',
            'success_count': success_count,
            'error_count': error_count,
            'errors': errors
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"批量更新用户位置失败: {e}")
        return jsonify({
            'status': 'error',
            'message': f'批量更新失败: {str(e)}'
        }), 500


# 新增：获取用户统计信息（包含位置统计）
@app.route('/api/database/users/stats', methods=['GET'])
@login_required
@require_admin()
@log_api_request()
def get_user_stats():
    """获取用户统计信息"""
    try:
        total_users = User.query.count()
        users_with_location = User.query.filter(
            User.longitude.isnot(None),
            User.latitude.isnot(None)
        ).count()
        users_without_location = total_users - users_with_location

        # 按角色统计
        role_stats = {}
        for role in ['admin', 'system_admin', 'user', 'passenger']:
            role_stats[role] = User.query.filter_by(role=role).count()

        # 按位置状态和角色交叉统计
        location_by_role = {}
        for role in ['admin', 'system_admin', 'user', 'passenger']:
            with_location = User.query.filter(
                User.role == role,
                User.longitude.isnot(None),
                User.latitude.isnot(None)
            ).count()
            location_by_role[role] = {
                'total': role_stats[role],
                'with_location': with_location,
                'without_location': role_stats[role] - with_location
            }

        return jsonify({
            'status': 'success',
            'stats': {
                'total_users': total_users,
                'users_with_location': users_with_location,
                'users_without_location': users_without_location,
                'location_percentage': round((users_with_location / total_users * 100) if total_users > 0 else 0, 1),
                'role_stats': role_stats,
                'location_by_role': location_by_role
            }
        })

    except Exception as e:
        logger.error(f"获取用户统计失败: {e}")
        return jsonify({
            'status': 'error',
            'message': f'获取统计信息失败: {str(e)}'
        }), 500


@app.route('/api/set_home_location', methods=['POST'])
@login_required
@log_api_request()
def set_home_location():
    """设置当前用户的家位置"""
    try:
        # 从请求中获取位置数据，或从车载系统中获取
        data = request.get_json()

        # 如果请求中没有数据，尝试从车载系统获取
        if not data and hasattr(car_system, 'pending_home_location'):
            data = car_system.pending_home_location
            # 清除临时数据
            delattr(car_system, 'pending_home_location')

        if not data:
            return jsonify({
                'status': 'error',
                'message': '没有可用的位置数据'
            }), 400

        home_name = data.get('home_name', '').strip()
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        # 验证数据
        if not home_name:
            return jsonify({
                'status': 'error',
                'message': '家的名称不能为空'
            }), 400

        if latitude is None or longitude is None:
            return jsonify({
                'status': 'error',
                'message': '经纬度信息不完整'
            }), 400

        try:
            latitude = float(latitude)
            longitude = float(longitude)

            # 验证经纬度范围
            if not (-90 <= latitude <= 90):
                return jsonify({
                    'status': 'error',
                    'message': '纬度必须在-90到90之间'
                }), 400

            if not (-180 <= longitude <= 180):
                return jsonify({
                    'status': 'error',
                    'message': '经度必须在-180到180之间'
                }), 400

        except (ValueError, TypeError):
            return jsonify({
                'status': 'error',
                'message': '经纬度必须是有效的数字'
            }), 400

        # 更新当前用户的位置信息
        user = current_user
        user.home_name = home_name
        user.latitude = latitude
        user.longitude = longitude

        # 保存到数据库
        db.session.commit()

        # 更新 car_system 中的用户信息
        home_location = user.get_location()
        car_system.set_current_user(user.id, home_location)

        logger.info(f"✅ 用户 {user.username} 的家位置已更新: {home_name} ({latitude:.6f}, {longitude:.6f})")

        return jsonify({
            'status': 'success',
            'message': f'家位置已成功设置为: {home_name}',
            'data': {
                'home_name': home_name,
                'latitude': latitude,
                'longitude': longitude,
                'coordinates': f"{latitude:.6f}, {longitude:.6f}"
            }
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ 设置家位置失败: {e}")
        return jsonify({
            'status': 'error',
            'message': f'设置家位置失败: {str(e)}'
        }), 500


@app.route('/api/get_home_location', methods=['GET'])
@login_required
@log_api_request()
def get_home_location():
    """获取当前用户的家位置"""
    try:
        user = current_user

        if user.has_location():
            location_data = user.get_location()
            return jsonify({
                'status': 'success',
                'data': location_data
            })
        else:
            return jsonify({
                'status': 'success',
                'data': None,
                'message': '用户尚未设置家位置'
            })

    except Exception as e:
        logger.error(f"❌ 获取家位置失败: {e}")
        return jsonify({
            'status': 'error',
            'message': f'获取家位置失败: {str(e)}'
        }), 500


# ============== 服务启动函数 ==============
def start_navigation_module():
    global navigation_module
    try:
        logger.info("🗺️ 正在初始化导航模块...")

        def navigation_command_callback(cmd_type, cmd_text):
            try:
                car_system.add_command(cmd_type, cmd_text, "导航")
                logger.info(f"✅ 导航指令已添加到系统: {cmd_text}")
            except Exception as e:
                logger.error(f"❌ 导航回调错误: {e}")

        navigation_module = NavigationModule(navigation_command_callback)
        car_system.navigation_module = navigation_module
        nav_status = navigation_module.get_navigation_status()
        car_system.system_state['navigation'] = nav_status
        logger.info("✅ 导航模块启动成功")
        return True
    except Exception as e:
        logger.error(f"❌ 导航模块启动失败: {e}")
        return False


def start_voice_recognition():
    global voice_recognition
    try:
        logger.info("🎤 正在初始化语音识别...")

        def voice_command_callback(cmd_type, cmd_text):
            try:
                car_system.add_command(cmd_type, cmd_text, "语音")
                logger.info(f"✅ 语音指令已添加到系统: {cmd_text}")
            except Exception as e:
                logger.error(f"❌ 语音回调错误: {e}")

        voice_recognition = VoiceRecognition(voice_command_callback)

        if not voice_recognition.test_audio_device():
            logger.warning("⚠️ 音频设备测试失败，但将继续尝试启动")

        def voice_thread_function():
            try:
                voice_recognition.start_continuous_recognition()
            except Exception as e:
                logger.error(f"❌ 语音识别线程错误: {e}")

        voice_thread = threading.Thread(target=voice_thread_function, daemon=True)
        voice_thread.start()
        time.sleep(2)
        logger.info("✅ 语音识别线程已启动")
        return True
    except Exception as e:
        logger.error(f"❌ 语音识别启动失败: {e}")
        return False


def start_vision_recognition():
    global vision_recognition
    try:
        logger.info("📹 正在初始化视觉识别...")

        def vision_command_callback(cmd_type, cmd_text):
            try:
                car_system.add_command(cmd_type, cmd_text, "视觉")
                logger.info(f"✅ 视觉指令已添加到系统: {cmd_text}")
            except Exception as e:
                logger.error(f"❌ 视觉回调错误: {e}")

        vision_recognition = VisionRecognition(vision_command_callback)

        if not vision_recognition.test_camera():
            logger.warning("⚠️ 摄像头测试失败，但将继续尝试启动")

        def vision_thread_function():
            try:
                vision_recognition.start_camera_recognition()
            except Exception as e:
                logger.error(f"❌ 视觉识别线程错误: {e}")

        vision_thread = threading.Thread(target=vision_thread_function, daemon=True)
        vision_thread.start()
        logger.info("✅ 视觉识别线程已启动")
        return True
    except Exception as e:
        logger.error(f"❌ 视觉识别启动失败: {e}")
        return False





# ============== 主函数 ==============
def main():
    logger.info("🚗 车载多模态交互系统启动中...")
    logger.info("=" * 50)

    # 创建数据库表和升级数据库结构
    with app.app_context():
        try:
            # 首先创建基本表结构
            db.create_all()
            logger.info("✅ 数据库表结构已创建")

            # 最后创建默认管理员
            create_default_admin()

            # 创建测试用户
            if not User.query.filter_by(username='user').first():
                test_user = User(username='user', role='user')
                test_user.set_password('user123')
                db.session.add(test_user)
                db.session.commit()
                logger.info('✅ 已创建测试用户 user / user123')

        except Exception as e:
            logger.error(f"❌ 数据库初始化失败: {e}")
            logger.info("请检查数据库文件权限或手动运行迁移脚本")
            return

    # 启动导航模块
    if start_navigation_module():
        logger.info("✅ 导航模块已启动")
    else:
        logger.warning("⚠️ 导航模块启动失败，将继续运行其他功能")

    # 启动语音识别
    if start_voice_recognition():
        logger.info("✅ 语音识别模块已启动")
    else:
        logger.warning("⚠️ 语音识别模块启动失败，将继续运行其他功能")

    # 启动视觉识别
    if start_vision_recognition():
        logger.info("✅ 视觉识别模块已启动")
    else:
        logger.warning("⚠️ 视觉识别模块启动失败，将继续运行其他功能")

    logger.info("=" * 50)
    logger.info("🌐 Web服务器启动中...")
    logger.info("📱 系统登录: http://localhost:5000/login")
    logger.info("👤 用户界面: http://localhost:5000/ (登录后)")
    logger.info("🔧 管理界面: http://localhost:5000/admin (管理员登录后)")
    logger.info("🗺️ 地图页面: http://localhost:5000/map")
    logger.info("⚡ 按 Ctrl+C 退出系统")
    logger.info("=" * 50)

    try:
        socketio.run(app,
                     host='0.0.0.0',
                     port=5000,
                     debug=False,
                     use_reloader=False,
                     allow_unsafe_werkzeug=True,
                     log_output=False)
    except KeyboardInterrupt:
        logger.info("\n👋 系统正在关闭...")

        # 清理资源
        if voice_recognition:
            voice_recognition.stop()
        if vision_recognition:
            vision_recognition.stop()
        if navigation_module:
            navigation_module.cleanup()

        try:
            if hasattr(car_system, 'tts_engine') and car_system.tts_engine:
                car_system.tts_engine.stop()
                car_system.tts_engine = None
        except Exception as e:
            logger.error(f"❌ 清理语音提醒系统失败: {e}")

        logger.info("✅ 系统已安全关闭")


if __name__ == "__main__":
    main()