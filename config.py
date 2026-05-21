import sys
import logging
from pathlib import Path
from enum import Enum

def _resolve_resource_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).parent.resolve()

def _resolve_data_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()

RESOURCE_DIR = _resolve_resource_dir()
DATA_DIR = _resolve_data_dir()

TEMPLATES_DIR = RESOURCE_DIR / "templates"
LOGS_DIR = DATA_DIR / "logs"
SCREENSHOT_DIR = DATA_DIR / "_debug_screenshots"

_log_initialized = False


class InputMethod(Enum):
    ZHIPU = "zhipu"
    QIANWEN = "qianwen"


def ensure_dirs():
    TEMPLATES_DIR.mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)
    SCREENSHOT_DIR.mkdir(exist_ok=True)


def setup_logging():
    global _log_initialized
    if _log_initialized:
        return
    _log_initialized = True
    ensure_dirs()
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOGS_DIR / "input_helper.log", encoding="utf-8"),
        ],
    )
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("pystray").setLevel(logging.WARNING)


log = logging.getLogger("InputHelper")

# === 检测参数 ===
CHECK_INTERVAL_MS = 300
VOICE_DONE_STABLE_FRAMES = 5
PROCESSING_WAIT_TIMEOUT_S = 15
CLOSE_RETRY_COUNT = 2
CLOSE_INTERVAL_S = 0.3
PASTE_ENTER_DELAY_S = 0.5
WAITING_BAR_TIMEOUT_S = 10

# === 快捷键 ===
ACTIVATE_HOTKEY = ("alt", "space")
TRIGGER_HOTKEY = ("ctrl", "alt", "v")

# === 输入法选择 ===
INPUT_METHOD = InputMethod.ZHIPU

# === 唤醒词参数 ===
WAKE_WORD_ENABLED = False
WAKE_WORD = "开始输入"
WAKE_IDLE_TIMEOUT_MIN = 5

# === 多回路控制参数 ===

# === 自适应控制参数 ===
ADAPTIVE_MIN_INTERVAL_MS = 100
ADAPTIVE_MAX_INTERVAL_MS = 600

# === 系统辨识参数 ===

# === 模板匹配参数 ===
MULTI_SCALE_MATCH = True
MULTI_SCALE_RANGES = [0.9, 1.0, 1.1]

# === 声音参数 ===
SUCCESS_SOUND_FREQ = 880
SUCCESS_SOUND_DUR_MS = 200
START_SOUND_FREQ = 440
START_SOUND_DUR_MS = 150
ERROR_SOUND_FREQ = 330
ERROR_SOUND_DUR_MS = 300

# === 文本区域参数 ===
TEXT_REGION_PAD_X = 30
TEXT_REGION_PAD_Y = 10
TEXT_REGION_FROM_CONFIRM_OFFSET_X = 350
TEXT_REGION_FROM_CONFIRM_OFFSET_Y = 30
TEXT_REGION_FROM_CONFIRM_W = 300
TEXT_REGION_FROM_CONFIRM_H = 60

def apply_settings():
    global CHECK_INTERVAL_MS, VOICE_DONE_STABLE_FRAMES, ACTIVATE_HOTKEY, TRIGGER_HOTKEY
    global INPUT_METHOD, WAKE_WORD_ENABLED, WAKE_WORD, WAKE_IDLE_TIMEOUT_MIN
    global STEP_AUDIO_ENABLED, STEP_AUDIO_VOICE
    from settings import get
    INPUT_METHOD = InputMethod(get("input_method", "zhipu"))
    hotkey = get("activate_hotkey", ["alt", "space"])
    ACTIVATE_HOTKEY = tuple(hotkey)
    trigger = get("trigger_hotkey", ["ctrl", "alt", "v"])
    TRIGGER_HOTKEY = tuple(trigger)
    VOICE_DONE_STABLE_FRAMES = get("voice_done_stable_frames", 5)
    CHECK_INTERVAL_MS = get("check_interval_ms", 300)
    WAKE_WORD_ENABLED = get("wake_word_enabled", False)
    WAKE_WORD = get("wake_word", "开始输入")
    WAKE_IDLE_TIMEOUT_MIN = get("wake_idle_timeout_min", 5)
    STEP_AUDIO_ENABLED = get("step_audio_enabled", False)
    STEP_AUDIO_VOICE = get("step_audio_voice", "qingnianansheng")
    log.info("配置已应用: input_method=%s, 快捷键=%s/%s, 静音帧数=%d, 检测间隔=%dms, 唤醒词=%s/%s, StepAudio=%s/%s",
             INPUT_METHOD.value, "+".join(ACTIVATE_HOTKEY), "+".join(TRIGGER_HOTKEY),
             VOICE_DONE_STABLE_FRAMES, CHECK_INTERVAL_MS,
             WAKE_WORD if WAKE_WORD_ENABLED else "关闭",
             f"{WAKE_IDLE_TIMEOUT_MIN}min" if WAKE_WORD_ENABLED else "",
             "开" if STEP_AUDIO_ENABLED else "关", STEP_AUDIO_VOICE)

# === 模板文件名 ===
TEMPLATE_READY_TO_SPEAKING = "ready_to_speaking.png"
TEMPLATE_SPEECH_DONE = "speak_end.png"
TEMPLATE_PROCESSING = "processing.png"
TEMPLATE_CONFIRM_BTN = "confirm_btn.png"
TEMPLATE_COPY_BTN = "copy_btn.png"
TEMPLATE_CLOSE_BTN = "close_btn.png"

REQUIRED_TEMPLATES = [
    (TEMPLATE_READY_TO_SPEAKING, "语音条「开始说话」文字区域"),
    (TEMPLATE_SPEECH_DONE, "语音条发言完成（中间空白，仅X和对勾）"),
    (TEMPLATE_PROCESSING, "语音条「处理中」文字区域"),
    (TEMPLATE_CONFIRM_BTN, "语音条上的确认（✓ 对勾）按钮"),
    (TEMPLATE_COPY_BTN, "识别结果弹窗中的「复制」按钮"),
    (TEMPLATE_CLOSE_BTN, "识别结果弹窗中的「关闭」按钮"),
]

# === 前馈控制参数 (Feedforward Control) ===
FEEDFORWARD_ENABLED = True

# === StepAudio 实时播报参数 ===
STEP_AUDIO_ENABLED = False
STEP_AUDIO_VOICE = "qingnianansheng"
