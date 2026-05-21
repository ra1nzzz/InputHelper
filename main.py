import enum
import time
import threading
import queue
import pyperclip
import numpy as np

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
    FOREGROUND_DELAY_S, ACTIVATION_POST_DELAY_S, QW_RELEASE_DELAY_S,
    COPY_CLIPBOARD_DELAY_S,
    OUTPUT_MONITOR_CHECK_INTERVAL_S, OUTPUT_MONITOR_CAPTURE_GAP_S,
    OUTPUT_MONITOR_CONSECUTIVE_STOPS, OUTPUT_MONITOR_PIXEL_DIFF_THRESHOLD,
    OUTPUT_MONITOR_MAX_DURATION_S,
)
from detector import (
    find_template, find_on_screen, check_on_screen,
    capture_screen, invalidate_screen_cache,
    batch_check, save_debug_screenshot,
)
from controller import (
    click, press_hotkey, paste_from_clipboard, type_enter,
    is_key_pressed, is_right_alt_pressed,
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

    WAIT_OUTPUT = "等待AI输出"
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


def _find_candidate_window():
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
        time.sleep(FOREGROUND_DELAY_S)
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
        bar_latencies = []
        proc_latencies = []
        for i in range(iterations):
            t0 = time.perf_counter()
            press_hotkey(list(ACTIVATE_HOTKEY))
            time.sleep(ACTIVATION_POST_DELAY_S)
            screen = capture_screen()
            for _ in range(20):
                if check_on_screen(screen, TEMPLATE_READY_TO_SPEAKING, confidence=0.6):
                    break
                time.sleep(0.1)
                screen = capture_screen()
            t1 = time.perf_counter()
            bar_latencies.append(t1 - t0)
            log.info("  辨识[%d/%d]: 语音条出现延迟=%.2fs", i + 1, iterations, t1 - t0)

            click_result = find_template(TEMPLATE_CONFIRM_BTN, confidence=0.6)
            if click_result:
                cx, cy = click_result["center"]
                click(cx, cy)
            t2 = time.perf_counter()
            screen = capture_screen()
            for _ in range(30):
                if check_on_screen(screen, TEMPLATE_COPY_BTN, confidence=0.6):
                    break
                time.sleep(0.1)
                screen = capture_screen()
            t3 = time.perf_counter()
            processing_time = t3 - t2
            proc_latencies.append(processing_time)
            log.info("  辨识[%d/%d]: 处理延迟=%.2fs", i + 1, iterations, processing_time)

        if bar_latencies:
            self._metrics["bar_latency_p50"] = float(np.median(bar_latencies))
            self._metrics["bar_latency_p95"] = float(np.percentile(bar_latencies, 95))
        if proc_latencies:
            self._metrics["processing_p50"] = float(np.median(proc_latencies))
            self._metrics["processing_p95"] = float(np.percentile(proc_latencies, 95))
        log.info("系统辨识完成: 语音条延迟 p50=%.2fs p95=%.2fs | 处理延迟 p50=%.2fs p95=%.2fs",
                 self._metrics.get("bar_latency_p50", 0),
                 self._metrics.get("bar_latency_p95", 0),
                 self._metrics.get("processing_p50", 0),
                 self._metrics.get("processing_p95", 0))
        self._identified = True

    @property
    def is_identified(self):
        return self._identified

    def get(self, key, default=None):
        return self._metrics.get(key, default)


_system_identifier = SystemIdentifier()


def _compare_screenshots(img1, img2) -> bool:
    try:
        import cv2 as _cv
        import numpy as _np
        a1 = _cv.cvtColor(_np.array(img1), _cv.COLOR_RGB2GRAY)
        a2 = _cv.cvtColor(_np.array(img2), _cv.COLOR_RGB2GRAY)
        h = min(a1.shape[0], a2.shape[0])
        a1 = a1[:int(h * 0.7), :]
        a2 = a2[:int(h * 0.7), :]
        if a1.shape != a2.shape:
            a2 = _cv.resize(a2, (a1.shape[1], a1.shape[0]))
        diff = _np.mean(_np.abs(a1.astype(float) - a2.astype(float)))
        return diff < OUTPUT_MONITOR_PIXEL_DIFF_THRESHOLD
    except Exception:
        return False


class _OutputMonitor:
    def __init__(self):
        self._thread = None
        self._running = False
        self._on_stop = None

    def start(self, on_stop_callback):
        self._on_stop = on_stop_callback
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="OutputMonitor")
        self._thread.start()
        log.info("AI输出监控已启动 (每%ds检查, 连续%d次无变化触发)",
                 OUTPUT_MONITOR_CHECK_INTERVAL_S, OUTPUT_MONITOR_CONSECUTIVE_STOPS)

    def stop(self):
        self._running = False

    def _run(self):
        consecutive = 0
        deadline = time.time() + OUTPUT_MONITOR_MAX_DURATION_S
        while self._running and time.time() < deadline:
            for _ in range(OUTPUT_MONITOR_CHECK_INTERVAL_S * 10):
                if not self._running:
                    return
                time.sleep(0.1)
            if not self._running:
                return
            screen1 = self._capture_active()
            for _ in range(OUTPUT_MONITOR_CAPTURE_GAP_S * 10):
                if not self._running:
                    return
                time.sleep(0.1)
            if not self._running:
                return
            screen2 = self._capture_active()
            if screen1 is None or screen2 is None:
                continue
            if _compare_screenshots(screen1, screen2):
                consecutive += 1
                log.info("输出停止检测[%d/%d]: 屏幕无变化", consecutive, OUTPUT_MONITOR_CONSECUTIVE_STOPS)
                if consecutive >= OUTPUT_MONITOR_CONSECUTIVE_STOPS:
                    log.info("输出已停止 (连续%d次无变化)", OUTPUT_MONITOR_CONSECUTIVE_STOPS)
                    if self._on_stop:
                        self._on_stop(screen2)
                    return
            else:
                if consecutive > 0:
                    log.info("输出停止检测: 屏幕有变化, 重置计数器")
                consecutive = 0

    @staticmethod
    def _capture_active():
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None
            rect = win32gui.GetWindowRect(hwnd)
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            if w < 200 or h < 100:
                return None
            import pyautogui as _pg
            return _pg.screenshot(region=rect)
        except Exception:
            return None


