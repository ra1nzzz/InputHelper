import sys
import time
import threading
from pathlib import Path
from PIL import Image, ImageDraw

from config import setup_logging, ensure_dirs, log, apply_settings, TRIGGER_HOTKEY, InputMethod, WAKE_WORD_ENABLED
from settings import load, get, get_input_method
from utils import set_dpi_aware

set_dpi_aware()
setup_logging()
ensure_dirs()
load()
apply_settings()


def _create_icon_image():
    icon_path = Path(__file__).parent / "app_icon.png"
    if icon_path.exists():
        return Image.open(str(icon_path)).resize((64, 64), Image.LANCZOS).convert("RGBA")
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill="#4A90D9", outline="#2C5F8A", width=2)
    draw.polygon([(22, 18), (22, 38), (42, 28)], fill="white")
    draw.ellipse([16, 38, 48, 46], fill="white")
    return img


def _create_icon_image_active():
    icon_path = Path(__file__).parent / "app_icon.png"
    if icon_path.exists():
        img = Image.open(str(icon_path)).resize((64, 64), Image.LANCZOS).convert("RGBA")
        colored = Image.new("RGBA", img.size, (0, 0, 0, 0))
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Color(img)
        return enhancer.enhance(1.3)
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill="#2ECC71", outline="#1A9C54", width=2)
    draw.polygon([(22, 18), (22, 38), (42, 28)], fill="white")
    draw.ellipse([16, 38, 48, 46], fill="white")
    return img


def _create_icon_image_wake():
    icon_path = Path(__file__).parent / "app_icon.png"
    if icon_path.exists():
        img = Image.open(str(icon_path)).resize((64, 64), Image.LANCZOS).convert("RGBA")
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Brightness(img)
        return enhancer.enhance(0.85)
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill="#F39C12", outline="#D68910", width=2)
    draw.polygon([(22, 18), (22, 38), (42, 28)], fill="white")
    draw.ellipse([16, 38, 48, 46], fill="white")
    return img


def main():
    import pystray
    import keyboard as kb
    from gui import get_root, show_settings, destroy_all, set_quit_callback
    from main import InputHelper, _system_identifier

    helper = None
    helper_thread = None
    icon_ref = [None]
    running_flag = [False]
    wake_mode_flag = [False]

    def _start_helper():
        nonlocal helper, helper_thread
        if helper is not None and helper_thread is not None and helper_thread.is_alive():
            log.info("助手已在运行，跳过")
            return
        from gui import _do_close_settings
        _do_close_settings()
        time.sleep(0.3)
        apply_settings()
        input_method = get_input_method()
        if input_method == InputMethod.ZHIPU:
            _system_identifier.identify(input_method)
        helper = InputHelper()
        helper_thread = threading.Thread(
            target=helper.start,
            args=(input_method,),
            daemon=True,
        )
        helper_thread.start()
        running_flag[0] = True
        wake_mode_flag[0] = WAKE_WORD_ENABLED
        _update_icon()
        log.info("助手线程已启动 (输入法=%s, 唤醒词=%s)", input_method.value, WAKE_WORD_ENABLED)

    def _stop_helper():
        nonlocal helper
        if helper is not None:
            helper.stop()
            helper = None
            running_flag[0] = False
            wake_mode_flag[0] = False
            _update_icon()
            log.info("助手已停止")

    def _update_icon():
        ic = icon_ref[0]
        if ic is None:
            return
        try:
            if wake_mode_flag[0] and not running_flag[0]:
                ic.icon = _create_icon_image_wake()
                ic.title = "InputHelper - 唤醒词监听中"
            elif running_flag[0]:
                ic.icon = _create_icon_image_active()
                ic.title = "InputHelper - 运行中"
            else:
                ic.icon = _create_icon_image()
                ic.title = "InputHelper - 已停止"
            ic.update_menu()
        except Exception:
            pass

    def _on_start(icon, item):
        _start_helper()

    def _on_stop(icon, item):
        _stop_helper()

    def _on_settings(icon, item):
        show_settings(
            on_save_callback=lambda: (_stop_helper(), _start_helper()),
            on_start=_start_helper,
            on_stop=_stop_helper,
        )

    def _on_quit(icon, item):
        from gui import ask_quit
        ask_quit()

    def _do_quit():
        _stop_helper()
        _unregister_trigger()
        ic = icon_ref[0]
        if ic is not None:
            threading.Thread(target=ic.stop, daemon=True).start()
        root.after(200, destroy_all)
        root.after(400, root.destroy)

    set_quit_callback(_do_quit)

    def _register_trigger():
        apply_settings()
        keys = list(TRIGGER_HOTKEY)
        hotkey_str = "+".join(keys)
        try:
            kb.add_hotkey(hotkey_str, _start_helper, suppress=False)
            log.info("已注册触发快捷键: %s", hotkey_str)
        except Exception as exc:
            log.warning("注册触发快捷键失败: %s", exc)

    def _unregister_trigger():
        try:
            keys = list(TRIGGER_HOTKEY)
            hotkey_str = "+".join(keys)
            kb.remove_hotkey(hotkey_str)
            log.info("已注销触发快捷键: %s", hotkey_str)
        except Exception:
            pass

    menu = pystray.Menu(
        pystray.MenuItem(
            "开始语音输入", _on_start, default=True,
            visible=lambda item: not running_flag[0]),
        pystray.MenuItem(
            "停止", _on_stop,
            visible=lambda item: running_flag[0]),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("设置", _on_settings),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", _on_quit),
    )

    icon = pystray.Icon(
        name="InputHelper",
        icon=_create_icon_image(),
        title="InputHelper - 智谱AI语音输入助手",
        menu=menu,
    )
    icon_ref[0] = icon

    tray_thread = threading.Thread(target=icon.run, daemon=True)
    tray_thread.start()
    log.info("托盘图标线程已启动")

    _register_trigger()

    root = get_root()
    root.withdraw()
    log.info("tkinter 主循环已启动")
    root.mainloop()

    _unregister_trigger()
    log.info("应用已退出")


if __name__ == "__main__":
    main()
