import enum
import time
import threading
import queue
import pyperclip

import pyautogui
import win32gui
import win32con
import keyboard as kb

from utils import set_dpi_aware
from config import (
    setup_logging, ensure_dirs, log, apply_settings,
    InputMethod,
    TEMPLATES_DIR, CHECK_INTERVAL_MS, VOICE_DONE_STABLE_FRAMES,
    PROCESSING_WAIT_TIMEOUT_S, CLOSE_RETRY_COUNT, CLOSE_INTERVAL_S,
    PASTE_ENTER_DELAY_S, WAITING_BAR_TIMEOUT_S, ACTIVATE_HOTKEY,
    TEMPLATE_READY_TO_SPEAKING, TEMPLATE_SPEECH_DONE, TEMPLATE_PROCESSING,
    TEMPLATE_CONFIRM_BTN, TEMPLATE_COPY_BTN, TEMPLATE_CLOSE_BTN,
    REQUIRED_TEMPLATES,
    WAKE_WORD_ENABLED, WAKE_WORD, WAKE_IDLE_TIMEOUT_MIN,
    FEEDFORWARD_ENABLED,
    ADAPTIVE_MIN_INTERVAL_MS, ADAPTIVE_MAX_INTERVAL_MS,
    STEP_AUDIO_ENABLED, STEP_AUDIO_VOICE,
)
from detector import (
    find_template, find_on_screen, check_on_screen,
    capture_screen, invalidate_screen_cache,
    batch_check, save_debug_screenshot,
)
from controller import (
    click, press_hotkey, paste_from_clipboard, type_enter,
    is_key_pressed,
)
from sound import play_start, play_success, play_error
from region_learner import region_learner
from wake_word import create_detector
from step_audio import init_client, speak as step_speak, cleanup as step_cleanup

set_dpi_aware()
setup_logging()
ensure_dirs()

pyautogui.PAUSE = 0.05
pyautogui.FAILSAFE = True


class State(enum.Enum):
    IDLE = "待机"
    WAKE_MONITOR = "监听唤醒词"

    ACTIVATING = "激活语音"
    WAITING_BAR = "等待语音条"
    WAITING_SPEECH = "等待说话"
    SPEAKING = "说话中"
    CONFIRMING = "点击确认"
    PROCESSING = "识别处理"
    RESULT_COPY = "复制结果"
    RESULT_CLOSE = "关闭弹窗"
    PASTE_SEND = "粘贴发送"

    QW_MONITORING_KEY = "等待右ALT"
    QW_SPEAKING = "说话中(千问)"
    QW_WAITING_INPUT = "等待千问输入"
    QW_ENTER_SEND = "回车发送(千问)"

    ERROR = "错误"


def _check_templates():
    missing = [name for name, _ in REQUIRED_TEMPLATES if not (TEMPLATES_DIR / name).exists()]
    if missing:
        log.warning("缺少模板文件: %s", missing)
        return False
    return True


def _get_foreground_title():
    hwnd = win32gui.GetForegroundWindow()
    return win32gui.GetWindowText(hwnd), hwnd


def _find_chat_window():
    exclude_keywords = [
        "系统托盘", "溢出窗口", "TaskSwitcherWnd", "Windows Input Experience",
        "TextInputHost", "ShellExperienceHost", "StartMenuExperience",
        "SearchHost", "Shell_TrayWnd", "MicrosoftText", "输入法",
    ]
    min_width, min_height = 300, 200

    def callback(hwnd, results):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title or len(title) < 2:
            return True
        if any(kw in title for kw in exclude_keywords):
            return True
        if win32gui.GetClassName(hwnd) in ["Button", "Static", "Edit"]:
            return True
        try:
            rect = win32gui.GetWindowRect(hwnd)
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            if w < min_width or h < min_height:
                return True
        except Exception:
            return True
        results.append((title, hwnd))
        return True

    results = []
    win32gui.EnumWindows(callback, results)
    return results[0] if results else ("", None)