class _ZhipuWorkflow:
    def _do_activating(self):
        log.info("发送激活快捷键 %s", "+".join(ACTIVATE_HOTKEY))
        invalidate_screen_cache()
        press_hotkey(list(ACTIVATE_HOTKEY))
        time.sleep(ACTIVATION_POST_DELAY_S)
        self._waiting_bar_start = time.time()
        self._cycle_start = time.time()
        self._in_cycle = True

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
            processing_latency = _system_identifier.get("processing_p95") or _system_identifier.get("processing_p50") or 1.5
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
            processing_latency = time.time() - self._processing_start
            if self._in_cycle:
                self._metrics_runtime["processing_latencies"].append(processing_latency)
                if len(self._metrics_runtime["processing_latencies"]) > 30:
                    self._metrics_runtime["processing_latencies"].pop(0)
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
            time.sleep(COPY_CLIPBOARD_DELAY_S)
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


class _QianwenWorkflow:
    def _do_qw_monitoring_key(self):
        self._check_idle_timeout()
        if is_right_alt_pressed():
            if not self._qianwen_alt_pressed:
                self._qianwen_alt_pressed = True
                self._alt_release_processed = False
                log.info("千问: 右ALT按下，开始说话")
                self._speaking_start = time.time()
                self._transition(State.QW_SPEAKING)

    def _do_qw_speaking(self):
        if not is_right_alt_pressed():
            if not self._alt_release_processed:
                self._alt_release_processed = True
                self._qianwen_alt_pressed = False
                duration = time.time() - self._speaking_start
                log.info("千问: 右ALT松开 (说话时长=%.1fs)", duration)
                time.sleep(QW_RELEASE_DELAY_S)
                self._transition(State.QW_WAITING_INPUT)
            return

    def _do_qw_waiting_input(self):
        log.info("千问: 等待输入完成，准备按回车发送")
        self._transition(State.QW_ENTER_SEND)

    def _do_qw_enter_send(self):
        title, hwnd = _find_candidate_window()
        if hwnd:
            self.target_hwnd = hwnd
        log.info("千问: 切换到目标窗口并发送回车: %s", self.target_title)
        _set_foreground(self.target_hwnd)
        type_enter()
        log.info("千问: 已发送回车")
        play_success()

        if self._wake_enabled:
            self._schedule_idle_timeout()
        self._transition(State.QW_MONITORING_KEY)


