import asyncio
import websockets
import json
import struct
import gzip
import wave
import pyaudio
import threading
import time
import uuid
import os
import queue
import re
from typing import Optional, Dict, Any, Callable


# 语音输出模块
class VoiceResponse:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式，确保只有一个语音输出实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(VoiceResponse, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化语音输出模块"""
        if hasattr(self, '_initialized'):
            return

        self.engine = None
        self.is_initialized = False
        self.speak_queue = queue.Queue()
        self.speak_thread = None
        self.should_stop = False
        self._current_speaking = False
        self._initialized = True

        # 启动语音输出工作线程
        self._start_speak_worker()

    def _start_speak_worker(self):
        """启动语音输出工作线程"""
        if self.speak_thread and self.speak_thread.is_alive():
            return

        self.should_stop = False
        self.speak_thread = threading.Thread(target=self._speak_worker, daemon=True)
        self.speak_thread.start()

    def _speak_worker(self):
        """语音输出工作线程"""
        while not self.should_stop:
            try:
                # 获取语音任务，超时1秒
                text = self.speak_queue.get(timeout=1.0)
                if text is None:  # 停止信号
                    break

                self._speak_text(text)
                self.speak_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ 语音输出工作线程错误: {e}")

    def _initialize_engine(self):
        """初始化语音引擎"""
        if self.is_initialized and self.engine:
            return True

        try:
            import pyttsx3

            # 先清理旧引擎
            if self.engine:
                try:
                    self.engine.stop()
                except:
                    pass

            # 创建新引擎
            self.engine = pyttsx3.init(driverName='sapi5' if os.name == 'nt' else None)

            # 设置语音参数
            self.engine.setProperty('rate', 150)  # 语速
            self.engine.setProperty('volume', 0.8)  # 音量

            # 尝试设置中文语音
            try:
                voices = self.engine.getProperty('voices')
                if voices:
                    for voice in voices:
                        if ('chinese' in voice.name.lower() or
                                'zh' in voice.id.lower() or
                                'mandarin' in voice.name.lower()):
                            self.engine.setProperty('voice', voice.id)
                            break
            except:
                pass  # 如果设置语音失败，使用默认语音

            self.is_initialized = True
            print("✅ 语音输出模块初始化成功")
            return True

        except ImportError:
            print("❌ 缺少pyttsx3库，请运行: pip install pyttsx3")
            return False
        except Exception as e:
            print(f"❌ 语音输出模块初始化失败: {e}")
            return False

    def _speak_text(self, text: str):
        """实际执行语音输出"""
        try:
            self._current_speaking = True

            # 初始化引擎
            if not self._initialize_engine():
                print(f"语音输出失败，引擎未初始化: {text}")
                return

            print(f"🔊 语音输出: {text}")

            # 使用引擎输出语音
            self.engine.say(text)
            self.engine.runAndWait()

        except Exception as e:
            print(f"❌ 语音输出错误: {e}")
            # 尝试重新初始化引擎
            self.is_initialized = False
            self.engine = None
        finally:
            self._current_speaking = False

    def speak(self, text: str):
        """语音输出文本（异步）"""
        if not text or not text.strip():
            return

        try:
            # 将语音任务放入队列
            self.speak_queue.put(text)

            # 确保工作线程在运行
            if not self.speak_thread or not self.speak_thread.is_alive():
                self._start_speak_worker()

        except Exception as e:
            print(f"❌ 语音输出失败: {e}")

    def is_busy(self):
        """检查是否正在语音输出"""
        return self._current_speaking or not self.speak_queue.empty()

    def stop_all(self):
        """停止所有语音输出"""
        try:
            # 清空队列
            while not self.speak_queue.empty():
                try:
                    self.speak_queue.get_nowait()
                except queue.Empty:
                    break

            # 停止工作线程
            self.should_stop = True
            self.speak_queue.put(None)  # 发送停止信号

            # 停止引擎
            if self.engine:
                try:
                    self.engine.stop()
                except:
                    pass

        except Exception as e:
            print(f"停止语音输出时出错: {e}")

    def cleanup(self):
        """清理资源"""
        self.stop_all()

        if self.speak_thread and self.speak_thread.is_alive():
            self.speak_thread.join(timeout=2)

        if self.engine:
            try:
                self.engine.stop()
            except:
                pass

        self.is_initialized = False


class VoiceRecognition:
    def __init__(self, command_callback: Callable[[str, str], None]):
        """
        初始化语音识别模块

        Args:
            command_callback: 回调函数，参数为(command_type, command_text)
        """
        self.command_callback = command_callback

        # 添加语音输出模块
        self.voice_response = VoiceResponse()

        # API配置 - 使用原始代码中的配置
        self.app_key = "2596648890"
        self.access_key = "TQec02tHPei4vRw8QffUs_i_bTfHR1_e"
        self.resource_id = "volc.bigasr.sauc.duration"

        # 音频参数
        self.sample_rate = 16000
        self.channels = 1
        self.chunk_size = 3200

        # 连接状态
        self.reset_connection()

        # 识别控制
        self.is_running = False
        self.is_recording = False
        self.audio_queue = queue.Queue()

        # 去重和冷却机制
        self.last_recognized_text = ""
        self.last_command_time = 0
        self.command_cooldown = 3  # 指令冷却时间（秒）
        self.max_text_length = 50  # 最大文本长度

        # 新增：指令重启机制
        self.restart_after_command = True  # 是否在识别到指令后重启
        self.restart_delay = 2  # 重启前等待时间（秒）
        self.restart_event = threading.Event()  # 重启事件
        self.command_detected = threading.Event()  # 指令检测事件

        # 新增：导航指令延迟处理机制
        self.navigation_waiting = False  # 是否正在等待导航目的地
        self.navigation_wait_start = 0  # 开始等待的时间
        self.navigation_wait_duration = 3  # 等待持续时间（秒）
        self.navigation_partial_text = ""  # 部分导航文本
        self.navigation_collected_texts = []  # 收集的文本片段
        self.navigation_timer = None  # 导航等待计时器

        # 新增：连续无匹配指令计数器
        self.no_match_count = 0  # 连续无匹配指令的计数
        self.max_no_match_count = 20  # 最大连续无匹配次数
        self.no_match_restart_enabled = True  # 是否启用无匹配重启功能
        self.last_no_match_time = 0  # 最后一次无匹配的时间
        self.no_match_time_window = 30  # 无匹配计数的时间窗口（秒）

        # 修复后的指令模式定义 - 增加更多匹配表达和导航相关指令
        self.command_patterns = {
            # 导航控制 - 修复模式匹配（关键：分离导航触发词和完整导航指令）
            'navigation_trigger': [
                r'导航到?', r'导航', r'出发去?', r'我要去', r'前往',
                r'开始导航', r'去', r'到', r'路线到?', r'开车去',
                r'带我去', r'指路到?', r'怎么去'
            ],
            'navigation_complete': [
                r'导航到(.+)', r'出发去(.+)', r'我要去(.+)', r'前往(.+)',
                r'开始导航到(.+)',
                r'导航(.+)', r'路线到(.+)', r'开车去(.+)',
                r'带我去(.+)', r'指路到(.+)', r'怎么去(.+)'
            ],
            'navigation_stop': [r'停止导航', r'结束导航', r'取消导航', r'关闭导航'],

            # 新增：回家导航指令
            'navigation_home': [
                r'回家', r'导航回家', r'我要回家', r'开车回家', r'回到家',
                r'导航到家', r'带我回家', r'开始回家', r'出发回家', r'回家去'
            ],

            # 新增：设置家位置指令
            'set_home_location': [
                r'这里是我家', r'设置为我家', r'这是我家', r'记住这里是我家',
                r'保存为我家', r'这就是我家', r'设为家', r'记为我家',
                r'保存这个位置为我家', r'将这里设为我家'
            ],

            # 音乐控制
            'music_play': [r'播放音乐', r'开始播放', r'开始音乐', r'打开音乐'],
            'music_pause': [r'暂停音乐', r'暂停播放', r'暂停', r'停止音乐', r'停止播放'],
            'music_next': [r'下一首', r'下首歌', r'换歌', r'下一个', r'下一曲'],
            'music_prev': [r'上一首', r'上首歌', r'前一首', r'上一个', r'上一曲'],

            # 空调控制
            'ac_on': [r'开空调', r'打开空调', r'开启空调'],
            'ac_off': [r'关空调', r'关闭空调', r'停止空调'],
            # 修复：增加更多温度调节的表达方式
            'temp_up': [r'升温', r'调高温度', r'温度调高', r'加热', r'提高温度', r'增加温度', r'调高一点', r'热一点'],
            'temp_down': [r'降温', r'调低温度', r'温度调低', r'制冷', r'降低温度', r'减少温度', r'调低一点', r'凉一点'],

            # 车窗控制
            'window_open': [r'开窗', r'开车窗', r'打开车窗', r'打开窗户'],
            'window_close': [r'关窗', r'关车窗', r'关闭车窗', r'关闭窗户'],

            # 灯光控制
            'light_on': [r'开灯', r'打开大灯', r'开大灯', r'开启头灯'],
            'light_off': [r'关灯', r'关闭大灯', r'关大灯', r'关闭头灯'],
            'interior_on': [r'开室内灯', r'打开车内灯', r'开车内灯'],
            'interior_off': [r'关室内灯', r'关闭车内灯', r'关车内灯']
        }

        # 指令对应的语音回应文本
        self.command_responses = {
            'navigation_trigger': ('正在为您启动导航', '导航已启动'),
            'navigation_complete': ('正在为您规划路线', '路线规划完成'),
            'navigation_stop': ('正在为您停止导航', '导航已停止'),
            'navigation_home': ('正在为您导航回家', '回家路线规划完成'),
            'set_home_location': ('正在为您设置家位置', '家位置设置完成'),
            'music_play': ('正在为您播放音乐', '音乐播放已开始'),
            'music_pause': ('正在为您暂停音乐', '音乐已暂停'),
            'music_next': ('正在为您切换下一首', '已切换到下一首'),
            'music_prev': ('正在为您切换上一首', '已切换到上一首'),
            'ac_on': ('正在为您开启空调', '空调已开启'),
            'ac_off': ('正在为您关闭空调', '空调已关闭'),
            'temp_up': ('正在为您调高温度', '温度已调高'),
            'temp_down': ('正在为您调低温度', '温度已调低'),
            'window_open': ('正在为您开启车窗', '车窗已开启'),
            'window_close': ('正在为您关闭车窗', '车窗已关闭'),
            'light_on': ('正在为您开启大灯', '大灯已开启'),
            'light_off': ('正在为您关闭大灯', '大灯已关闭'),
            'interior_on': ('正在为您开启室内灯', '室内灯已开启'),
            'interior_off': ('正在为您关闭室内灯', '室内灯已关闭')
        }

        print("🎤 语音识别模块已初始化")

    def get_command_response(self, command_type: str):
        """获取指令对应的语音回应"""
        return self.command_responses.get(command_type, ('正在为您执行指令', '指令已完成'))

    def speak_command_start(self, command_type: str):
        """指令开始时的语音回应"""
        start_response, _ = self.get_command_response(command_type)
        self.voice_response.speak(start_response)

    def speak_command_complete(self, command_type: str):
        """指令完成时的语音回应"""
        _, complete_response = self.get_command_response(command_type)

        # 使用更可靠的延迟机制
        def delayed_response():
            try:
                # 等待指令执行完成
                time.sleep(1.5)

                # 检查系统是否还在运行
                if self.is_running:
                    self.voice_response.speak(complete_response)
                else:
                    print(f"⚠️ 系统已停止，跳过语音回应: {complete_response}")

            except Exception as e:
                print(f"❌ 延迟语音回应错误: {e}")

        # 使用守护线程，避免阻塞重启过程
        thread = threading.Thread(target=delayed_response, daemon=True)
        thread.start()

    def reset_recognition_state(self):
        """重置语音识别状态"""
        print("🔄 重置语音识别状态...")

        # 清空音频队列
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        # 重置事件
        self.command_detected.clear()
        self.restart_event.clear()

        # 重置文本记录
        self.last_recognized_text = ""

        # 重置导航等待状态
        self.reset_navigation_waiting()

        # 重置无匹配计数器
        self.reset_no_match_counter()

        print("✅ 语音识别状态已重置")

    def reset_navigation_waiting(self):
        """重置导航等待状态"""
        print("🧭 重置导航等待状态")
        self.navigation_waiting = False
        self.navigation_wait_start = 0
        self.navigation_partial_text = ""
        self.navigation_collected_texts = []

        # 取消导航计时器
        if self.navigation_timer:
            self.navigation_timer.cancel()
            self.navigation_timer = None

    def reset_no_match_counter(self):
        """重置无匹配计数器"""
        print("🔄 重置无匹配指令计数器")
        self.no_match_count = 0
        self.last_no_match_time = 0

    def handle_no_match_command(self, text: str):
        """处理无匹配指令的情况"""
        current_time = time.time()

        # 检查是否在时间窗口内
        if self.last_no_match_time > 0 and (current_time - self.last_no_match_time) > self.no_match_time_window:
            print(f"⏰ 超过时间窗口({self.no_match_time_window}秒)，重置无匹配计数器")
            self.reset_no_match_counter()

        # 增加计数
        self.no_match_count += 1
        self.last_no_match_time = current_time

        print(f"❌ 无匹配指令({self.no_match_count}/{self.max_no_match_count}): '{text}'")

        # 检查是否需要重启
        if self.no_match_restart_enabled and self.no_match_count >= self.max_no_match_count:
            print(f"🔄 连续{self.max_no_match_count}次无匹配指令，触发语音识别重启")
            #self.voice_response.speak("语音识别将重新启动以提高识别准确性")

            # 触发重启
            self.command_detected.set()

            # 重置计数器
            self.reset_no_match_counter()

            return True  # 表示已触发重启

        # 如果还没达到重启条件，给出语音提示
        # if self.no_match_count == 1:
        #     self.voice_response.speak("未识别到有效指令，请重新说明")
        # elif self.no_match_count == 2:
        #     self.voice_response.speak("仍未识别到指令，请说得更清楚一些")

        return False  # 表示未触发重启

    def start_navigation_waiting(self, initial_text):
        """开始导航等待模式"""
        print(f"🧭 开始导航等待模式，初始文本: '{initial_text}'")

        self.navigation_waiting = True
        self.navigation_wait_start = time.time()
        self.navigation_partial_text = initial_text
        self.navigation_collected_texts = [initial_text]

        # 设置计时器，在等待时间结束后处理导航指令
        self.navigation_timer = threading.Timer(
            self.navigation_wait_duration,
            self.process_navigation_command
        )
        self.navigation_timer.start()

        print(f"⏱️ 将在{self.navigation_wait_duration}秒后处理导航指令")

    def process_navigation_command(self):
        """处理收集到的导航指令"""
        print("🧭 开始处理收集到的导航指令...")

        if not self.navigation_waiting:
            print("⚠️ 导航等待状态已结束，跳过处理")
            return

        # 合并所有收集到的文本
        combined_text = " ".join(self.navigation_collected_texts).strip()
        print(f"🔗 合并的完整文本: '{combined_text}'")

        # 清理合并的文本
        clean_text = self.clean_and_normalize_text(combined_text)
        print(f"🧹 清理后的文本: '{clean_text}'")

        # 解析导航指令
        navigation_command = self.parse_navigation_command(clean_text)

        if navigation_command:
            command_type, command_text = navigation_command
            print(f"✅ 解析出导航指令: {command_type} - '{command_text}'")

            # 更新去重记录
            self.last_recognized_text = clean_text
            self.last_command_time = time.time()

            # 重置无匹配计数器（因为找到了匹配的指令）
            self.reset_no_match_counter()

            # 语音回应：指令开始执行
            self.speak_command_start(command_type)

            # 执行回调
            try:
                self.command_callback('voice', command_text)
                print(f"✅ 导航指令回调成功: '{command_text}'")

                # 语音回应：指令执行完成
                self.speak_command_complete(command_type)

                # 导航指令处理完成后触发重启
                self.command_detected.set()

            except Exception as e:
                print(f"❌ 导航指令回调错误: {e}")
                self.voice_response.speak("导航指令执行出现错误")
        else:
            print(f"❌ 无法解析导航指令: '{clean_text}'")
            # 导航指令解析失败也计入无匹配
            self.handle_no_match_command(clean_text)
            self.voice_response.speak("无法识别目的地，请重新说明")

        # 重置导航等待状态
        self.reset_navigation_waiting()

    def parse_navigation_command(self, text):
        """专门解析导航指令"""
        if not text or not text.strip():
            return None

        text = text.strip()
        print(f"🧭 解析导航指令文本: '{text}'")

        # 检查完整的导航指令模式
        for pattern in self.command_patterns['navigation_complete']:
            try:
                match = re.search(pattern, text)
                if match:
                    print(f"✅ 匹配到导航模式: '{pattern}'")

                    destination = None
                    if match.groups():
                        destination = match.group(1).strip()
                        print(f"🎯 通过捕获组提取目的地: '{destination}'")

                    if destination and len(destination) > 0:
                        # 清理目的地文本
                        for suffix in ['了', '吧', '呢', '啊', '。', '，']:
                            if destination.endswith(suffix):
                                destination = destination[:-1].strip()

                        command_text = f"导航到{destination}"
                        print(f"🧭 构建导航指令: '{command_text}'")
                        return ('navigation_complete', command_text)

            except re.error as e:
                print(f"❌ 正则表达式错误: {pattern} - {e}")
                continue

        # 如果没有匹配到完整模式，尝试提取关键词后的内容
        nav_keywords = ['导航到', '导航', '去', '到', '前往', '我要去', '出发去']
        for keyword in nav_keywords:
            if keyword in text:
                parts = text.split(keyword, 1)
                if len(parts) > 1:
                    destination = parts[1].strip()
                    if destination:
                        # 清理目的地
                        for suffix in ['了', '吧', '呢', '啊', '。', '，']:
                            if destination.endswith(suffix):
                                destination = destination[:-1].strip()

                        if destination:
                            command_text = f"导航到{destination}"
                            print(f"🧭 通过关键词'{keyword}'构建导航指令: '{command_text}'")
                            return ('navigation_complete', command_text)

        print(f"❌ 无法提取有效的导航目的地")
        return None

    def reset_connection(self):
        """重置连接状态"""
        self.connect_id = str(uuid.uuid4())
        self.websocket = None
        self.is_connected = False
        self.loop = None
        self.loop_thread = None

    def create_headers(self) -> Dict[str, str]:
        """创建WebSocket连接头"""
        return {
            "X-Api-App-Key": self.app_key,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": self.connect_id
        }

    def create_protocol_header(self, message_type: int, flags: int = 0,
                               serialization: int = 1, compression: int = 1) -> bytes:
        """创建协议头"""
        byte0 = (0b0001 << 4) | 0b0001
        byte1 = (message_type << 4) | flags
        byte2 = (serialization << 4) | compression
        byte3 = 0x00
        return struct.pack('>BBBB', byte0, byte1, byte2, byte3)

    def create_full_client_request(self) -> bytes:
        """创建完整客户端请求"""
        request_data = {
            "user": {
                "uid": "car_system_client",
                "platform": "CarSystem"
            },
            "audio": {
                "format": "pcm",
                "codec": "raw",
                "rate": self.sample_rate,
                "bits": 16,
                "channel": self.channels
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": False,
                "show_utterances": True,
                "result_type": "full"
            }
        }

        json_data = json.dumps(request_data, ensure_ascii=False).encode('utf-8')
        compressed_data = gzip.compress(json_data)

        header = self.create_protocol_header(
            message_type=1,
            flags=0,
            serialization=1,
            compression=1
        )

        payload_size = struct.pack('>I', len(compressed_data))
        return header + payload_size + compressed_data

    def create_audio_request(self, audio_data: bytes, is_last: bool = False) -> bytes:
        """创建音频请求"""
        compressed_data = gzip.compress(audio_data)
        flags = 0b0010 if is_last else 0b0000
        header = self.create_protocol_header(
            message_type=2,
            flags=flags,
            serialization=0,
            compression=1
        )

        payload_size = struct.pack('>I', len(compressed_data))
        return header + payload_size + compressed_data

    def parse_server_response(self, data) -> Optional[Dict[str, Any]]:
        """解析服务器响应"""
        try:
            if isinstance(data, str):
                try:
                    return json.loads(data)
                except:
                    data = data.encode('utf-8')

            if not isinstance(data, bytes) or len(data) < 12:
                return None

            header = data[:4]
            sequence = struct.unpack('>I', data[4:8])[0]
            payload_size = struct.unpack('>I', data[8:12])[0]

            if len(data) < 12 + payload_size:
                return None

            payload_data = data[12:12 + payload_size]

            compression = (header[2] >> 0) & 0x0F
            if compression == 1:
                try:
                    payload_data = gzip.decompress(payload_data)
                except:
                    return None

            try:
                if isinstance(payload_data, bytes):
                    json_str = payload_data.decode('utf-8')
                else:
                    json_str = str(payload_data)

                result = json.loads(json_str)
                result['sequence'] = sequence
                return result
            except:
                return None

        except:
            return None

    def start_event_loop(self):
        """启动事件循环线程"""
        if self.loop_thread and self.loop_thread.is_alive():
            self.stop_event_loop()
            self.loop_thread.join(timeout=2)

        self.loop = None
        self.loop_thread = None

        def run_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_forever()
            except Exception as e:
                print(f"语音识别事件循环错误: {e}")
            finally:
                self.loop.close()
                self.loop = None

        self.loop_thread = threading.Thread(target=run_loop, daemon=True)
        self.loop_thread.start()

        max_wait = 50
        while self.loop is None and max_wait > 0:
            time.sleep(0.1)
            max_wait -= 1

        if self.loop is None:
            raise Exception("语音识别事件循环启动失败")

    def stop_event_loop(self):
        """停止事件循环"""
        if self.loop and not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except Exception:
                pass

        if self.loop_thread and self.loop_thread.is_alive():
            self.loop_thread.join(timeout=2)

        self.loop = None
        self.loop_thread = None

    def run_in_loop(self, coro):
        """在事件循环中运行协程"""
        if not self.loop or self.loop.is_closed():
            return None

        try:
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            return future.result(timeout=30)
        except Exception as e:
            print(f"语音识别协程执行错误: {e}")
            return None

    async def _connect_async(self) -> bool:
        """异步连接到ASR服务"""
        try:
            if self.websocket and not self.websocket.closed:
                await self.websocket.close()

            url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
            headers = self.create_headers()

            try:
                self.websocket = await websockets.connect(url, extra_headers=headers)
            except TypeError:
                try:
                    self.websocket = await websockets.connect(url, additional_headers=headers)
                except TypeError:
                    self.websocket = await websockets.connect(url)

            self.is_connected = True

            init_request = self.create_full_client_request()
            await self.websocket.send(init_request)

            try:
                response_data = await asyncio.wait_for(self.websocket.recv(), timeout=10.0)
                result = self.parse_server_response(response_data)
                if result and 'error' not in result:
                    print("✅ 语音识别服务已连接")
                    return True
                else:
                    print(f"❌ 语音识别服务错误: {result.get('error', '未知错误') if result else '无响应'}")
                    self.is_connected = False
                    return False
            except asyncio.TimeoutError:
                print("✅ 语音识别服务已连接")
                return True

        except Exception as e:
            print(f"❌ 语音识别连接失败: {e}")
            self.is_connected = False
            return False

    def connect(self) -> bool:
        """连接到ASR服务"""
        try:
            self.disconnect()
            self.reset_connection()
            self.start_event_loop()
            result = self.run_in_loop(self._connect_async())
            return result if result is not None else False
        except Exception as e:
            print(f"❌ 语音识别连接过程出错: {e}")
            self.disconnect()
            return False

    async def _disconnect_async(self):
        """异步断开连接"""
        if self.websocket and self.is_connected:
            await self.websocket.close()
            self.is_connected = False

    def disconnect(self):
        """断开连接"""
        try:
            if self.is_recording:
                self.stop_recording()

            # 重置导航等待状态
            self.reset_navigation_waiting()

            if self.loop and not self.loop.is_closed() and self.websocket:
                try:
                    self.run_in_loop(self._disconnect_async())
                except Exception:
                    pass

            self.stop_event_loop()
            self.is_connected = False
            self.websocket = None

        except Exception as e:
            print(f"语音识别断开连接错误: {e}")

    def clean_and_normalize_text(self, text: str) -> str:
        """清理和标准化文本"""
        if not text:
            return ""

        # 去除多余的标点符号和空格
        text = re.sub(r'[。，、；：！？\s]+', ' ', text)
        text = text.strip()

        # 去除重复的部分（如"到吾悦广场 导航到吾悦广场"变成"导航到吾悦广场"）
        # 找到重复的片段并保留更完整的一个
        words = text.split()
        if len(words) > 1:
            # 检查是否有重复的关键词组合
            for i in range(len(words) - 1):
                for j in range(i + 2, len(words) + 1):
                    phrase1 = ' '.join(words[i:j])
                    # 在剩余部分中查找是否有包含这个短语的更长短语
                    remaining = ' '.join(words[j:])
                    if phrase1 in remaining and len(remaining) > len(phrase1):
                        # 找到了更完整的版本，提取它
                        start_idx = remaining.find(phrase1)
                        # 提取包含phrase1的完整短语
                        for k in range(len(remaining), start_idx, -1):
                            candidate = remaining[start_idx:k].strip()
                            if candidate and phrase1 in candidate:
                                text = candidate
                                break
                        break

        # 限制文本长度
        if len(text) > self.max_text_length:
            text = text[:self.max_text_length]
            print(f"⚠️ 文本过长，已截断至: {text}")

        return text

    def parse_command(self, text: str) -> Optional[tuple]:
        """解析语音文本为指令 - 修复版本"""
        if not text or not text.strip():
            return None

        text = text.strip()
        print(f"🎤 解析指令文本: '{text}'")

        # 首先检查是否为导航触发词
        for pattern in self.command_patterns['navigation_trigger']:
            try:
                if re.search(pattern, text):
                    print(f"🧭 检测到导航触发词: '{pattern}' 在 '{text}' 中")
                    return ('navigation_trigger', text)
            except re.error as e:
                print(f"❌ 正则表达式错误: {pattern} - {e}")
                continue

        # 检查其他指令类型
        for command_type, patterns in self.command_patterns.items():
            if command_type in ['navigation_trigger', 'navigation_complete']:
                continue  # 跳过导航相关的，已经在上面处理

            for pattern in patterns:
                try:
                    match = re.search(pattern, text)
                    if match:
                        print(f"✅ 匹配到模式: '{pattern}' -> 类型: {command_type}")
                        return (command_type, text)

                except re.error as e:
                    print(f"❌ 正则表达式错误: {pattern} - {e}")
                    continue

        print(f"❌ 未找到匹配的指令模式")
        return None

    def is_duplicate_text(self, text: str) -> bool:
        """检查是否为重复文本"""
        current_time = time.time()

        # 在导航等待模式下，不检查重复（允许收集多段文本）
        if self.navigation_waiting:
            return False

        # 检查是否与上次识别的文本完全相同
        if text == self.last_recognized_text:
            print(f"🔄 检测到重复文本，忽略: '{text}'")
            return True

        # 检查冷却时间
        time_since_last = current_time - self.last_command_time
        if time_since_last < self.command_cooldown:
            print(f"⏰ 指令冷却中({time_since_last:.1f}s < {self.command_cooldown}s)，忽略: '{text}'")
            return True

        print(f"✅ 文本通过去重检查: '{text}' (距上次: {time_since_last:.1f}s)")
        return False

    def handle_recognition_result(self, result: Dict[str, Any]):
        """处理识别结果 - 改进版本支持导航延迟处理、语音回应和无匹配重启"""
        if 'error' in result:
            error_msg = result['error']
            print(f"❌ 语音识别错误: {error_msg}")
            return

        if 'result' in result and 'text' in result['result']:
            raw_text = result['result']['text']
            if not raw_text or not raw_text.strip():
                return

            print(f"🎤 原始识别文本: '{raw_text}'")

            # 清理和标准化文本
            clean_text = self.clean_and_normalize_text(raw_text)
            if not clean_text:
                print(f"⚠️ 文本清理后为空")
                return

            print(f"🧹 清理后文本: '{clean_text}'")

            # 导航等待模式处理
            if self.navigation_waiting:
                print(f"🧭 导航等待模式中，收集文本: '{clean_text}'")
                self.navigation_collected_texts.append(clean_text)
                return  # 在导航等待模式中，不处理其他指令

            # 检查重复
            if self.is_duplicate_text(clean_text):
                return

            # 解析为指令
            command = self.parse_command(clean_text)

            if command:
                command_type, command_text = command
                # 👉 拦截大灯指令，不进行自动语音播报
                if command_type in ('light_on', 'light_off'):
                    # 关键：在回调之前就更新去重记录
                    self.last_recognized_text = clean_text
                    self.last_command_time = time.time()
                    print(f"🔒 已记录灯光指令防重复: '{clean_text}' 时间: {self.last_command_time}")

                    # 重置无匹配计数器（因为找到了匹配的指令）
                    self.reset_no_match_counter()

                    # 调用回调函数
                    try:
                        self.command_callback(command_type, command_text)
                        print(f"✅ 灯光指令回调成功: '{command_text}'")

                        # 灯光指令处理完成后触发重启
                        if self.restart_after_command:
                            print(f"🔄 灯光指令识别成功，{self.restart_delay}秒后将重启语音识别...")
                            self.command_detected.set()  # 设置指令检测事件

                    except Exception as e:
                        print(f"❌ 灯光指令回调错误: {e}")

                    return
                print(f"✅ 识别语音指令: {command_type} - '{command_text}'")

                # 重置无匹配计数器（因为找到了匹配的指令）
                self.reset_no_match_counter()

                # 特殊处理导航触发指令
                if command_type == 'navigation_trigger':
                    print(f"🧭 检测到导航触发指令，开始等待模式")
                    # 语音回应：导航触发
                    self.speak_command_start(command_type)
                    self.start_navigation_waiting(clean_text)
                    return  # 不立即处理，等待更多输入

                # 处理其他指令
                # 关键：在回调之前就更新去重记录
                self.last_recognized_text = clean_text
                self.last_command_time = time.time()
                print(f"🔒 已记录指令防重复: '{clean_text}' 时间: {self.last_command_time}")

                # 语音回应：指令开始执行
                self.speak_command_start(command_type)

                # 调用回调函数
                try:
                    self.command_callback('voice', command_text)
                    print(f"✅ 语音指令回调成功: '{command_text}'")

                    # 语音回应：指令执行完成
                    self.speak_command_complete(command_type)

                    # 非导航指令识别成功后，触发重启机制
                    if self.restart_after_command:
                        print(f"🔄 指令识别成功，{self.restart_delay}秒后将重启语音识别...")
                        self.command_detected.set()  # 设置指令检测事件

                except Exception as e:
                    print(f"❌ 语音指令回调错误: {e}")
                    # 即使回调失败，也播放错误提示
                    self.voice_response.speak("指令执行出现错误")
            else:
                # 处理无匹配指令的情况
                print(f"❌ 无匹配指令: '{clean_text}'")
                restart_triggered = self.handle_no_match_command(clean_text)

                if not restart_triggered:
                    print(f"ℹ️ 继续等待有效指令...")
        else:
            print("🔇 识别结果中没有文本内容")

    async def _receive_responses_async(self):
        """异步接收服务器响应"""
        try:
            while self.is_connected and self.websocket and self.is_running:
                try:
                    response_data = await self.websocket.recv()
                    result = self.parse_server_response(response_data)
                    if result:
                        self.handle_recognition_result(result)

                    # 检查是否需要重启（但不在导航等待期间重启）
                    if self.command_detected.is_set() and not self.navigation_waiting:
                        print("🔄 检测到指令或重启信号，准备重启识别...")
                        break

                except websockets.exceptions.ConnectionClosed:
                    print("语音识别WebSocket连接已关闭")
                    self.is_connected = False
                    break
                except Exception:
                    break
        except Exception:
            pass

    async def _send_realtime_audio_async(self):
        """异步发送实时音频"""
        try:
            while self.is_recording and self.is_connected and self.is_running:
                try:
                    # 检查是否需要停止（但不在导航等待期间停止）
                    if self.command_detected.is_set() and not self.navigation_waiting:
                        print("🔄 检测到指令或重启信号，停止音频发送...")
                        break

                    audio_data = self.audio_queue.get(timeout=0.5)  # 降低超时时间以更快响应
                    if audio_data is None:
                        break

                    is_last = not self.is_recording
                    audio_request = self.create_audio_request(audio_data, is_last)
                    await self.websocket.send(audio_request)
                    await asyncio.sleep(0.05)

                except queue.Empty:
                    continue
                except Exception:
                    break

            if self.is_connected and not self.command_detected.is_set():
                try:
                    audio_request = self.create_audio_request(b'', True)
                    await self.websocket.send(audio_request)
                except Exception:
                    pass

        except Exception:
            pass

    def start_recording(self):
        """开始录音"""
        if not self.is_connected:
            print("请先连接语音识别服务")
            return False

        self.is_recording = True
        self.command_detected.clear()  # 清除指令检测事件

        # 清空音频队列
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        # 启动异步处理任务
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._receive_responses_async(), self.loop)
            asyncio.run_coroutine_threadsafe(self._send_realtime_audio_async(), self.loop)

        # 启动录音线程
        self.audio_thread = threading.Thread(target=self._record_audio, daemon=True)
        self.audio_thread.start()

        return True

    def _record_audio(self):
        """录制音频"""
        audio = pyaudio.PyAudio()

        try:
            stream = audio.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size // 2
            )

            print("🎤 语音识别录音中...")

            while self.is_recording and self.is_running:
                try:
                    # 检查是否需要停止（但不在导航等待期间停止）
                    if self.command_detected.is_set() and not self.navigation_waiting:
                        print("🔄 检测到指令或重启信号，停止录音...")
                        break

                    data = stream.read(self.chunk_size // 4, exception_on_overflow=False)
                    if len(data) > 0 and self.is_recording and self.is_running:
                        # 在导航等待期间也继续录音
                        if not (self.command_detected.is_set() and not self.navigation_waiting):
                            self.audio_queue.put(data)

                    if not self.is_recording or not self.is_running:
                        break

                except Exception:
                    break

        except Exception as e:
            print(f"❌ 语音音频设备错误: {e}")
        finally:
            if 'stream' in locals():
                stream.stop_stream()
                stream.close()
            audio.terminate()
            self.audio_queue.put(None)

    def stop_recording(self):
        """停止录音"""
        if self.is_recording:
            self.is_recording = False

            if hasattr(self, 'audio_thread') and self.audio_thread.is_alive():
                self.audio_thread.join(timeout=2)

    def restart_recognition_cycle(self):
        """重启识别周期"""
        print("🔄 开始重启识别周期...")

        # 停止当前识别
        self.stop_recording()
        self.disconnect()

        # 等待指定时间，让语音输出有时间完成
        print(f"⏱️ 等待 {self.restart_delay} 秒...")
        time.sleep(self.restart_delay)

        # 额外等待语音输出完成
        wait_count = 0
        while self.voice_response.is_busy() and wait_count < 10:
            print("🔊 等待语音输出完成...")
            time.sleep(0.5)
            wait_count += 1

        # 重置状态
        self.reset_recognition_state()

        # 重新连接和开始录音
        if self.connect():
            print("✅ 重新连接成功")
            if self.start_recording():
                print("✅ 重新开始录音")
                return True
            else:
                print("❌ 重新开始录音失败")
                return False
        else:
            print("❌ 重新连接失败")
            return False

    def start_continuous_recognition(self):
        """开始连续语音识别"""
        print("🎤 启动连续语音识别...")
        print(f"📊 无匹配重启功能: {'启用' if self.no_match_restart_enabled else '禁用'}")
        print(f"📊 连续无匹配阈值: {self.max_no_match_count}次")
        print(f"📊 无匹配时间窗口: {self.no_match_time_window}秒")

        self.is_running = True

        while self.is_running:
            try:
                # 重置识别状态
                self.reset_recognition_state()

                if not self.is_connected:
                    print("🔄 正在连接语音识别服务...")
                    if self.connect():
                        print("✅ 语音识别服务连接成功")
                        if self.start_recording():
                            print("✅ 语音录音已启动")
                        else:
                            print("❌ 语音录音启动失败")
                    else:
                        print("❌ 语音识别服务连接失败，5秒后重试...")
                        time.sleep(5)
                        continue

                # 保持运行状态，直到检测到指令或连接断开
                while self.is_running and self.is_connected:
                    # 检查是否需要重启（但不在导航等待期间重启）
                    if self.command_detected.is_set() and not self.navigation_waiting:
                        break
                    time.sleep(0.5)

                # 如果检测到指令，进行重启周期
                if self.command_detected.is_set() and self.is_running and not self.navigation_waiting:
                    print("🔄 检测到指令或重启信号，开始重启周期...")
                    if not self.restart_recognition_cycle():
                        print("❌ 重启识别周期失败，5秒后重试...")
                        time.sleep(5)
                    continue

                # 如果连接断开，尝试重连
                if self.is_running and not self.is_connected:
                    print("🔄 语音识别连接断开，准备重连...")
                    time.sleep(2)

            except KeyboardInterrupt:
                print("👋 语音识别用户中断")
                break
            except Exception as e:
                print(f"❌ 语音识别运行错误: {e}")
                time.sleep(5)

        self.stop()

    def get_status(self):
        """获取语音识别状态"""
        return {
            'is_running': self.is_running,
            'is_connected': self.is_connected,
            'is_recording': self.is_recording,
            'connect_id': getattr(self, 'connect_id', None),
            'command_detected': self.command_detected.is_set(),
            'last_command_time': self.last_command_time,
            'navigation_waiting': self.navigation_waiting,
            'navigation_collected_texts': len(self.navigation_collected_texts) if self.navigation_waiting else 0,
            'voice_response_busy': self.voice_response.is_busy(),
            'voice_queue_size': self.voice_response.speak_queue.qsize() if hasattr(self.voice_response,
                                                                                   'speak_queue') else 0,
            # 新增：无匹配重启相关状态
            'no_match_count': self.no_match_count,
            'max_no_match_count': self.max_no_match_count,
            'no_match_restart_enabled': self.no_match_restart_enabled,
            'last_no_match_time': self.last_no_match_time,
            'no_match_time_window': self.no_match_time_window
        }

    def stop(self):
        """停止语音识别"""
        print("🛑 停止语音识别...")
        self.is_running = False
        self.command_detected.set()  # 触发停止事件
        self.reset_navigation_waiting()  # 停止导航等待
        self.reset_no_match_counter()  # 重置无匹配计数器
        self.stop_recording()
        self.disconnect()

        # 停止语音输出
        try:
            self.voice_response.stop_all()
        except Exception as e:
            print(f"停止语音输出时出错: {e}")

        print("✅ 语音识别已停止")

    def test_audio_device(self):
        """测试音频设备"""
        try:
            audio = pyaudio.PyAudio()
            device_count = audio.get_device_count()

            input_devices = []
            for i in range(device_count):
                try:
                    info = audio.get_device_info_by_index(i)
                    if info['maxInputChannels'] > 0:
                        input_devices.append(i)
                except:
                    pass

            if not input_devices:
                print("❌ 没有找到可用的语音输入设备!")
                return False

            # 简单测试
            stream = audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=1600
            )

            # 测试录音
            data = stream.read(1600, exception_on_overflow=False)

            stream.stop_stream()
            stream.close()
            audio.terminate()

            print("✅ 语音设备测试成功")
            return True

        except Exception as e:
            print(f"❌ 语音设备测试失败: {e}")
            return False

    def test_voice_response(self):
        """测试语音输出功能"""
        print("🧪 测试语音输出功能...")
        self.voice_response.speak("语音输出测试成功")

        # 等待一下确保语音输出完成
        time.sleep(2)

        # 测试多个语音输出
        self.voice_response.speak("第一条测试")
        time.sleep(0.5)
        self.voice_response.speak("第二条测试")

        print("✅ 语音输出测试完成")

    def set_no_match_restart_config(self, enabled: bool = True, max_count: int = 3, time_window: int = 30):
        """配置无匹配重启功能

        Args:
            enabled: 是否启用无匹配重启功能
            max_count: 最大连续无匹配次数
            time_window: 无匹配计数的时间窗口（秒）
        """
        self.no_match_restart_enabled = enabled
        self.max_no_match_count = max_count
        self.no_match_time_window = time_window

        print(f"🔧 无匹配重启配置已更新:")
        print(f"   启用状态: {'是' if enabled else '否'}")
        print(f"   最大次数: {max_count}次")
        print(f"   时间窗口: {time_window}秒")


# 测试函数
def test_voice_recognition():
    """测试语音识别"""

    def command_callback(cmd_type, cmd_text):
        print(f"收到指令: [{cmd_type}] {cmd_text}")
        # 模拟指令执行时间
        time.sleep(1)

    voice = VoiceRecognition(command_callback)

    # 测试音频设备
    if not voice.test_audio_device():
        print("音频设备测试失败，退出")
        return

    # 测试语音输出
    voice.test_voice_response()

    # 可以自定义无匹配重启配置
    voice.set_no_match_restart_config(enabled=True, max_count=3, time_window=30)

    try:
        voice.start_continuous_recognition()
    except KeyboardInterrupt:
        print("用户中断测试")
    finally:
        voice.stop()


if __name__ == "__main__":
    test_voice_recognition()