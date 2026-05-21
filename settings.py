import json
import sys
import winreg
from pathlib import Path
from config import DATA_DIR, log, InputMethod

SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULTS = {
    "activate_hotkey": ["alt", "space"],
    "trigger_hotkey": ["ctrl", "alt", "v"],
    "input_method": "zhipu",
    "voice_done_stable_frames": 5,
    "check_interval_ms": 300,
    "auto_start": False,
    "silent_start": False,
    "wake_word_enabled": False,
    "wake_word": "开始输入",
    "wake_idle_timeout_min": 5,
    "step_audio_enabled": False,
    "step_audio_voice": "qingnianansheng",
}

_settings: dict = {}


def load() -> dict:
    global _settings
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            _settings = {**DEFAULTS, **saved}
        except Exception as exc:
            log.warning("读取设置失败，使用默认值: %s", exc)
            _settings = dict(DEFAULTS)
    else:
        _settings = dict(DEFAULTS)
    return _settings


def save(data: dict = None):
    global _settings
    if data is not None:
        _settings.update(data)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(_settings, f, indent=2, ensure_ascii=False)
    log.info("设置已保存")


def get(key: str, default=None):
    s = _settings if _settings else DEFAULTS
    return s.get(key, default if default is not None else DEFAULTS.get(key))


def set_val(key: str, value):
    if not _settings:
        load()
    _settings[key] = value


def all_settings() -> dict:
    return dict(_settings if _settings else DEFAULTS)


def get_input_method() -> InputMethod:
    v = get("input_method", "zhipu")
    try:
        return InputMethod(v)
    except ValueError:
        return InputMethod.ZHIPU


def is_auto_start_enabled() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, "InputHelper")
        winreg.CloseKey(key)
        return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_auto_start(enabled: bool):
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        if enabled:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path,
                                 0, winreg.KEY_WRITE)
            exe_path = sys.executable
            script_path = Path(__file__).parent / "tray_app.py"
            cmd = f'"{exe_path}" "{script_path}" --silent'
            winreg.SetValueEx(key, "InputHelper", 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
            log.info("已启用开机启动")
        else:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path,
                                 0, winreg.KEY_WRITE)
            try:
                winreg.DeleteValue(key, "InputHelper")
            except FileNotFoundError:
                pass
            winreg.CloseKey(key)
            log.info("已禁用开机启动")
    except Exception as exc:
        log.error("修改开机启动失败: %s", exc)
