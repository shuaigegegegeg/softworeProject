import os
import cv2
import time
import tempfile
from openai import OpenAI
from PIL import Image
import base64
import threading
from typing import Optional, Callable


class VisionRecognition:
    def __init__(self, command_callback: Callable[[str, str], None]):
        """
        初始化视觉识别模块

        Args:
            command_callback: 回调函数，参数为(command_type, command_text)
        """
        self.command_callback = command_callback

        # API配置
        self.client = OpenAI(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key="b220fba9-e27b-4e7c-bf61-5bc0ff995b70"
        )

        # 识别控制
        self.is_running = False
        self.analysis_interval = 3  # 分析间隔（秒）

        # 状态记录 - 简化版
        self.current_state = "正常"  # 只有"正常"和"分心"两种状态
        self.eyes_closed_count = 0  # 连续闭眼帧数
        self.last_gesture = "无"
        self.last_gesture_time = 0
        self.gesture_cooldown = 3  # 手势冷却时间（秒）

        # 当前帧缓存
        self.current_frame = None
        self.frame_lock = threading.Lock()
        self.camera_cap = None

        # 手势指令映射 - 简化版
        self.gesture_commands = {
            '张开手掌': '播放音乐',
            '握拳': '暂停音乐',
            '大拇指向上': '升温',
            '大拇指向下': '降温'
        }

        print("📹 简化版视觉识别模块已初始化")

    def get_current_frame(self):
        """获取当前摄像头帧"""
        with self.frame_lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
            return None

    def create_driver_analysis_prompt(self) -> str:
        """创建驾驶员状态分析提示词 - 简化版"""
        return """请分析图片中驾驶员的状态，只判断是否分心：

**分心判断标准：**
1. 头部明显向下低着（超过30度）
2. 头部明显向上仰着（超过30度）  
3. 双眼完全闭合

**正常判断标准：**
1. 头部保持正常前视姿势
2. 眼睛睁开

请用以下格式回答：
状态：[正常/分心]
原因：简要说明判断依据

只回答这两项，不要其他内容。"""

    def create_gesture_prompt(self) -> str:
        """创建手势识别提示词 - 简化版"""
        return """请识别图片中的手势，只识别以下4种：

1. **张开手掌**：五指伸直分开，手掌展开
2. **握拳**：五指紧握成拳头
3. **大拇指向上**：拇指竖起指向上方
4. **大拇指向下**：拇指指向下方

请用以下格式回答：
手势：[张开手掌/握拳/大拇指向上/大拇指向下/无]

如果不是上述4种手势，请回答"无"。"""

    def analyze_image(self, image_path: str, analysis_type: str) -> Optional[str]:
        """分析图像"""
        try:
            with open(image_path, "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode('utf-8')

            if analysis_type == "driver":
                prompt = self.create_driver_analysis_prompt()
            elif analysis_type == "gesture":
                prompt = self.create_gesture_prompt()
            else:
                return None

            response = self.client.chat.completions.create(
                model="doubao-1.5-vision-pro-250328",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{encoded_image}"
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                max_tokens=300
            )

            return response.choices[0].message.content

        except Exception as e:
            print(f"❌ 视觉分析错误: {e}")
            return None

    def parse_driver_state(self, analysis_result: str) -> Optional[str]:
        """解析驾驶员状态 - 简化版"""
        if not analysis_result:
            return None

        analysis_lower = analysis_result.lower()

        # 检查是否提到分心的关键词
        distraction_keywords = ['分心', '低头', '仰头', '闭眼', '闭合']
        if any(keyword in analysis_lower for keyword in distraction_keywords):
            return "分心"

        # 检查是否明确说正常
        if '正常' in analysis_lower:
            return "正常"

        # 尝试从格式化输出中提取
        if '状态：' in analysis_result:
            try:
                for line in analysis_result.split('\n'):
                    if '状态：' in line:
                        state = line.split('状态：')[1].strip()
                        if '分心' in state:
                            return "分心"
                        elif '正常' in state:
                            return "正常"
            except:
                pass

        return "正常"  # 默认返回正常

    def parse_gesture(self, analysis_result: str) -> Optional[str]:
        """解析手势 - 简化版"""
        if not analysis_result:
            return "无"

        analysis_lower = analysis_result.lower()

        # 直接检查关键词
        if '张开手掌' in analysis_lower or '手掌张开' in analysis_lower:
            return '张开手掌'
        elif '握拳' in analysis_lower or '拳头' in analysis_lower:
            return '握拳'
        elif '拇指向上' in analysis_lower or '大拇指向上' in analysis_lower:
            return '大拇指向上'
        elif '拇指向下' in analysis_lower or '大拇指向下' in analysis_lower:
            return '大拇指向下'

        # 尝试从格式化输出中提取
        if '手势：' in analysis_result:
            try:
                for line in analysis_result.split('\n'):
                    if '手势：' in line:
                        gesture = line.split('手势：')[1].strip()
                        for cmd_gesture in self.gesture_commands.keys():
                            if cmd_gesture in gesture:
                                return cmd_gesture
            except:
                pass

        return "无"

    def process_driver_state(self, state: str):
        """处理驾驶员状态 - 简化版"""
        if state != self.current_state:
            print(f"📊 驾驶员状态: {self.current_state} -> {state}")
            self.current_state = state

            # 发送状态更新
            try:
                self.command_callback('driver_state', state)
            except Exception as e:
                print(f"❌ 状态回调错误: {e}")

            # 分心时发送语音提醒
            if state == "分心":
                print("⚠️ 检测到驾驶员分心，发送语音提醒")
                try:
                    self.command_callback('voice_warning', '请集中精神注意路况')
                except Exception as e:
                    print(f"❌ 语音提醒回调错误: {e}")

    def process_gesture(self, gesture: str):
        """处理手势 - 简化版"""
        current_time = time.time()

        # 手势去重和冷却
        if gesture == self.last_gesture or gesture == "无":
            return

        if current_time - self.last_gesture_time < self.gesture_cooldown:
            print(f"⏱️ 手势冷却中，忽略: {gesture}")
            return

        print(f"👋 识别到手势: {gesture}")
        self.last_gesture = gesture
        self.last_gesture_time = current_time

        # 发送手势状态更新
        try:
            self.command_callback('gesture', gesture)
        except Exception as e:
            print(f"❌ 手势状态回调错误: {e}")

        # 执行手势指令
        if gesture in self.gesture_commands:
            command = self.gesture_commands[gesture]
            print(f"✅ 执行手势指令: {gesture} -> {command}")

            try:
                # 发送指令（使用voice类型，这样main.py能正确处理）
                self.command_callback('voice', command)
                print(f"📤 手势指令已发送: {command}")
            except Exception as e:
                print(f"❌ 手势指令回调错误: {e}")

    def analyze_camera_frame(self, frame):
        """分析摄像头帧 - 简化版"""
        try:
            # 转换为PIL格式
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb_frame)

            # 保存为临时文件
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                temp_path = f.name
                pil_img.save(temp_path, quality=85)

            # 分析驾驶员状态
            driver_analysis = self.analyze_image(temp_path, "driver")
            if driver_analysis:
                driver_state = self.parse_driver_state(driver_analysis)
                if driver_state:
                    # 处理连续闭眼检测
                    if '闭眼' in driver_analysis.lower() or '闭合' in driver_analysis.lower():
                        self.eyes_closed_count += 1
                        print(f"👁️ 检测到闭眼，连续次数: {self.eyes_closed_count}")
                        if self.eyes_closed_count >= 2:  # 连续两次闭眼
                            print("⚠️ 连续闭眼超过2次，判定为分心")
                            driver_state = "分心"
                            self.eyes_closed_count = 0  # 重置
                    else:
                        self.eyes_closed_count = 0  # 重置闭眼计数

                    self.process_driver_state(driver_state)

            # 分析手势
            gesture_analysis = self.analyze_image(temp_path, "gesture")
            if gesture_analysis:
                gesture = self.parse_gesture(gesture_analysis)
                if gesture:
                    self.process_gesture(gesture)

            # 删除临时文件
            os.unlink(temp_path)

        except Exception as e:
            print(f"❌ 帧分析错误: {e}")

    def start_camera_recognition(self, camera_index: int = 0):
        """开始摄像头识别"""
        print(f"📹 启动摄像头视觉识别...")
        self.is_running = True

        while self.is_running:
            try:
                self.camera_cap = cv2.VideoCapture(camera_index)
                if not self.camera_cap.isOpened():
                    print(f"❌ 无法打开摄像头 {camera_index}")
                    time.sleep(5)
                    continue

                print(f"✅ 摄像头 {camera_index} 已启动")
                self.camera_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.camera_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

                last_analysis_time = 0
                frame_count = 0

                while self.is_running:
                    ret, frame = self.camera_cap.read()
                    if not ret:
                        print("❌ 无法读取摄像头帧")
                        break

                    frame_count += 1
                    current_time = time.time()

                    # 更新当前帧
                    with self.frame_lock:
                        self.current_frame = frame.copy()

                    # 按间隔分析帧
                    if current_time - last_analysis_time >= self.analysis_interval:
                        print(f"🔍 分析第 {frame_count} 帧...")
                        # 在单独线程中分析
                        analysis_thread = threading.Thread(
                            target=self.analyze_camera_frame,
                            args=(frame.copy(),),
                            daemon=True
                        )
                        analysis_thread.start()
                        last_analysis_time = current_time

                    time.sleep(0.066)  # 约15fps

            except Exception as e:
                print(f"❌ 摄像头运行错误: {e}")
                time.sleep(5)
            finally:
                if self.camera_cap:
                    self.camera_cap.release()
                    self.camera_cap = None

    def test_camera(self, camera_index: int = 0) -> bool:
        """测试摄像头"""
        try:
            cap = cv2.VideoCapture(camera_index)
            if not cap.isOpened():
                print(f"❌ 无法打开摄像头 {camera_index}")
                return False
            ret, frame = cap.read()
            cap.release()
            if ret:
                print(f"✅ 摄像头 {camera_index} 测试成功")
                return True
            else:
                print(f"❌ 摄像头 {camera_index} 无法读取帧")
                return False
        except Exception as e:
            print(f"❌ 摄像头测试错误: {e}")
            return False

    def stop(self):
        """停止视觉识别"""
        print("🛑 停止视觉识别...")
        self.is_running = False
        if self.camera_cap:
            self.camera_cap.release()
            self.camera_cap = None
        with self.frame_lock:
            self.current_frame = None
        print("✅ 视觉识别已停止")


# 测试函数
def test_simple_vision():
    """测试简化版视觉识别"""

    def command_callback(cmd_type, cmd_text):
        print(f"收到指令: [{cmd_type}] {cmd_text}")

    vision = VisionRecognition(command_callback)

    if not vision.test_camera():
        print("摄像头测试失败，退出")
        return

    try:
        print("开始简化版视觉识别测试，按 Ctrl+C 停止")
        vision.start_camera_recognition()
    except KeyboardInterrupt:
        print("用户中断测试")
    finally:
        vision.stop()


if __name__ == "__main__":
    test_simple_vision()