def _set_foreground(hwnd):
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.25)
    except Exception:
        pass


def _get_clipboard_text():
    try:
        return pyperclip.paste()
    except Exception:
        return ""


class SystemIdentifier:
    def __init__(self):
        self._identified = False
        self._metrics = {}

    def identify(self, input_method: InputMethod, iterations: int = 3):
        if not iterations or self._identified:
            return
        log.info("开始系统辨识 (%d次迭代)...", iterations)
        latencies = []
        for i in range(iterations):
            t0 = time.perf_counter()
            press_hotkey(list(ACTIVATE_HOTKEY))
            time.sleep(0.5)
            screen = capture_screen()
            for _ in range(20):
                if check_on_screen(screen, TEMPLATE_READY_TO_SPEAKING, confidence=0.6):
                    break
                time.sleep(0.1)
                screen = capture_screen()
            t1 = time.perf_counter()
            latencies.append(t1 - t0)
            log.info("  辨识[%d/%d]: 语音条出现延迟=%.2fs", i + 1, iterations, t1 - t0)

        if latencies:
            import numpy as np
            self._metrics["bar_latency_p50"] = float(np.median(latencies))
            self._metrics["bar_latency_p95"] = float(np.percentile(latencies, 95))
            log.info("系统辨识完成: 语音条延迟 p50=%.2fs p95=%.2fs",
                     self._metrics["bar_latency_p50"], self._metrics["bar_latency_p95"])
        self._identified = True

    @property
    def is_identified(self):
        return self._identified

    def get(self, key, default=None):
        return self._metrics.get(key, default)


_system_identifier = SystemIdentifier()


