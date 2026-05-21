import tkinter as tk
from tkinter import ttk, messagebox
from settings import load, save, all_settings, set_auto_start, is_auto_start_enabled, set_val
from config import log

_root = None
_window = None
_start_callback = None
_stop_callback = None


def get_root():
    global _root
    if _root is None:
        _root = tk.Tk()
        _root.withdraw()
    return _root


def show_settings(on_save_callback=None, on_start=None, on_stop=None):
    global _start_callback, _stop_callback
    _start_callback = on_start
    _stop_callback = on_stop
    root = get_root()
    root.after(0, lambda: _do_show_settings(root, on_save_callback))


def _do_show_settings(root, on_save_callback):
    global _window
    if _window is not None:
        try:
            _window.deiconify()
            _window.lift()
            _window.focus_force()
            return
        except tk.TclError:
            _window = None

    _window = _SettingsDialog(root, on_save_callback)
    _window.deiconify()


def close_settings():
    root = get_root()
    root.after(0, _do_close_settings)


def _do_close_settings():
    global _window
    if _window is not None:
        try:
            _window.withdraw()
        except tk.TclError:
            _window = None


def destroy_all():
    global _window, _root
    if _window is not None:
        try:
            _window.destroy()
        except tk.TclError:
            pass
        _window = None
    if _root is not None:
        try:
            _root.destroy()
        except tk.TclError:
            pass
        _root = None


def ask_quit():
    root = get_root()
    root.after(0, _do_ask_quit)


def _do_ask_quit():
    root = get_root()
    result = messagebox.askyesno("确认退出", "确定要退出 InputHelper 吗？", parent=root)
    if result and _quit_callback:
        _quit_callback()


_quit_callback = None


def set_quit_callback(cb):
    global _quit_callback
    _quit_callback = cb


