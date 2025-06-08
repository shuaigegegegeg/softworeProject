import cv2
import time
import numpy as np
from collections import deque
import mediapipe as mp
from typing import Optional, Callable
import threading
import math


class VisionRecognition:
    """
    车载智能视觉识别模块 - 兼容main.py的集成版本
    集成功能：
    1. 手势识别 - 控制音乐、空调等
    2. 头部动作识别 - 确认/取消操作
    3. 眼部状态监控 - 驾驶员注意力检测
    """

    def __init__(self, command_callback: Optional[Callable[[str, str], None]] = None):
        self.command_callback = command_callback or self.default_callback

        # ===== 集成兼容性属性 =====
        self.is_running = False
        self.camera_cap = None
        self.current_frame = None
        self.vision_thread = None
        self.should_stop = False

        # ===== MediaPipe 初始化 =====
        self.mp_hands = mp.solutions.hands
        self.mp_face_mesh = mp.solutions.face_mesh
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_drawing_styles = mp.solutions.drawing_styles

        # 手部检测器
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5
        )

        # 面部检测器
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5
        )

        # ===== 手势识别参数 =====
        self.finger_threshold = 0.02
        self.gesture_stability_frames = 5
        self.gesture_history = deque(maxlen=self.gesture_stability_frames)
        self.current_gesture = "None"

        # ===== 头部动作识别参数 =====
        self.head_movement_threshold = 0.1
        self.nod_threshold = 0.1
        self.head_action_frames = 10
        self.head_movement_history = deque(maxlen=20)
        self.head_action_history = deque(maxlen=self.head_action_frames)
        self.current_head_action = "None"

        # ===== 眼部状态监控参数 =====
        self.eye_aspect_ratio_threshold = 0.25
        self.eye_closed_frames_threshold = 60
        self.consecutive_closed_frames = 0
        self.eyes_status = "Open"
        self.driver_attention_status = "Normal"
        self.ear_history = deque(maxlen=10)

        # ===== 指令控制参数 =====
        self.command_cooldown = 2.0
        self.last_command_time = 0
        self.last_head_command_time = 0
        self.last_attention_alert_time = 0

        # ===== 系统状态 =====
        self.frame_count = 0

        # ===== 指令映射配置 =====
        self.gesture_commands = {
            'Open Palm': '播放音乐',
            'Fist': '暂停音乐',
            'Index Up': '升温',
            'Two Fingers Up': '降温'
        }

        self.head_action_commands = {
            'Nod': '确认操作',
            'Shake': '取消操作'
        }

        # ===== 面部关键点索引 =====
        self.face_landmarks_indices = {
            'nose_tip': 1,
            'left_eye': {
                'outer_corner': 33,
                'inner_corner': 133,
                'top_1': 159,
                'top_2': 158,
                'bottom_1': 145,
                'bottom_2': 153
            },
            'right_eye': {
                'outer_corner': 362,
                'inner_corner': 263,
                'top_1': 386,
                'top_2': 385,
                'bottom_1': 374,
                'bottom_2': 380
            }
        }

        print("🎯 车载智能视觉识别系统已初始化")

    def default_callback(self, cmd_type: str, cmd_text: str):
        """默认回调函数"""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] 🎯 {cmd_type}: {cmd_text}")

    def get_current_frame(self):
        """获取当前帧 - 兼容接口"""
        return self.current_frame

    def test_camera(self, camera_index: int = 0) -> bool:
        """测试摄像头 - 兼容接口"""
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

    # =================== 手势识别模块 ===================

    def detect_gesture(self, hands_results):
        """手势识别核心算法"""
        if not hands_results.multi_hand_landmarks:
            return "None"

        landmarks = hands_results.multi_hand_landmarks[0].landmark

        # 获取手指关键点
        finger_landmarks = {
            'thumb': {'tip': landmarks[4], 'pip': landmarks[3]},
            'index': {'tip': landmarks[8], 'pip': landmarks[6]},
            'middle': {'tip': landmarks[12], 'pip': landmarks[10]},
            'ring': {'tip': landmarks[16], 'pip': landmarks[14]},
            'pinky': {'tip': landmarks[20], 'pip': landmarks[18]}
        }

        # 判断每个手指是否伸直
        fingers_extended = []

        # 拇指特殊处理（水平伸展）
        thumb_extended = abs(finger_landmarks['thumb']['tip'].x -
                             finger_landmarks['thumb']['pip'].x) > self.finger_threshold
        fingers_extended.append(thumb_extended)

        # 其他四指（垂直伸展）
        for finger_name in ['index', 'middle', 'ring', 'pinky']:
            tip = finger_landmarks[finger_name]['tip']
            pip = finger_landmarks[finger_name]['pip']
            extended = tip.y < pip.y - self.finger_threshold
            fingers_extended.append(extended)

        # 手势识别逻辑
        extended_count = sum(fingers_extended)

        if extended_count >= 4:
            return "Open Palm"
        elif extended_count <= 1:
            return "Fist"
        elif (fingers_extended[1] and fingers_extended[2] and
              not fingers_extended[3] and not fingers_extended[4]):
            return "Two Fingers Up"
        elif (fingers_extended[1] and not fingers_extended[2] and
              not fingers_extended[3] and not fingers_extended[4]):
            return "Index Up"
        else:
            return "None"

    def process_gesture_stable(self, raw_gesture):
        """手势稳定性处理"""
        self.gesture_history.append(raw_gesture)

        if len(self.gesture_history) < self.gesture_stability_frames:
            return self.current_gesture

        # 统计最近手势
        recent_gestures = list(self.gesture_history)
        gesture_counts = {}
        for g in recent_gestures:
            gesture_counts[g] = gesture_counts.get(g, 0) + 1

        if gesture_counts:
            most_common = max(gesture_counts, key=gesture_counts.get)
            required_count = self.gesture_stability_frames // 2 + 1
            if gesture_counts[most_common] >= required_count:
                return most_common

        return self.current_gesture

    def execute_gesture_command(self, gesture):
        """执行手势指令"""
        current_time = time.time()

        if (gesture != "None" and
                gesture != self.current_gesture and
                current_time - self.last_command_time > self.command_cooldown):

            if gesture in self.gesture_commands:
                command = self.gesture_commands[gesture]
                self.command_callback('手势', command)
                self.last_command_time = current_time
                print(f"✅ 手势指令: {gesture} → {command}")

    # =================== 头部动作识别模块 ===================

    def detect_head_action(self, face_results):
        """头部动作识别核心算法"""
        if not face_results.multi_face_landmarks:
            return "None"

        face_landmarks = face_results.multi_face_landmarks[0]
        landmarks = face_landmarks.landmark

        try:
            # 使用鼻尖作为头部位置参考点
            nose_tip = landmarks[self.face_landmarks_indices['nose_tip']]
            current_position = (nose_tip.x, nose_tip.y)

            self.head_movement_history.append(current_position)

            if len(self.head_movement_history) < self.head_action_frames:
                return "None"

            # 分析头部移动模式
            positions = list(self.head_movement_history)

            # Y轴变化分析（点头）
            y_positions = [pos[1] for pos in positions]
            y_range = max(y_positions) - min(y_positions)

            # X轴变化分析（摇头）
            x_positions = [pos[0] for pos in positions]
            x_range = max(x_positions) - min(x_positions)

            # 点头检测
            if y_range > self.nod_threshold:
                max_y_idx = y_positions.index(max(y_positions))
                if 3 <= max_y_idx <= len(y_positions) - 4:
                    start_y = y_positions[0]
                    end_y = y_positions[-1]
                    max_y = y_positions[max_y_idx]

                    if (max_y > start_y + self.nod_threshold * 0.6 and
                            max_y > end_y + self.nod_threshold * 0.6):
                        return "Nod"

            # 摇头检测
            if x_range > self.head_movement_threshold:
                direction_changes = 0
                for i in range(1, len(x_positions) - 1):
                    if ((x_positions[i] > x_positions[i - 1] and x_positions[i] > x_positions[i + 1]) or
                            (x_positions[i] < x_positions[i - 1] and x_positions[i] < x_positions[i + 1])):
                        direction_changes += 1

                if direction_changes >= 2:
                    return "Shake"

            return "None"

        except (IndexError, AttributeError):
            return "None"

    def process_head_action_stable(self, raw_action):
        """头部动作稳定性处理"""
        self.head_action_history.append(raw_action)

        if len(self.head_action_history) < self.head_action_frames // 2:
            return self.current_head_action

        recent_actions = list(self.head_action_history)
        action_counts = {}
        for a in recent_actions:
            action_counts[a] = action_counts.get(a, 0) + 1

        if action_counts:
            most_common = max(action_counts, key=action_counts.get)
            required_count = len(recent_actions) // 3 + 1
            if action_counts[most_common] >= required_count and most_common != "None":
                return most_common

        return "None"

    def execute_head_command(self, action):
        """执行头部动作指令"""
        current_time = time.time()

        if (action != "None" and
                action != self.current_head_action and
                current_time - self.last_head_command_time > self.command_cooldown):

            if action in self.head_action_commands:
                command = self.head_action_commands[action]
                self.command_callback('头部动作', command)
                self.last_head_command_time = current_time
                print(f"✅ 头部动作: {action} → {command}")

    # =================== 眼部状态监控模块 ===================

    def calculate_eye_aspect_ratio(self, eye_landmarks):
        """计算眼睛宽高比 (Eye Aspect Ratio - EAR)"""
        try:
            # 获取眼部6个关键点的坐标
            points = []
            for landmark in eye_landmarks:
                points.append([landmark.x, landmark.y])

            points = np.array(points)

            # 计算垂直距离
            vertical_1 = np.linalg.norm(points[1] - points[5])
            vertical_2 = np.linalg.norm(points[2] - points[4])

            # 计算水平距离
            horizontal = np.linalg.norm(points[0] - points[3])

            # EAR = (vertical_1 + vertical_2) / (2.0 * horizontal)
            if horizontal > 0:
                ear = (vertical_1 + vertical_2) / (2.0 * horizontal)
            else:
                ear = 0.0

            return ear

        except Exception as e:
            print(f"EAR计算错误: {e}")
            return 0.3

    def detect_eye_status(self, face_results):
        """眼部状态检测"""
        if not face_results.multi_face_landmarks:
            return "Unknown"

        face_landmarks = face_results.multi_face_landmarks[0]
        landmarks = face_landmarks.landmark

        try:
            # 获取左眼关键点
            left_eye_indices = [
                self.face_landmarks_indices['left_eye']['outer_corner'],
                self.face_landmarks_indices['left_eye']['top_1'],
                self.face_landmarks_indices['left_eye']['top_2'],
                self.face_landmarks_indices['left_eye']['inner_corner'],
                self.face_landmarks_indices['left_eye']['bottom_1'],
                self.face_landmarks_indices['left_eye']['bottom_2']
            ]

            # 获取右眼关键点
            right_eye_indices = [
                self.face_landmarks_indices['right_eye']['outer_corner'],
                self.face_landmarks_indices['right_eye']['top_1'],
                self.face_landmarks_indices['right_eye']['top_2'],
                self.face_landmarks_indices['right_eye']['inner_corner'],
                self.face_landmarks_indices['right_eye']['bottom_1'],
                self.face_landmarks_indices['right_eye']['bottom_2']
            ]

            # 获取实际的关键点坐标
            left_eye_points = [landmarks[i] for i in left_eye_indices]
            right_eye_points = [landmarks[i] for i in right_eye_indices]

            # 计算双眼EAR
            left_ear = self.calculate_eye_aspect_ratio(left_eye_points)
            right_ear = self.calculate_eye_aspect_ratio(right_eye_points)
            avg_ear = (left_ear + right_ear) / 2.0

            # 将EAR值添加到历史记录中进行平滑处理
            self.ear_history.append(avg_ear)

            # 使用移动平均来平滑EAR值
            if len(self.ear_history) > 0:
                smooth_ear = sum(self.ear_history) / len(self.ear_history)
            else:
                smooth_ear = avg_ear

            # 眼部状态判断
            if smooth_ear < self.eye_aspect_ratio_threshold:
                self.consecutive_closed_frames += 1
                if self.consecutive_closed_frames >= self.eye_closed_frames_threshold:
                    return "Closed_Long"
                else:
                    return "Closed"
            else:
                self.consecutive_closed_frames = 0
                return "Open"

        except (IndexError, AttributeError) as e:
            print(f"眼部检测错误: {e}")
            return "Unknown"

    def check_driver_attention(self, eye_status):
        """驾驶员注意力状态检查"""
        current_time = time.time()

        if eye_status == "Closed_Long":
            if self.driver_attention_status != "Distracted":
                self.driver_attention_status = "Distracted"
                # 防止频繁警告
                if current_time - self.last_attention_alert_time > 5.0:
                    # 发送开始分心警告的指令
                    self.command_callback('driver_distraction_start', '检测到驾驶员分心 - 长时间闭眼')
                    self.last_attention_alert_time = current_time
                    print("⚠️  驾驶员注意力警告: 检测到长时间闭眼!")
        else:
            if self.driver_attention_status == "Distracted":
                self.driver_attention_status = "Normal"
                # 发送停止分心警告的指令
                self.command_callback('driver_distraction_end', '驾驶员注意力恢复正常')
                print("✅ 驾驶员注意力恢复正常")

    # =================== 核心处理流程 ===================

    def process_frame(self, frame):
        """单帧处理主流程"""
        if frame is None:
            return None

        self.frame_count += 1
        self.current_frame = frame.copy()  # 更新当前帧

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # MediaPipe 检测
        hands_results = self.hands.process(rgb_frame)
        face_results = self.face_mesh.process(rgb_frame)

        # === 手势识别流程 ===
        raw_gesture = self.detect_gesture(hands_results)
        stable_gesture = self.process_gesture_stable(raw_gesture)

        if stable_gesture != self.current_gesture:
            self.execute_gesture_command(stable_gesture)
            self.current_gesture = stable_gesture

        # === 头部动作识别流程 ===
        raw_head_action = self.detect_head_action(face_results)
        stable_head_action = self.process_head_action_stable(raw_head_action)

        if stable_head_action != self.current_head_action:
            self.execute_head_command(stable_head_action)
            self.current_head_action = stable_head_action

        # === 眼部状态监控流程 ===
        eye_status = self.detect_eye_status(face_results)
        self.eyes_status = eye_status
        self.check_driver_attention(eye_status)

        # === 绘制可视化界面 ===
        display_frame = self.draw_interface(frame, hands_results, face_results)

        return display_frame

    def draw_interface(self, frame, hands_results, face_results):
        """绘制用户界面"""
        if frame is None:
            return None

        # 绘制手部关键点
        if hands_results.multi_hand_landmarks:
            for hand_landmarks in hands_results.multi_hand_landmarks:
                self.mp_drawing.draw_landmarks(
                    frame, hand_landmarks, self.mp_hands.HAND_CONNECTIONS,
                    self.mp_drawing_styles.get_default_hand_landmarks_style(),
                    self.mp_drawing_styles.get_default_hand_connections_style())

        # 绘制眼部关键点
        if face_results.multi_face_landmarks:
            for face_landmarks in face_results.multi_face_landmarks:
                landmarks = face_landmarks.landmark

                # 绘制左眼关键点
                for key, idx in self.face_landmarks_indices['left_eye'].items():
                    landmark = landmarks[idx]
                    x = int(landmark.x * frame.shape[1])
                    y = int(landmark.y * frame.shape[0])
                    cv2.circle(frame, (x, y), 2, (0, 255, 0), -1)

                # 绘制右眼关键点
                for key, idx in self.face_landmarks_indices['right_eye'].items():
                    landmark = landmarks[idx]
                    x = int(landmark.x * frame.shape[1])
                    y = int(landmark.y * frame.shape[0])
                    cv2.circle(frame, (x, y), 2, (0, 255, 0), -1)

        height, width = frame.shape[:2]

        # 半透明背景
        overlay = frame.copy()
        cv2.rectangle(overlay, (10, 10), (400, 200), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

        font = cv2.FONT_HERSHEY_SIMPLEX

        # === 状态显示区域 ===
        cv2.putText(frame, f"Hand: {self.current_gesture}", (20, 40),
                    font, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, f"Head: {self.current_head_action}", (20, 70),
                    font, 0.6, (255, 255, 0), 2)

        # 眼部状态
        eye_color = (0, 255, 0) if self.eyes_status == "Open" else (0, 0, 255)
        cv2.putText(frame, f"Eyes: {self.eyes_status}", (20, 100),
                    font, 0.6, eye_color, 2)

        # 注意力状态
        attention_color = (0, 255, 0) if self.driver_attention_status == "Normal" else (0, 0, 255)
        cv2.putText(frame, f"Attention: {self.driver_attention_status}", (20, 130),
                    font, 0.6, attention_color, 2)

        # EAR值显示
        if len(self.ear_history) > 0:
            current_ear = self.ear_history[-1]
            cv2.putText(frame, f"EAR: {current_ear:.3f}", (20, 160),
                        font, 0.5, (255, 255, 255), 1)

        # 帧数计数
        cv2.putText(frame, f"Frame: {self.frame_count}", (300, height - 20),
                    font, 0.4, (255, 255, 0), 1)

        return frame

    # =================== 主要运行接口 ===================

    def start_camera_recognition(self, camera_index: int = 0):
        """开始摄像头识别 - 兼容main.py的接口"""
        if self.is_running:
            print("⚠️ 视觉识别已在运行中")
            return

        print(f"🚀 启动车载智能视觉识别系统（摄像头 {camera_index}）")

        self.should_stop = False
        self.is_running = True

        def recognition_worker():
            try:
                # 初始化摄像头
                self.camera_cap = cv2.VideoCapture(camera_index)
                if not self.camera_cap.isOpened():
                    print(f"❌ 无法打开摄像头 {camera_index}")
                    self.is_running = False
                    return

                # 摄像头配置
                self.camera_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.camera_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.camera_cap.set(cv2.CAP_PROP_FPS, 30)

                print("✅ 视觉识别启动成功，开始处理视频流...")

                while self.is_running and not self.should_stop:
                    ret, frame = self.camera_cap.read()
                    if not ret:
                        print("❌ 无法读取摄像头帧")
                        break

                    # 处理帧
                    processed_frame = self.process_frame(frame)

                    # 在集成模式下，不显示窗口，只处理数据
                    # 如果需要调试，可以取消注释下面的代码
                    # if processed_frame is not None:
                    #     cv2.imshow("车载智能视觉识别", processed_frame)
                    #     if cv2.waitKey(1) & 0xFF == 27:  # ESC退出
                    #         break

                    time.sleep(0.033)  # 约30fps

            except Exception as e:
                print(f"❌ 视觉识别运行错误: {e}")
            finally:
                self.cleanup()

        # 在独立线程中运行识别
        self.vision_thread = threading.Thread(target=recognition_worker, daemon=True)
        self.vision_thread.start()

    def stop(self):
        """停止识别系统 - 兼容main.py的接口"""
        print("🛑 停止车载智能视觉识别系统")
        self.should_stop = True
        self.is_running = False

        # 等待线程结束
        if self.vision_thread and self.vision_thread.is_alive():
            self.vision_thread.join(timeout=2)

        self.cleanup()

    def cleanup(self):
        """清理资源"""
        try:
            if self.camera_cap:
                self.camera_cap.release()
                self.camera_cap = None

            cv2.destroyAllWindows()

            # 重置状态
            self.current_frame = None
            self.is_running = False

        except Exception as e:
            print(f"清理视觉识别资源时出错: {e}")

    # =================== 调试和测试接口 ===================

    def start_recognition_with_display(self, camera_index: int = 0):
        """启动带显示界面的识别（用于调试）"""
        print(f"\n🚀 启动车载智能视觉识别系统（调试模式）")

        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            print(f"❌ 无法打开摄像头 {camera_index}")
            return

        # 摄像头配置
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)

        cv2.namedWindow("车载智能视觉识别（调试模式）", cv2.WINDOW_NORMAL)
        self.is_running = True

        try:
            while self.is_running:
                ret, frame = cap.read()
                if not ret:
                    print("❌ 无法读取摄像头帧")
                    break

                # 处理帧
                processed_frame = self.process_frame(frame)
                if processed_frame is not None:
                    cv2.imshow("车载智能视觉识别（调试模式）", processed_frame)

                # 按键控制
                key = cv2.waitKey(1) & 0xFF
                if key == 27:  # ESC
                    break
                elif key == ord('q'):
                    break

        except KeyboardInterrupt:
            print("用户中断")
        finally:
            self.stop()
            cap.release()


# =================== 测试和演示 ===================

def test_vision_system():
    """测试车载视觉识别系统"""

    def command_callback(cmd_type, cmd_text):
        print(f"🎯 系统接收指令: [{cmd_type}] {cmd_text}")

    vision = VisionRecognition(command_callback)

    try:
        # 使用调试模式启动（带显示界面）
        vision.start_recognition_with_display()
    except KeyboardInterrupt:
        print("测试结束")
    finally:
        vision.stop()


if __name__ == "__main__":
    test_vision_system()