class InputHelper:
    MIN_SPEAKING_DURATION_S = 3.0
    SPEECH_END_STABLE_FRAMES = 5

    def __init__(self):
        self.state = State.IDLE
        self.target_hwnd = None
        self.target_title = ""
        self._stop_event = threading.Event()
        self._processing_start = 0.0
        self._waiting_bar_start = 0.0
        self._clipboard_before = ""
        self._not_ready_count = 0
        self._not_ready_threshold = 3
        self._speaking_start = 0.0
        self._speech_end_count = 0
        self._debug_screenshot_count = 0
        self._idle_start = 0.0
        self._sleeping = False
        self._qianwen_alt_pressed = False
        self._alt_release_processed = False

        self._input_method = InputMethod.ZHIPU
        self._feedforward_timer = None
        self._state_lock = threading.Lock()
        self._pending_transition: queue.Queue = queue.Queue()

        self._wake_detector = None
        self._wake_enabled = False

    def _cancel_feedforward(self):
        if self._feedforward_timer is not None:
            self._feedforward_timer.cancel()
            self._feedforward_timer = None

    def _schedule_feedforward(self, delay: float, target_state: State):
        self._cancel_feedforward()
        if not FEEDFORWARD_ENABLED:
            return
        def _fire():
            self._pending_transition.put(target_state)
        self._feedforward_timer = threading.Timer(delay, _fire)
        self._feedforward_timer.daemon = True
        self._feedforward_timer.start()

    def start(self, input_method: InputMethod = InputMethod.ZHIPU):
        self._input_method = input_method
        self._wake_enabled = WAKE_WORD_ENABLED and input_method == InputMethod.ZHIPU

        if not _check_templates():
            log.error("模板不完整，无法启动，请先运行截图工具")
            play_error()
            return

        region_learner.load()

        title, hwnd = _find_chat_window()
        if not hwnd:
            title, hwnd = _get_foreground_title()
        self.target_hwnd = hwnd
        self.target_title = title
        log.info("目标窗口: %s (hwnd=%s), 输入法: %s", title, hwnd, input_method.value)

        try:
            kb.add_hotkey("ctrl+shift+q", self.stop)
        except Exception:
            pass

        if self._wake_enabled:
            self._setup_wake_detector()
            self._schedule_idle_timeout()
            self._transition(State.WAKE_MONITOR)
            log.info("启动唤醒词监听模式, 唤醒词='%s', 超时=%dmin", WAKE_WORD, WAKE_IDLE_TIMEOUT_MIN)
        else:
            apply_settings()
            if FEEDFORWARD_ENABLED and _system_identifier.is_identified:
                log.info("使用系统辨识参数")
            self._transition(State.ACTIVATING if input_method == InputMethod.ZHIPU else State.QW_MONITORING_KEY)

        init_client(STEP_AUDIO_VOICE, STEP_AUDIO_ENABLED)
        if STEP_AUDIO_ENABLED:
            log.info("StepAudio 实时语音播报已启用")

        play_start()

        while not self._stop_event.is_set():
            try:
                self._process_pending_transitions()
                interval = self._get_adaptive_interval()
                self._tick()
                time.sleep(interval / 1000.0)
            except Exception as exc:
                log.error("状态 %s 异常: %s", self.state.value, exc)
                self._transition(State.ERROR)

        region_learner.save()
        self._cleanup_wake_detector()
        log.info("助手已停止")

    def stop(self):
        self._stop_event.set()
        self._cancel_feedforward()
        region_learner.save()
        step_cleanup()
        log.info("助手停止请求")

    def _setup_wake_detector(self):
        self._wake_detector = create_detector(WAKE_WORD, True, self._on_wake_word)
        self._wake_detector.start()

    def _cleanup_wake_detector(self):
        if self._wake_detector is not None:
            self._wake_detector.stop()
            self._wake_detector = None

    def _on_wake_word(self):
        if self.state == State.WAKE_MONITOR:
            log.info("唤醒词触发，启动语音流程")
            self._cancel_feedforward()
            self._pending_transition.put("_WAKE_TRIGGER")

    def _schedule_idle_timeout(self):
        if self._wake_enabled and WAKE_IDLE_TIMEOUT_MIN > 0:
            timeout_s = WAKE_IDLE_TIMEOUT_MIN * 60
            log.info("设定空闲超时: %d分钟 (%ds)", WAKE_IDLE_TIMEOUT_MIN, timeout_s)
            self._idle_start = time.time()

    def _check_idle_timeout(self):
        if not self._wake_enabled or WAKE_IDLE_TIMEOUT_MIN <= 0:
            return False
        if self._idle_start <= 0:
            return False
        elapsed = time.time() - self._idle_start
        if elapsed > WAKE_IDLE_TIMEOUT_MIN * 60:
            log.info("空闲超时(%dmin)，进入待机唤醒模式", WAKE_IDLE_TIMEOUT_MIN)
            self._transition(State.WAKE_MONITOR)
            return True
        return False

    def _process_pending_transitions(self):
        while not self._pending_transition.empty():
            item = self._pending_transition.get_nowait()
            if item == "_WAKE_TRIGGER":
                apply_settings()
                self._idle_start = 0.0
                self._transition(State.ACTIVATING)
            elif isinstance(item, State):
                self._transition(item)

    def _get_adaptive_interval(self) -> int:
        state_intervals = {
            State.IDLE: ADAPTIVE_MAX_INTERVAL_MS,
            State.WAKE_MONITOR: ADAPTIVE_MAX_INTERVAL_MS,
            State.ACTIVATING: ADAPTIVE_MAX_INTERVAL_MS,
            State.WAITING_BAR: CHECK_INTERVAL_MS,
            State.WAITING_SPEECH: CHECK_INTERVAL_MS,
            State.SPEAKING: ADAPTIVE_MIN_INTERVAL_MS,
            State.CONFIRMING: ADAPTIVE_MIN_INTERVAL_MS,
            State.PROCESSING: CHECK_INTERVAL_MS,
            State.RESULT_COPY: ADAPTIVE_MIN_INTERVAL_MS,
            State.RESULT_CLOSE: CHECK_INTERVAL_MS,
            State.PASTE_SEND: ADAPTIVE_MAX_INTERVAL_MS,
            State.QW_MONITORING_KEY: ADAPTIVE_MIN_INTERVAL_MS,
            State.QW_SPEAKING: CHECK_INTERVAL_MS,
            State.QW_WAITING_INPUT: ADAPTIVE_MAX_INTERVAL_MS,
            State.QW_ENTER_SEND: ADAPTIVE_MAX_INTERVAL_MS,
            State.ERROR: ADAPTIVE_MAX_INTERVAL_MS,
        }
        return state_intervals.get(self.state, CHECK_INTERVAL_MS)

    def _transition(self, new_state: State):
        if self.state != new_state:
            log.info("状态转换: %s -> %s", self.state.value, new_state.value)
            self.state = new_state
            if new_state in (State.ACTIVATING, State.QW_MONITORING_KEY, State.QW_SPEAKING):
                self._idle_start = time.time()

    def _tick(self):
        handler_map = {
            State.IDLE: self._do_idle,
            State.WAKE_MONITOR: self._do_wake_monitor,
            State.ACTIVATING: self._do_activating,
            State.WAITING_BAR: self._do_waiting_bar,
            State.WAITING_SPEECH: self._do_waiting_speech,
            State.SPEAKING: self._do_speaking,
            State.CONFIRMING: self._do_confirming,
            State.PROCESSING: self._do_processing,
            State.RESULT_COPY: self._do_result_copy,
            State.RESULT_CLOSE: self._do_result_close,
            State.PASTE_SEND: self._do_paste_send,
            State.QW_MONITORING_KEY: self._do_qw_monitoring_key,
            State.QW_SPEAKING: self._do_qw_speaking,
            State.QW_WAITING_INPUT: self._do_qw_waiting_input,
            State.QW_ENTER_SEND: self._do_qw_enter_send,
            State.ERROR: self._do_error,
        }
        handler = handler_map.get(self.state)
        if handler:
            handler()

    # ========== 通用状态 ==========

    def _do_idle(self):
        if not self._stop_event.is_set():
            time.sleep(1.0)

    def _do_wake_monitor(self):
        if self._check_idle_timeout():
            return
        pass

    # ========== 智谱AI 工作流 ==========

    def _do_activating(self):
        log.info("发送激活快捷键 %s", "+".join(ACTIVATE_HOTKEY))
        invalidate_screen_cache()
        press_hotkey(list(ACTIVATE_HOTKEY))
        time.sleep(0.6)
        self._waiting_bar_start = time.time()

        bar_latency = _system_identifier.get("bar_latency_p95")
        if bar_latency and FEEDFORWARD_ENABLED:
            self._schedule_feedforward(bar_latency * 0.9, State.WAITING_SPEECH)
        self._transition(State.WAITING_BAR)

    def _do_waiting_bar(self):
        if self._check_idle_timeout():
            return
        screen = capture_screen()
        results = batch_check(screen, [
            (TEMPLATE_READY_TO_SPEAKING, 0.82, (0, 0)),
            (TEMPLATE_CONFIRM_BTN, 0.60, (0, 0)),
        ])

        if results.get(TEMPLATE_READY_TO_SPEAKING):
            self._not_ready_count = 0
            self._cancel_feedforward()
            self._transition(State.WAITING_SPEECH)
            return
        if results.get(TEMPLATE_CONFIRM_BTN):
            self._cancel_feedforward()
            self._transition(State.WAITING_SPEECH)
            return

        if time.time() - self._waiting_bar_start > WAITING_BAR_TIMEOUT_S:
            log.warning("等待语音条超时，重新激活")
            self._transition(State.ACTIVATING)

    def _do_waiting_speech(self):
        screen = capture_screen()
        if check_on_screen(screen, TEMPLATE_READY_TO_SPEAKING):
            self._not_ready_count = 0
            return
        if check_on_screen(screen, TEMPLATE_PROCESSING):
            self._processing_start = time.time()
            self._transition(State.PROCESSING)
            return
        self._not_ready_count += 1
        if self._not_ready_count >= self._not_ready_threshold:
            log.info("连续 %d 帧未检测到「开始说话」，判定用户已开始说话", self._not_ready_threshold)
            self._not_ready_count = 0
            self._speaking_start = time.time()
            self._speech_end_count = 0
            self._transition(State.SPEAKING)

    def _do_speaking(self):
        speaking_duration = time.time() - self._speaking_start
        if speaking_duration < self.MIN_SPEAKING_DURATION_S:
            return
        screen = capture_screen()
        self._debug_screenshot_count += 1
        if self._debug_screenshot_count % 10 == 1:
            save_debug_screenshot("speaking", screen)

        results = batch_check(screen, [
            (TEMPLATE_SPEECH_DONE, 0.70, (0, 0)),
            (TEMPLATE_PROCESSING, 0.82, (0, 0)),
        ])

        if results.get(TEMPLATE_SPEECH_DONE):
            self._speech_end_count += 1
            if self._speech_end_count >= self.SPEECH_END_STABLE_FRAMES:
                log.info("连续 %d 帧检测到发言完成 (已说=%.1fs)",
                         self.SPEECH_END_STABLE_FRAMES, speaking_duration)
                save_debug_screenshot("speech_end_detected", screen)
                self._speech_end_count = 0
                if FEEDFORWARD_ENABLED:
                    self._schedule_feedforward(0.8, State.PROCESSING)
                self._transition(State.CONFIRMING)
                return
        else:
            self._speech_end_count = 0

        if results.get(TEMPLATE_PROCESSING):
            self._processing_start = time.time()
            self._transition(State.PROCESSING)
            return

    def _do_confirming(self):
        r = find_template(TEMPLATE_CONFIRM_BTN, confidence=0.6)
        if r:
            cx, cy = r["center"]
            log.info("点击确认按钮 (%d, %d)", cx, cy)
            click(cx, cy)
            region_learner.tracker(TEMPLATE_CONFIRM_BTN).update(cx, cy, r["size"][0], r["size"][1])
            self._processing_start = time.time()
            processing_latency = _system_identifier.get("processing_latency", 1.5)
            if FEEDFORWARD_ENABLED:
                self._schedule_feedforward(processing_latency * 0.8, State.RESULT_COPY)
            self._transition(State.PROCESSING)
        else:
            log.warning("未找到确认按钮，重新激活")
            self._transition(State.ACTIVATING)

    def _do_processing(self):
        screen = capture_screen()
        if check_on_screen(screen, TEMPLATE_PROCESSING):
            self._processing_start = time.time()
            return
        r = find_on_screen(screen, TEMPLATE_COPY_BTN, confidence=0.6)
        if r:
            region_learner.tracker(TEMPLATE_COPY_BTN).update(
                r["center"][0], r["center"][1], r["size"][0], r["size"][1])
            self._cancel_feedforward()
            self._transition(State.RESULT_COPY)
            return
        if time.time() - self._processing_start > PROCESSING_WAIT_TIMEOUT_S:
            log.warning("处理超时")
            self._transition(State.ERROR)

    def _do_result_copy(self):
        r = find_template(TEMPLATE_COPY_BTN, confidence=0.6)
        if r:
            cx, cy = r["center"]
            log.info("点击复制按钮 (%d, %d)", cx, cy)
            region_learner.tracker(TEMPLATE_COPY_BTN).update(cx, cy, r["size"][0], r["size"][1])
            self._clipboard_before = _get_clipboard_text()
            click(cx, cy)
            if FEEDFORWARD_ENABLED:
                self._schedule_feedforward(0.4, State.RESULT_CLOSE)
            time.sleep(0.5)
            self._transition(State.RESULT_CLOSE)
        else:
            log.warning("未找到复制按钮")
            self._transition(State.ERROR)

    def _do_result_close(self):
        self._cancel_feedforward()
        for i in range(CLOSE_RETRY_COUNT):
            r = find_template(TEMPLATE_CLOSE_BTN, confidence=0.6)
            if r:
                cx, cy = r["center"]
                log.info("点击关闭按钮 (%d, %d) 第%d次", cx, cy, i + 1)
                region_learner.tracker(TEMPLATE_CLOSE_BTN).update(cx, cy, r["size"][0], r["size"][1])
                click(cx, cy)
                time.sleep(CLOSE_INTERVAL_S)
            else:
                break

        new_text = _get_clipboard_text()
        if new_text and new_text != self._clipboard_before:
            log.info("复制验证成功，剪贴板内容长度: %d", len(new_text))
        else:
            log.warning("复制验证失败，剪贴板无变化")
        self._transition(State.PASTE_SEND)

    def _do_paste_send(self):
        title, hwnd = _find_chat_window()
        if hwnd and hwnd != self.target_hwnd:
            self.target_hwnd = hwnd
            self.target_title = title
            log.info("重新识别到目标窗口: %s", title)
        log.info("切换到目标窗口并粘贴发送: %s (hwnd=%s)", self.target_title, self.target_hwnd)
        _set_foreground(self.target_hwnd)
        time.sleep(0.3)
        clip_text = _get_clipboard_text()
        log.info("剪贴板内容长度: %d", len(clip_text) if clip_text else 0)
        paste_from_clipboard()
        time.sleep(PASTE_ENTER_DELAY_S)
        type_enter()
        log.info("已执行粘贴+回车")
        play_success()

        if clip_text and len(clip_text) > 0:
            step_speak(clip_text[:500])

        if self._wake_enabled:
            self._schedule_idle_timeout()
            self._transition(State.WAKE_MONITOR)
        else:
            time.sleep(1.0)
            self._transition(State.ACTIVATING)

    # ========== 千问语音输入 工作流 ==========

    def _do_qw_monitoring_key(self):
        self._check_idle_timeout()
        if is_key_pressed("alt gr"):
            if not self._qianwen_alt_pressed:
                self._qianwen_alt_pressed = True
                self._alt_release_processed = False
                log.info("千问: 右ALT按下，开始说话")
                self._speaking_start = time.time()
                self._transition(State.QW_SPEAKING)

    def _do_qw_speaking(self):
        if not is_key_pressed("alt gr"):
            if not self._alt_release_processed:
                self._alt_release_processed = True
                self._qianwen_alt_pressed = False
                duration = time.time() - self._speaking_start
                log.info("千问: 右ALT松开 (说话时长=%.1fs)", duration)
                time.sleep(0.5)
                self._transition(State.QW_WAITING_INPUT)
            return

    def _do_qw_waiting_input(self):
        log.info("千问: 等待输入完成，准备按回车发送")
        self._transition(State.QW_ENTER_SEND)

    def _do_qw_enter_send(self):
        title, hwnd = _find_chat_window()
        if hwnd:
            self.target_hwnd = hwnd
        log.info("千问: 切换到目标窗口并发送回车: %s", self.target_title)
        _set_foreground(self.target_hwnd)
        time.sleep(0.3)
        type_enter()
        log.info("千问: 已发送回车")
        play_success()

        if self._wake_enabled:
            self._schedule_idle_timeout()
        self._transition(State.QW_MONITORING_KEY)

    # ========== 错误处理 ==========

    def _do_error(self):
        play_error()
        self._cancel_feedforward()
        if self._wake_enabled:
            self._schedule_idle_timeout()
            self._transition(State.WAKE_MONITOR)
        else:
            time.sleep(1.0)
            self._transition(State.ACTIVATING if self._input_method == InputMethod.ZHIPU
                             else State.QW_MONITORING_KEY)