class _SettingsDialog(tk.Toplevel):
    def __init__(self, parent, on_save_callback=None):
        super().__init__(parent)
        self.on_save = on_save_callback
        self.title("InputHelper 设置")
        self.geometry("520x620")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self._on_close())

        self._activate_var = tk.StringVar(value="Alt+Space")
        self._trigger_var = tk.StringVar(value="Ctrl+Alt+V")
        self._frames_var = tk.IntVar(value=5)
        self._interval_var = tk.IntVar(value=300)
        self._auto_start_var = tk.BooleanVar(value=False)
        self._silent_var = tk.BooleanVar(value=False)
        self._input_method_var = tk.StringVar(value="zhipu")
        self._wake_enabled_var = tk.BooleanVar(value=False)
        self._wake_word_var = tk.StringVar(value="开始输入")
        self._wake_timeout_var = tk.IntVar(value=5)
        self._capturing = False
        self._captured_keys = []
        self._capture_target = None

        self._build()
        self._load_values()

    def _build(self):
        pad = {"padx": 16, "pady": 3}
        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="语音输入助手 设置", font=("Microsoft YaHei", 14, "bold")).pack(pady=(0, 10))

        notebook = ttk.Notebook(main)
        notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        tab1 = ttk.Frame(notebook, padding=8)
        notebook.add(tab1, text="基本设置")

        tab2 = ttk.Frame(notebook, padding=8)
        notebook.add(tab2, text="唤醒词")

        # ====== Tab 1: 基本设置 ======
        ttk.Label(tab1, text="输入法选择:", font=("Microsoft YaHei", 10)).pack(anchor=tk.W, **pad)
        im_frame = ttk.Frame(tab1)
        im_frame.pack(fill=tk.X, **pad)
        ttk.Radiobutton(im_frame, text="智谱AI输入法", variable=self._input_method_var,
                        value="zhipu", command=self._on_input_method_change).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Radiobutton(im_frame, text="千问语音输入", variable=self._input_method_var,
                        value="qianwen", command=self._on_input_method_change).pack(side=tk.LEFT)
        ttk.Label(tab1, text="(千问: 按住右ALT键说话，松开自动输入文字)",
                  font=("Microsoft YaHei", 8), foreground="gray").pack(anchor=tk.W, padx=16)

        ttk.Separator(tab1, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        row1 = ttk.Frame(tab1)
        row1.pack(fill=tk.X, **pad)
        ttk.Label(row1, text="语音激活快捷键:", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)
        self._activate_entry = ttk.Entry(row1, textvariable=self._activate_var, width=16, state="readonly",
                                         font=("Consolas", 10))
        self._activate_entry.pack(side=tk.LEFT, padx=(6, 4))
        self._activate_btn = ttk.Button(row1, text="录制", width=5,
                                        command=lambda: self._start_capture("activate"))
        self._activate_btn.pack(side=tk.LEFT)
        ttk.Label(row1, text="← 智谱/千问语音条", font=("Microsoft YaHei", 8), foreground="gray").pack(side=tk.LEFT, padx=4)

        row2 = ttk.Frame(tab1)
        row2.pack(fill=tk.X, **pad)
        ttk.Label(row2, text="助手触发快捷键:", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)
        self._trigger_entry = ttk.Entry(row2, textvariable=self._trigger_var, width=16, state="readonly",
                                        font=("Consolas", 10))
        self._trigger_entry.pack(side=tk.LEFT, padx=(6, 4))
        self._trigger_btn = ttk.Button(row2, text="录制", width=5,
                                       command=lambda: self._start_capture("trigger"))
        self._trigger_btn.pack(side=tk.LEFT)
        ttk.Label(row2, text="← 本助手", font=("Microsoft YaHei", 8), foreground="gray").pack(side=tk.LEFT, padx=4)

        ttk.Separator(tab1, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        row3 = ttk.Frame(tab1)
        row3.pack(fill=tk.X, **pad)
        ttk.Label(row3, text="静音判定帧数:", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)
        ttk.Spinbox(row3, from_=1, to=30, textvariable=self._frames_var, width=6,
                    font=("Consolas", 10)).pack(side=tk.LEFT, padx=(6, 4))
        ttk.Label(row3, text="(越大越不容易误判说完)", font=("Microsoft YaHei", 8),
                  foreground="gray").pack(side=tk.LEFT)

        row4 = ttk.Frame(tab1)
        row4.pack(fill=tk.X, **pad)
        ttk.Label(row4, text="检测间隔(ms):", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)
        ttk.Spinbox(row4, from_=100, to=2000, increment=50, textvariable=self._interval_var,
                    width=6, font=("Consolas", 10)).pack(side=tk.LEFT, padx=(6, 4))
        ttk.Label(row4, text="(越小反应越快但更耗CPU)", font=("Microsoft YaHei", 8),
                  foreground="gray").pack(side=tk.LEFT)

        ttk.Separator(tab1, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        self._auto_start_var = tk.BooleanVar(value=False)
        self._silent_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab1, text="开机自动启动", variable=self._auto_start_var).pack(anchor=tk.W, **pad)
        ttk.Checkbutton(tab1, text="静默启动（仅显示托盘图标）", variable=self._silent_var).pack(anchor=tk.W, **pad)

        # ====== Tab 2: 唤醒词 ======
        self._wake_check = ttk.Checkbutton(
            tab2, text="启用唤醒词检测（智谱AI模式）",
            variable=self._wake_enabled_var,
            command=self._on_wake_toggle,
        )
        self._wake_check.pack(anchor=tk.W, **pad)
        ttk.Label(tab2, text="启动后后台持续监听麦克风，说出唤醒词自动开始语音输入",
                  font=("Microsoft YaHei", 8), foreground="gray").pack(anchor=tk.W, padx=16)

        self._wake_word_frame = ttk.Frame(tab2)
        self._wake_word_frame.pack(fill=tk.X, **pad)
        ttk.Label(self._wake_word_frame, text="唤醒词:", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)
        self._wake_word_entry = ttk.Entry(self._wake_word_frame, textvariable=self._wake_word_var,
                                          width=20, font=("Microsoft YaHei", 10))
        self._wake_word_entry.pack(side=tk.LEFT, padx=(6, 4))
        ttk.Label(self._wake_word_frame, text="← 说出这个词启动流程",
                  font=("Microsoft YaHei", 8), foreground="gray").pack(side=tk.LEFT)

        row_timeout = ttk.Frame(tab2)
        row_timeout.pack(fill=tk.X, **pad)
        ttk.Label(row_timeout, text="空闲超时(分钟):", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)
        ttk.Spinbox(row_timeout, from_=1, to=60, textvariable=self._wake_timeout_var,
                    width=6, font=("Consolas", 10)).pack(side=tk.LEFT, padx=(6, 4))
        ttk.Label(row_timeout, text="(超过此时长无操作自动休眠)", font=("Microsoft YaHei", 8),
                  foreground="gray").pack(side=tk.LEFT)

        ttk.Separator(tab2, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=12)

        info_text = (
            "使用说明:\n"
            "1. 下载 VOSK 中文模型: https://alphacephei.com/vosk/models\n"
            "2. 推荐 vosk-model-small-cn-0.22 (约42MB)\n"
            "3. 解压到: InputHelper/vosk_model/ 目录\n"
            "4. 重启助手后唤醒词即可生效"
        )
        info_label = ttk.Label(tab2, text=info_text, font=("Microsoft YaHei", 8),
                               foreground="gray", justify=tk.LEFT)
        info_label.pack(anchor=tk.W, padx=16, pady=8)

        # ====== 底部按钮 ======
        ttk.Separator(main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        action_frame = ttk.Frame(main)
        action_frame.pack(fill=tk.X, padx=16)

        self._start_btn = ttk.Button(action_frame, text="▶ 开始语音输入", width=18, command=self._on_start)
        self._start_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._save_btn = ttk.Button(action_frame, text="保存设置", width=10, command=self._on_save)
        self._save_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(action_frame, text="最小化", width=8, command=self._on_close).pack(side=tk.LEFT)

    def _load_values(self):
        s = all_settings()
        activate = s.get("activate_hotkey", ["alt", "space"])
        self._activate_var.set("+".join(k.capitalize() for k in activate))
        trigger = s.get("trigger_hotkey", ["ctrl", "alt", "v"])
        self._trigger_var.set("+".join(k.capitalize() for k in trigger))
        self._frames_var.set(s.get("voice_done_stable_frames", 5))
        self._interval_var.set(s.get("check_interval_ms", 300))
        self._auto_start_var.set(is_auto_start_enabled())
        self._silent_var.set(s.get("silent_start", False))
        self._input_method_var.set(s.get("input_method", "zhipu"))
        self._wake_enabled_var.set(s.get("wake_word_enabled", False))
        self._wake_word_var.set(s.get("wake_word", "开始输入"))
        self._wake_timeout_var.set(s.get("wake_idle_timeout_min", 5))
        self._on_wake_toggle()
        self._on_input_method_change()

    def _on_input_method_change(self):
        is_zhipu = self._input_method_var.get() == "zhipu"
        state = "normal" if is_zhipu else "disabled"
        self._activate_entry.config(state=state)
        self._activate_btn.config(state=state)
        self._wake_check.config(state=state)
        self._on_wake_toggle()

    def _on_wake_toggle(self):
        is_zhipu = self._input_method_var.get() == "zhipu"
        enabled = self._wake_enabled_var.get() and is_zhipu
        state = "normal" if enabled else "disabled"
        for child in self._wake_word_frame.winfo_children():
            if isinstance(child, ttk.Entry):
                child.config(state=state)
            elif isinstance(child, ttk.Button):
                child.config(state=state)
        self._wake_word_entry.config(state=state)

    def _start_capture(self, target: str):
        self._capturing = True
        self._captured_keys = []
        self._capture_target = target
        var = self._activate_var if target == "activate" else self._trigger_var
        var.set("请按下快捷键...")
        self._activate_btn.config(state="disabled")
        self._trigger_btn.config(state="disabled")
        self.bind("<KeyPress>", self._on_key_press)
        self.focus_set()
        self.grab_set()

    def _on_key_press(self, event):
        if not self._capturing:
            return
        key = event.keysym.lower()
        if key in ("control_l", "control_r"):
            key = "ctrl"
        elif key in ("alt_l", "alt_r"):
            key = "alt"
        elif key in ("shift_l", "shift_r"):
            key = "shift"
        elif key in ("super_l", "super_r"):
            key = "win"

        if key in ("ctrl", "alt", "shift", "win"):
            if key not in self._captured_keys:
                self._captured_keys.append(key)
        else:
            self._captured_keys.append(key)
            self._capturing = False
            self.unbind("<KeyPress>")
            self.grab_release()
            self._activate_btn.config(state="normal")
            self._trigger_btn.config(state="normal")
            display = "+".join(k.capitalize() for k in self._captured_keys)
            var = self._activate_var if self._capture_target == "activate" else self._trigger_var
            var.set(display)

    def _on_start(self):
        _do_close_settings()
        if _start_callback:
            root = get_root()
            root.after(300, _start_callback)

    def _on_save(self):
        activate_str = self._activate_var.get()
        trigger_str = self._trigger_var.get()
        if activate_str in ("请按下快捷键...", ""):
            messagebox.showwarning("提示", "请先录制语音激活快捷键", parent=self)
            return
        if trigger_str in ("请按下快捷键...", ""):
            messagebox.showwarning("提示", "请先录制助手触发快捷键", parent=self)
            return

        activate_list = [k.strip().lower() for k in activate_str.split("+")]
        trigger_list = [k.strip().lower() for k in trigger_str.split("+")]
        frames = self._frames_var.get()
        interval = self._interval_var.get()
        auto_start = self._auto_start_var.get()
        silent = self._silent_var.get()
        input_method = self._input_method_var.get()
        wake_enabled = self._wake_enabled_var.get() and input_method == "zhipu"
        wake_word = self._wake_word_var.get().strip()
        wake_timeout = self._wake_timeout_var.get()

        if wake_enabled and not wake_word:
            messagebox.showwarning("提示", "启用唤醒词功能时，唤醒词不能为空", parent=self)
            return
        if wake_timeout < 1:
            wake_timeout = 5

        save({
            "activate_hotkey": activate_list,
            "trigger_hotkey": trigger_list,
            "input_method": input_method,
            "voice_done_stable_frames": frames,
            "check_interval_ms": interval,
            "silent_start": silent,
            "wake_word_enabled": wake_enabled,
            "wake_word": wake_word,
            "wake_idle_timeout_min": wake_timeout,
        })

        try:
            set_auto_start(auto_start)
        except Exception as exc:
            log.error("设置开机启动失败: %s", exc)
            messagebox.showerror("错误", f"设置开机启动失败:\n{exc}", parent=self)
            return

        if self.on_save:
            self.on_save()

        self._on_close()

    def _on_close(self):
        if self._capturing:
            self._capturing = False
            self.unbind("<KeyPress>")
            self.grab_release()
            self._activate_btn.config(state="normal")
            self._trigger_btn.config(state="normal")
        _do_close_settings()