class InputHelper(_ZhipuWorkflow, _QianwenWorkflow):
    MIN_SPEAKING_DURATION_S = 3.0
    SPEECH_END_STABLE_FRAMES = 5

    def __init__(self, region_learner=None, step_audio_client=None):
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
        self._error_count = 0
        self._max_error_backoff_s = 30.0
        self._metrics_runtime = {"bar_latencies": [], "processing_latencies": [], "match_fail_rate": 0.0, "total_cycles": 0, "successful_cycles": 0}
        self._cycle_start = 0.0
        self._in_cycle = False
        self._region_learner = region_learner
        self._step_audio_client = step_audio_client
        self._output_monitor = _OutputMonitor()

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

        title, hwnd = _find_candidate_window()
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

        self._output_monitor.start()
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
        self._output_monitor.stop()
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
            State.WAIT_OUTPUT: ADAPTIVE_MAX_INTERVAL_MS,
            State.ERROR: ADAPTIVE_MAX_INTERVAL_MS,
        }
        return state_intervals.get(self.state, CHECK_INTERVAL_MS)

    def _transition(self, new_state: State):
        if self.state != new_state:
            log.info("状态转换: %s -> %s", self.state.value, new_state.value)
            self.state = new_state
            if new_state != State.ERROR:
                self._error_count = 0
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
            State.WAIT_OUTPUT: self._do_wait_output,
            State.ERROR: self._do_error,
        }
        handler = handler_map.get(self.state)
        if handler:
            handler()

    # ========== 通用状态 ==========

    def _do_idle(self):
        pass

    def _do_wake_monitor(self):
        if self._check_idle_timeout():
            return
        pass

    # ========== 粘贴发送（共享） ==========

    def _do_paste_send(self):
        title, hwnd = _find_candidate_window()
        if hwnd and hwnd != self.target_hwnd:
            self.target_hwnd = hwnd
            self.target_title = title
            log.info("重新识别到目标窗口: %s", title)
        log.info("切换到目标窗口并粘贴发送: %s (hwnd=%s)", self.target_title, self.target_hwnd)
        _set_foreground(self.target_hwnd)
        clip_text = _get_clipboard_text()
        log.info("剪贴板内容长度: %d", len(clip_text) if clip_text else 0)
        paste_from_clipboard()
        time.sleep(PASTE_ENTER_DELAY_S)
        type_enter()
        log.info("已执行粘贴+回车")
        play_success()
        if self._in_cycle:
            self._metrics_runtime["total_cycles"] += 1
            self._metrics_runtime["successful_cycles"] += 1
            self._in_cycle = False

        if clip_text and len(clip_text) > 0:
            step_speak(clip_text[:500])

        log.info("开始监控AI输出...")
        self._output_monitor.start(on_stop_callback=self._on_output_stop)
        self._transition(State.WAIT_OUTPUT)

    def _do_wait_output(self):
        pass

    def _on_output_stop(self, latest_screenshot):
        log.info("AI输出已停止，开始OCR识别...")
        try:
            from ocr import extract_text
            text = extract_text(latest_screenshot)
            if text:
                log.info("OCR识别内容(%d字): %s...", len(text), text[:100])
                step_speak(text[:500])
            else:
                log.warning("OCR未识别到内容")
        except Exception as exc:
            log.warning("OCR播报失败: %s", exc)

        if self._wake_enabled:
            self._schedule_idle_timeout()
            self._pending_transition.put(State.WAKE_MONITOR)
        else:
            self._pending_transition.put(State.ACTIVATING if self._input_method == InputMethod.ZHIPU
                                          else State.QW_MONITORING_KEY)
        log.info("AI输出监控结束")

    # ========== 错误处理 ==========

    def _do_error(self):
        play_error()
        self._cancel_feedforward()
        self._error_count += 1
        backoff = min(self._max_error_backoff_s, self._error_count * 2.0)
        log.warning("错误恢复 backoff=%.1fs (连续错误=%d)", backoff, self._error_count)
        time.sleep(backoff)
        if self._wake_enabled:
            self._schedule_idle_timeout()
            self._transition(State.WAKE_MONITOR)
        else:
            self._transition(State.ACTIVATING if self._input_method == InputMethod.ZHIPU
                             else State.QW_MONITORING_KEY)
