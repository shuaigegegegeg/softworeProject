import cv2
import time
import numpy as np
from collections import deque
import mediapipe as mp
from typing import Optional, Callable
import math


class EnhancedVisionRecognition:
    """
    车载智能视觉识别模块
    集成功能：
    1. 手势识别 - 控制音乐、空调等
    2. 头部动作识别 - 确认/取消操作
    3. 眼部状态监控 - 驾驶员注意力检测
    """

    def __init__(self, command_callback: Optional[Callable[[str, str], None]] = None):
        self.command_callback = command_callback or self.default_callback

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
        self.finger_threshold = 0.02  # 手指伸直阈值
        self.gesture_stability_frames = 5  # 手势稳定确认帧数
        self.gesture_history = deque(maxlen=self.gesture_stability_frames)
        self.current_gesture = "None"

        # ===== 头部动作识别参数 =====
        self.head_movement_threshold = 0.1  # 头部移动阈值（降低以提高敏感度）
        self.nod_threshold = 0.1  # 点头专用阈值（更敏感）
        self.head_action_frames = 10  # 头部动作确认帧数（增加以获得更好的检测）
        self.head_movement_history = deque(maxlen=20)  # 增加历史记录
        self.head_action_history = deque(maxlen=self.head_action_frames)
        self.current_head_action = "None"

        # ===== 眼部状态监控参数 =====
        self.eye_aspect_ratio_threshold = 0.21  # 眼睛闭合阈值
        self.eye_closed_frames_threshold = 60  # 闭眼帧数阈值 (约2秒 @30fps)
        self.consecutive_closed_frames = 0
        self.eyes_status = "Open"
        self.driver_attention_status = "Normal"

        # ===== 指令控制参数 =====
        self.command_cooldown = 2.0  # 指令冷却时间
        self.last_command_time = 0
        self.last_head_command_time = 0
        self.last_attention_alert_time = 0

        # ===== 系统状态 =====
        self.is_running = False
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
            'left_eye': [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246],
            'right_eye': [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398],
            'left_eye_corners': [33, 133],
            'right_eye_corners': [362, 263]
        }

        self._print_startup_info()

    def _print_startup_info(self):
        """打印启动信息"""
        print("🎯 车载智能视觉识别系统已启动")
        print("=" * 50)
        print("✋ 手势识别功能:")
        for gesture, command in self.gesture_commands.items():
            print(f"   {gesture} → {command}")
        print("\n🤖 头部动作识别功能:")
        for action, command in self.head_action_commands.items():
            print(f"   {action} → {command}")
        print("\n👁️ 驾驶员注意力监控:")
        print("   闭眼超过2秒 → 分心警告")
        print("\n⚙️ 检测参数:")
        print(f"   点头检测阈值: {self.nod_threshold}")
        print(f"   摇头检测阈值: {self.head_movement_threshold}")
        print(f"   头部动作确认帧数: {self.head_action_frames}")
        print("=" * 50)
        print("💡 调试提示: 观察界面下方的 Y_range 和 X_range 数值")
        print("   点头时 Y_range 应该超过点头阈值")
        print("   摇头时 X_range 应该超过摇头阈值")
        print("\n🔧 实时调试按键:")
        print("   1/2: 调整点头阈值（减少/增加）")
        print("   3/4: 调整摇头阈值（减少/增加）")
        print("   R: 重置所有参数")
        print("   Q/ESC: 退出系统")

    def default_callback(self, cmd_type: str, cmd_text: str):
        """默认回调函数"""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] 🎯 {cmd_type}: {cmd_text}")

    # =================== 手势识别模块 ===================

    def detect_gesture(self, hands_results):
        """
        手势识别核心算法
        支持：张开手掌、握拳、食指向上、食指+中指向上
        """
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

        # 调试输出（每20帧一次）
        if self.frame_count % 20 == 0:
            finger_names = ['T', 'I', 'M', 'R', 'P']
            finger_status = [f"{name}:{int(ext)}" for name, ext in zip(finger_names, fingers_extended)]
            print(f"手指状态: [{', '.join(finger_status)}]")

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
        """
        头部动作识别核心算法
        支持：点头、摇头
        """
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

            # Y轴变化分析（点头）- 图像坐标系Y向下递增
            y_positions = [pos[1] for pos in positions]
            y_range = max(y_positions) - min(y_positions)

            # X轴变化分析（摇头）
            x_positions = [pos[0] for pos in positions]
            x_range = max(x_positions) - min(x_positions)

            # 调试输出（每30帧一次）
            if self.frame_count % 30 == 0:
                print(f"头部移动分析: Y_range={y_range:.4f}(阈值:{self.nod_threshold:.4f}), X_range={x_range:.4f}")
                print(f"Y位置变化: {[f'{y:.3f}' for y in y_positions[-8:]]}")
                if y_range > self.nod_threshold:
                    max_y_idx = y_positions.index(max(y_positions))
                    print(f"检测到Y轴变化，最低点位置: {max_y_idx}/{len(y_positions)}")

            # 点头检测 - 使用专用阈值
            if y_range > self.nod_threshold:  # 使用更敏感的点头阈值
                # 方法1：寻找点头模式
                max_y_idx = y_positions.index(max(y_positions))
                min_y_idx = y_positions.index(min(y_positions))

                # 点头模式：最低点在中间部分，且有明显的下降再上升
                if 3 <= max_y_idx <= len(y_positions) - 4:
                    start_y = y_positions[0]
                    end_y = y_positions[-1]
                    max_y = y_positions[max_y_idx]

                    if (max_y > start_y + self.nod_threshold * 0.6 and
                            max_y > end_y + self.nod_threshold * 0.6):
                        return "Nod"

                # 方法2：简化的点头检测（备选方案）
                # 检查是否有明显的先下后上模式
                mid_point = len(y_positions) // 2
                first_quarter = y_positions[:mid_point]
                second_quarter = y_positions[mid_point:]

                if len(first_quarter) >= 3 and len(second_quarter) >= 3:
                    # 前半段平均值vs后半段平均值，以及整体变化
                    first_avg = sum(first_quarter) / len(first_quarter)
                    second_avg = sum(second_quarter) / len(second_quarter)

                    # 前半段Y值应该增大（头向下），后半段Y值应该减小（头向上）
                    if (max(first_quarter) > min(first_quarter) + self.nod_threshold * 0.4 and
                            max(second_quarter) > min(second_quarter) + self.nod_threshold * 0.4 and
                            first_avg < second_avg):  # 前半段平均位置高于后半段
                        return "Nod"

            # 摇头检测 - 保持原有逻辑
            if x_range > self.head_movement_threshold:
                # 检测左右运动中的方向变化
                direction_changes = 0
                for i in range(1, len(x_positions) - 1):
                    if ((x_positions[i] > x_positions[i - 1] and x_positions[i] > x_positions[i + 1]) or
                            (x_positions[i] < x_positions[i - 1] and x_positions[i] < x_positions[i + 1])):
                        direction_changes += 1

                # 摇头需要至少2次方向变化
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
        # 垂直距离
        A = np.linalg.norm(np.array([eye_landmarks[1].x, eye_landmarks[1].y]) -
                           np.array([eye_landmarks[5].x, eye_landmarks[5].y]))
        B = np.linalg.norm(np.array([eye_landmarks[2].x, eye_landmarks[2].y]) -
                           np.array([eye_landmarks[4].x, eye_landmarks[4].y]))

        # 水平距离
        C = np.linalg.norm(np.array([eye_landmarks[0].x, eye_landmarks[0].y]) -
                           np.array([eye_landmarks[3].x, eye_landmarks[3].y]))

        # EAR = (A + B) / (2.0 * C)
        ear = (A + B) / (2.0 * C)
        return ear

    def detect_eye_status(self, face_results):
        """眼部状态检测"""
        if not face_results.multi_face_landmarks:
            return "Unknown"

        face_landmarks = face_results.multi_face_landmarks[0]
        landmarks = face_landmarks.landmark

        try:
            # 获取左右眼关键点
            left_eye_points = [landmarks[i] for i in [33, 7, 163, 144, 145, 153]]
            right_eye_points = [landmarks[i] for i in [362, 382, 381, 380, 374, 373]]

            # 计算双眼EAR
            left_ear = self.calculate_eye_aspect_ratio(left_eye_points)
            right_ear = self.calculate_eye_aspect_ratio(right_eye_points)
            avg_ear = (left_ear + right_ear) / 2.0

            # 眼部状态判断
            if avg_ear < self.eye_aspect_ratio_threshold:
                self.consecutive_closed_frames += 1
                if self.consecutive_closed_frames >= self.eye_closed_frames_threshold:
                    return "Closed_Long"  # 长时间闭眼
                else:
                    return "Closed"  # 短时间闭眼
            else:
                self.consecutive_closed_frames = 0
                return "Open"  # 睁眼

        except (IndexError, AttributeError):
            return "Unknown"

    def check_driver_attention(self, eye_status):
        """驾驶员注意力状态检查"""
        current_time = time.time()

        if eye_status == "Closed_Long":
            if self.driver_attention_status != "Distracted":
                self.driver_attention_status = "Distracted"
                # 防止频繁警告
                if current_time - self.last_attention_alert_time > 5.0:
                    self.command_callback('注意力警告', '检测到驾驶员分心 - 长时间闭眼')
                    self.last_attention_alert_time = current_time
                    print("⚠️  驾驶员注意力警告: 检测到长时间闭眼!")
        else:
            if self.driver_attention_status == "Distracted":
                self.driver_attention_status = "Normal"
                print("✅ 驾驶员注意力恢复正常")

    # =================== 核心处理流程 ===================

    def process_frame(self, frame):
        """
        单帧处理主流程
        集成所有识别功能
        """
        self.frame_count += 1
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

    # =================== 可视化界面 ===================

    def draw_interface(self, frame, hands_results, face_results):
        """绘制用户界面"""
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
                # 只绘制眼部关键点
                for idx in self.face_landmarks_indices['left_eye'] + self.face_landmarks_indices['right_eye']:
                    landmark = face_landmarks.landmark[idx]
                    x = int(landmark.x * frame.shape[1])
                    y = int(landmark.y * frame.shape[0])
                    cv2.circle(frame, (x, y), 1, (0, 255, 0), -1)

        height, width = frame.shape[:2]

        # 半透明背景
        overlay = frame.copy()
        cv2.rectangle(overlay, (10, 10), (520, 300), (0, 0, 0), -1)
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

        # === 功能说明区域 ===
        y_offset = 160
        features = [
            "=== 手势功能 ===",
            "张开手掌 → 播放音乐",
            "握拳 → 暂停音乐",
            "食指向上 → 升温",
            "双指向上 → 降温",
            "",
            "=== 头部动作 ===",
            "点头 → 确认操作",
            "摇头 → 取消操作",
            "",
            "=== 按键调试 ===",
            "1/2: 点头阈值 ±",
            "3/4: 摇头阈值 ±",
            "R: 重置参数",
            "Q/ESC: 退出"
        ]

        for i, feature in enumerate(features):
            if feature == "":
                continue

            color = (255, 255, 255)
            if "===" in feature:
                color = (0, 255, 255)
            elif (self.current_gesture in feature) or (self.current_head_action in feature):
                color = (0, 255, 0)

            cv2.putText(frame, feature, (20, y_offset + i * 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        # === 系统信息区域 ===
        # 头部动作调试信息
        if len(self.head_movement_history) > 0:
            current_pos = self.head_movement_history[-1]
            cv2.putText(frame, f"Head Pos: ({current_pos[0]:.3f}, {current_pos[1]:.3f})",
                        (20, height - 80), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

            if len(self.head_movement_history) >= 5:
                positions = list(self.head_movement_history)
                y_positions = [pos[1] for pos in positions]
                x_positions = [pos[0] for pos in positions]
                y_range = max(y_positions) - min(y_positions)
                x_range = max(x_positions) - min(x_positions)

                cv2.putText(frame, f"Y_range: {y_range:.4f} (需要>{self.nod_threshold:.4f})",
                            (20, height - 60), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                            (0, 255, 0) if y_range > self.nod_threshold else (255, 255, 255), 1)
                cv2.putText(frame, f"X_range: {x_range:.4f} (需要>{self.head_movement_threshold:.4f})",
                            (20, height - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                            (0, 255, 0) if x_range > self.head_movement_threshold else (255, 255, 255), 1)

        # 闭眼计数器
        if self.consecutive_closed_frames > 0:
            closed_seconds = self.consecutive_closed_frames / 30.0
            cv2.putText(frame, f"Closed: {closed_seconds:.1f}s", (350, 40),
                        font, 0.5, (0, 165, 255), 1)

        # 指令冷却状态
        current_time = time.time()
        cooldown_remaining = max(0, self.command_cooldown - (current_time - self.last_command_time))
        if cooldown_remaining > 0:
            cv2.putText(frame, f"Gesture Cooldown: {cooldown_remaining:.1f}s", (280, height - 80),
                        font, 0.4, (255, 100, 100), 1)

        head_cooldown_remaining = max(0, self.command_cooldown - (current_time - self.last_head_command_time))
        if head_cooldown_remaining > 0:
            cv2.putText(frame, f"Head Cooldown: {head_cooldown_remaining:.1f}s", (280, height - 60),
                        font, 0.4, (255, 100, 100), 1)

        # 帧数计数
        cv2.putText(frame, f"Frame: {self.frame_count}", (450, height - 20),
                    font, 0.4, (255, 255, 0), 1)

        return frame

    # =================== 系统控制 ===================

    def start_recognition(self, camera_index=0):
        """启动视觉识别系统"""
        print(f"\n🚀 启动车载智能视觉识别系统")

        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            print(f"❌ 无法打开摄像头 {camera_index}")
            return

        # 摄像头配置
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)

        cv2.namedWindow("车载智能视觉识别", cv2.WINDOW_NORMAL)
        self.is_running = True

        try:
            while self.is_running:
                ret, frame = cap.read()
                if not ret:
                    print("❌ 无法读取摄像头帧")
                    break

                # 处理帧
                processed_frame = self.process_frame(frame)
                cv2.imshow("车载智能视觉识别", processed_frame)

                # 按键控制
                key = cv2.waitKey(1) & 0xFF
                if key == 27:  # ESC
                    break
                elif key == ord('q'):
                    break
                elif key == ord('1'):  # 降低点头阈值
                    self.nod_threshold = max(0.005, self.nod_threshold - 0.005)
                    print(f"点头阈值调整为: {self.nod_threshold:.4f}")
                elif key == ord('2'):  # 提高点头阈值
                    self.nod_threshold = min(0.050, self.nod_threshold + 0.005)
                    print(f"点头阈值调整为: {self.nod_threshold:.4f}")
                elif key == ord('3'):  # 降低摇头阈值
                    self.head_movement_threshold = max(0.010, self.head_movement_threshold - 0.005)
                    print(f"摇头阈值调整为: {self.head_movement_threshold:.4f}")
                elif key == ord('4'):  # 提高摇头阈值
                    self.head_movement_threshold = min(0.050, self.head_movement_threshold + 0.005)
                    print(f"摇头阈值调整为: {self.head_movement_threshold:.4f}")
                elif key == ord('r'):  # 重置参数
                    self.nod_threshold = 0.015
                    self.head_movement_threshold = 0.025
                    print("参数已重置为默认值")

        except KeyboardInterrupt:
            print("用户中断")
        finally:
            self.stop()

    def stop(self):
        """停止识别系统"""
        print("🛑 停止车载智能视觉识别系统")
        self.is_running = False
        cv2.destroyAllWindows()

    # =================== 兼容性接口 ===================

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

    def start_camera_recognition(self, camera_index: int = 0):
        """开始摄像头识别（兼容原接口）"""
        self.start_recognition(camera_index)

    def get_current_frame(self):
        """获取当前摄像头帧（兼容原接口）"""
        return None


# =================== 测试和演示 ===================

def test_vision_system():
    """测试车载视觉识别系统"""

    def command_callback(cmd_type, cmd_text):
        print(f"🎯 系统接收指令: [{cmd_type}] {cmd_text}")
        # 这里可以调用实际的车载系统API

    vision = EnhancedVisionRecognition(command_callback)

    try:
        vision.start_recognition()
    except KeyboardInterrupt:
        print("测试结束")
    finally:
        vision.stop()


if __name__ == "__main__":
    test_vision_system()