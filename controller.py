import pyautogui
import time
import keyboard as kb
from config import log


def _release_modifiers():
    for key in ["ctrl", "alt", "shift", "windows"]:
        if kb.is_pressed(key):
            kb.release(key)
    time.sleep(0.05)


def press_hotkey(keys: list[str]):
    hotkey_str = "+".join(keys)
    log.info("发送快捷键: %s", hotkey_str)
    _release_modifiers()
    time.sleep(0.15)
    kb.send(hotkey_str, do_press=True, do_release=True)
    time.sleep(0.1)


def type_enter():
    _release_modifiers()
    time.sleep(0.05)
    pyautogui.press('enter')
    log.debug("已发送回车键")


def paste_from_clipboard():
    log.debug("执行粘贴")
    kb.send("ctrl+v")


def click(x: int, y: int, retries: int = 2, delay: float = 0.1):
    for attempt in range(retries):
        try:
            pyautogui.click(x, y)
            log.debug("点击 (%d, %d) 成功", x, y)
            return True
        except Exception:
            log.warning("点击 (%d, %d) 失败 (第%d次)", x, y, attempt + 1)
            if attempt < retries - 1:
                time.sleep(delay)
    return False


def is_key_pressed(key: str) -> bool:
    return kb.is_pressed(key)
