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

        # 简单语音提醒系统初始化
        self.tts_engine = None
        self.tts_lock = threading.Lock()
        self._init_simple_tts()

        logger.info("🚗 车载智能系统已初始化")

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

            logger.info("✅ 简单语音提醒系统初始化成功")
        except Exception as e:
            logger.error(f"❌ 语音提醒系统初始化失败: {e}")
            self.tts_engine = None

    def speak_alert(self, message):
        """播放语音提醒（异步）"""
        if not self.tts_engine or not message:
            return

        def _speak():
            try:
                with self.tts_lock:
                    logger.info(f"🔊 播放语音提醒: {message}")
                    self.tts_engine.say(message)
                    self.tts_engine.runAndWait()
                    logger.info(f"✅ 语音提醒播放完成")
            except Exception as e:
                logger.error(f"❌ 语音提醒播放失败: {e}")

        # 在单独线程中播放，避免阻塞主程序
        thread = threading.Thread(target=_speak, daemon=True)
        thread.start()


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
            if command.get('type') == 'voice_warning':
                logger.info(f"🔊 收到语音提醒指令: {original_text}")
                self.speak_alert(original_text)
                result = f"语音提醒: {original_text}"
                self._send_update_to_clients(result)
                return
            # 导航指令处理
            if any(keyword in text for keyword in ['导航', '去', '到', '前往']):
                if hasattr(self, 'navigation_module') and self.navigation_module:
                    destination = None
                    for keyword in ['导航到', '去', '到', '前往']:
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


@app.route('/api/system_state')
@login_required
@log_api_request()
def get_system_state():
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
            users_data.append({
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'reg_code': user.reg_code
            })

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
        new_user = User(username=username, role=role, reg_code=reg_code)
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        logger.info(f"管理员 {current_user.username} 添加了新用户: {username} (角色: {role})")

        return jsonify({
            'status': 'success',
            'message': f'用户 {username} 添加成功'
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
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        role = data.get('role', user.role)
        reg_code = data.get('reg_code', '').strip() or None

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

        db.session.commit()

        logger.info(f"管理员 {current_user.username} 更新了用户: {username} (ID: {user_id})")

        return jsonify({
            'status': 'success',
            'message': f'用户 {username} 更新成功'
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

        # 释放注册码（如果有的话）
        if user.reg_code:
            code_row = RegistrationCode.query.filter_by(code=user.reg_code).first()
            if code_row:
                code_row.is_used = False

        db.session.delete(user)
        db.session.commit()

        logger.info(f"管理员 {current_user.username} 删除了用户: {username} (ID: {user_id})")

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

    # 创建数据库表
    with app.app_context():
        db.create_all()
        create_default_admin()

        # 创建测试用户
        if not User.query.filter_by(username='user').first():
            test_user = User(username='user', role='user')
            test_user.set_password('user123')
            db.session.add(test_user)
            db.session.commit()
            logger.info('✅ 已创建测试用户 user / user123')

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