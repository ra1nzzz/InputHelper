# -*- coding: utf-8 -*-
"""
妙语 VoxWise - Settings Dialog (V3)
设计预览 V3.0 -> tkinter ttk 落地
"""
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from PIL import Image, ImageTk

from settings import load, save, all_settings, set_auto_start, is_auto_start_enabled, set_val
from config import log, DATA_DIR

_root = None
_window = None
_start_callback = None
_stop_callback = None
_quit_callback = None

_QR_DIR = DATA_DIR


def set_quit_callback(cb):
    global _quit_callback
    _quit_callback = cb


def get_root():
    global _root
    if _root is None:
        _root = tk.Tk()
        _root.withdraw()
    return _root


class _SettingsDialog(tk.Toplevel):
    """妙语 VoxWise 设置窗口"""

    def __init__(self, parent, on_save_callback=None):
        super().__init__(parent)
        self.on_save = on_save_callback
        self.title("妙语 VoxWise 设置")
        self.geometry("520x620")
        self.resizable(False, False)
        self.configure(background="#f3f3f3")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self._on_close())

        self._activate_var     = tk.StringVar(value="Alt+Space")
        self._trigger_var      = tk.StringVar(value="Ctrl+Alt+V")
        self._frames_var       = tk.IntVar(value=5)
        self._interval_var     = tk.IntVar(value=300)
        self._auto_start_var   = tk.BooleanVar(value=False)
        self._silent_var       = tk.BooleanVar(value=False)
        self._input_method_var = tk.StringVar(value="zhipu")
        self._wake_enabled_var  = tk.BooleanVar(value=False)
        self._wake_word_var     = tk.StringVar(value="开始输入")
        self._wake_timeout_var  = tk.IntVar(value=5)
        self._step_audio_enabled_var = tk.BooleanVar(value=False)
        self._step_audio_voice_var   = tk.StringVar(value="wenrounvsheng")
        self._step_audio_api_key_var = tk.StringVar(value="")

        self._capturing = False
        self._captured_keys = []
        self._capture_target = None
        self._qr_imgs = {}
        self._voice_preview_btns = []

        self._build()
        self._load_values()

    def _build(self):
        PAD = {"padx": 16, "pady": 4}
        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # Title bar with app icon
        title_frame = tk.Frame(main, bg="#ffffff", height=48)
        title_frame.pack(fill=tk.X, pady=(0, 8))
        title_frame.pack_propagate(False)
        try:
            icon_img = Image.open(str(_QR_DIR / "app_icon.png"))
            icon_img = icon_img.resize((24, 24), Image.LANCZOS)
            self._app_icon_tk = ImageTk.PhotoImage(icon_img)
            tk.Label(title_frame, image=self._app_icon_tk, bg="#ffffff").pack(
                side=tk.LEFT, padx=(8, 6), pady=12)
        except Exception:
            pass
        tk.Label(title_frame, text="语音输入助手 设置",
                 font=("Microsoft YaHei UI", 14, "bold"),
                 bg="#ffffff", fg="#1a1a1a").pack(side=tk.LEFT, pady=12)

        # Notebook (4 tabs)
        self._notebook = ttk.Notebook(main)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        tab_basic = ttk.Frame(self._notebook, padding=10)
        tab_wake  = ttk.Frame(self._notebook, padding=10)
        tab_voice = ttk.Frame(self._notebook, padding=10)
        tab_about = ttk.Frame(self._notebook, padding=10)

        self._notebook.add(tab_basic, text="基本设置")
        self._notebook.add(tab_wake,  text="唤醒词")
        self._notebook.add(tab_voice, text="语音播报")
        self._notebook.add(tab_about, text="关于")

        self._build_basic_tab(tab_basic)
        self._build_wake_tab(tab_wake)
        self._build_voice_tab(tab_voice)
        self._build_about_tab(tab_about)

        # Footer buttons
        ttk.Separator(main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        action = ttk.Frame(main)
        action.pack(fill=tk.X, padx=16)
        self._start_btn = ttk.Button(action, text="▶ 开始语音输入", width=18, command=self._on_start)
        self._start_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(action, text="保存设置", width=10, command=self._on_save).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(action, text="最小化",   width=8,  command=self._on_close).pack(side=tk.LEFT)

    # ── Tab 1: 基本设置 ──────────────────────────────
    def _build_basic_tab(self, tab):
        PAD = {"padx": 8, "pady": 4}

        # 输入法选择
        grp = ttk.LabelFrame(tab, text=" 输入法选择 ", padding=10)
        grp.pack(fill=tk.X, **PAD)
        im_row = ttk.Frame(grp); im_row.pack(fill=tk.X)
        ttk.Radiobutton(im_row, text="智谱AI输入法",
            variable=self._input_method_var, value="zhipu",
            command=self._on_input_method_change).pack(side=tk.LEFT, padx=(0, 24))
        ttk.Radiobutton(im_row, text="千问语音输入（千问客户端自带）",
            variable=self._input_method_var, value="qianwen",
            command=self._on_input_method_change).pack(side=tk.LEFT)
        ttk.Label(grp, text="（千问：按住右 ALT 键说话，松开自动输入文字）",
            font=("Microsoft YaHei UI", 8), foreground="gray").pack(anchor=tk.W, padx=4, pady=(4, 0))

        # 快捷键
        grp2 = ttk.LabelFrame(tab, text=" 快捷键 ", padding=10)
        grp2.pack(fill=tk.X, **PAD)
        def _hotkey_row(p, lbl, var, cmd, hint, target=None):
            r = ttk.Frame(p); r.pack(fill=tk.X, pady=3)
            ttk.Label(r, text=lbl, width=16).pack(side=tk.LEFT)
            entry = ttk.Entry(r, textvariable=var, width=16, state="readonly",
                              font=("Consolas", 10))
            entry.pack(side=tk.LEFT, padx=(4, 4))
            btn = ttk.Button(r, text="录制", width=5, command=cmd)
            btn.pack(side=tk.LEFT, padx=(0, 4))
            ttk.Label(r, text=hint, font=("Microsoft YaHei UI", 8),
                      foreground="gray").pack(side=tk.LEFT)
            if target == "activate":
                self._activate_entry = entry
                self._activate_btn = btn
            elif target == "trigger":
                self._trigger_entry = entry
                self._trigger_btn = btn
        _hotkey_row(grp2, "语音激活快捷键:", self._activate_var,
                    lambda: self._start_capture("activate"), "（智谱/千问语音）", target="activate")
        _hotkey_row(grp2, "助手触发快捷键:", self._trigger_var,
                    lambda: self._start_capture("trigger"), "（本助手）", target="trigger")

        # 检测参数
        grp3 = ttk.LabelFrame(tab, text=" 检测参数 ", padding=10)
        grp3.pack(fill=tk.X, **PAD)
        r3 = ttk.Frame(grp3); r3.pack(fill=tk.X, pady=3)
        ttk.Label(r3, text="静音判定帧数:", width=16).pack(side=tk.LEFT)
        ttk.Spinbox(r3, from_=1, to=30, textvariable=self._frames_var,
                    width=6, font=("Consolas", 10)).pack(side=tk.LEFT, padx=(4, 4))
        ttk.Label(r3, text="（越大越不容易误判说完）",
                  font=("Microsoft YaHei UI", 8), foreground="gray").pack(side=tk.LEFT)
        r4 = ttk.Frame(grp3); r4.pack(fill=tk.X, pady=3)
        ttk.Label(r4, text="检测间隔 (ms):", width=16).pack(side=tk.LEFT)
        ttk.Spinbox(r4, from_=100, to=2000, increment=50,
                    textvariable=self._interval_var, width=6,
                    font=("Consolas", 10)).pack(side=tk.LEFT, padx=(4, 4))
        ttk.Label(r4, text="（越小反应越快但更耗 CPU）",
                  font=("Microsoft YaHei UI", 8), foreground="gray").pack(side=tk.LEFT)

        # 启动选项
        grp4 = ttk.LabelFrame(tab, text=" 启动选项 ", padding=10)
        grp4.pack(fill=tk.X, **PAD)
        ttk.Checkbutton(grp4, text="开机自动启动",
                        variable=self._auto_start_var).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(grp4, text="静默启动（仅显示托盘图标）",
                        variable=self._silent_var).pack(anchor=tk.W, pady=2)

    # ── Tab 2: 唤醒词 ────────────────────────────────
    def _build_wake_tab(self, tab):
        PAD = {"padx": 8, "pady": 4}
        enable_row = ttk.Frame(tab); enable_row.pack(fill=tk.X, **PAD)
        self._wake_check = ttk.Checkbutton(enable_row,
            text="启用唤醒词检测  （智谱AI模式）",
            variable=self._wake_enabled_var, command=self._on_wake_toggle)
        self._wake_check.pack(anchor=tk.W)
        ttk.Label(tab,
            text="启动后后台持续监听麦克风，说出唤醒词自动开始语音输入",
            font=("Microsoft YaHei UI", 8), foreground="gray").pack(
            anchor=tk.W, padx=24, pady=(0, 8))

        ww_row = ttk.Frame(tab); ww_row.pack(fill=tk.X, **PAD)
        ttk.Label(ww_row, text="唤醒词:", width=12).pack(side=tk.LEFT)
        self._wake_word_entry = ttk.Entry(ww_row, textvariable=self._wake_word_var,
                                          width=22, font=("Microsoft YaHei UI", 10))
        self._wake_word_entry.pack(side=tk.LEFT, padx=(4, 4))
        ttk.Label(ww_row, text="（说出这个词启动流程）",
                  font=("Microsoft YaHei UI", 8), foreground="gray").pack(side=tk.LEFT)

        to_row = ttk.Frame(tab); to_row.pack(fill=tk.X, **PAD)
        ttk.Label(to_row, text="空闲超时 (分钟):", width=12).pack(side=tk.LEFT)
        ttk.Spinbox(to_row, from_=1, to=60, textvariable=self._wake_timeout_var,
                    width=6, font=("Consolas", 10)).pack(side=tk.LEFT, padx=(4, 4))
        ttk.Label(to_row, text="（超过此时长无操作自动休眠）",
                  font=("Microsoft YaHei UI", 8), foreground="gray").pack(side=tk.LEFT)

        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Label(tab, text="使用说明",
                  font=("Microsoft YaHei UI", 9, "bold")).pack(anchor=tk.W, **PAD)
        info = ("1. 下载 VOSK 中文模型: https://alphacephei.com/vosk/models\n"
                "2. 推荐 vosk-model-small-cn-0.22（约 42MB）\n"
                "3. 解压至 InputHelper/vosk_model/ 目录\n"
                "4. 重启助手后唤醒词即可生效")
        ttk.Label(tab, text=info, font=("Microsoft YaHei UI", 8),
                  foreground="gray", justify=tk.LEFT).pack(
            anchor=tk.W, padx=16, pady=4)

    # ── Tab 3: 语音播报 ──────────────────────────────
    def _build_voice_tab(self, tab):
        PAD = {"padx": 8, "pady": 4}
        self._step_audio_check = ttk.Checkbutton(tab,
            text="启用 StepAudio 实时语音播报",
            variable=self._step_audio_enabled_var,
            command=self._on_step_audio_toggle)
        self._step_audio_check.pack(anchor=tk.W, **PAD)
        ttk.Label(tab,
            text="使用 stepaudio-2.5-realtime 模型低延迟播报识别结果，\n"
                 "适用于 VibeCoding 决策播报和好友聊天语音回复",
            font=("Microsoft YaHei UI", 8), foreground="gray",
            justify=tk.LEFT).pack(anchor=tk.W, padx=24, pady=(0, 8))

        voice_grp = ttk.LabelFrame(tab, text=" 播报音色 ", padding=10)
        voice_grp.pack(fill=tk.X, **PAD)
        self._voice_preview_btns = []
        for val, lbl in [("qingnianansheng", "青年男声"),
                          ("qingniannvsheng", "青年女声"),
                          ("cixingnansheng",  "磁性男声"),
                          ("wenrounvsheng",   "温柔女声")]:
            r = ttk.Frame(voice_grp); r.pack(fill=tk.X, pady=2)
            ttk.Radiobutton(r, text=lbl,
                            variable=self._step_audio_voice_var,
                            value=val).pack(side=tk.LEFT, padx=(0, 8))
            btn = ttk.Button(r, text="试听", width=5,
                             command=lambda v=val: self._preview_voice(v))
            btn.pack(side=tk.LEFT)
            self._voice_preview_btns.append(btn)

        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        api_row = ttk.Frame(tab); api_row.pack(fill=tk.X, **PAD)
        ttk.Label(api_row, text="API Key:", width=12).pack(side=tk.LEFT)
        self._api_key_entry = ttk.Entry(api_row,
            textvariable=self._step_audio_api_key_var, width=36,
            font=("Consolas", 9), show="*")
        self._api_key_entry.pack(side=tk.LEFT, padx=(4, 4))
        ttk.Label(api_row, text="* 必填", font=("Microsoft YaHei UI", 8),
                  foreground="#c42b1c").pack(side=tk.LEFT)

        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        ttk.Label(tab, text="技术说明",
                  font=("Microsoft YaHei UI", 9, "bold")).pack(anchor=tk.W, **PAD)
        ttk.Label(tab,
            text="• 使用 stepaudio-2.5-realtime 模型，非传统 TTS\n"
                 "• 优势：响应延迟更低，语音更自然有表现力\n"
                 "• 适用场景：VibeCoding 结果播报、聊天语音回复\n"
                 "• 需要网络连接，请自行申请 API Key",
            font=("Microsoft YaHei UI", 8), foreground="gray",
            justify=tk.LEFT).pack(anchor=tk.W, padx=16, pady=4)

    # ── Tab 4: 关于 ──────────────────────────────────
    def _build_about_tab(self, tab):
        PAD = {"padx": 8, "pady": 4}

        # App 标识
        id_row = tk.Frame(tab, bg="#ffffff")
        id_row.pack(fill=tk.X, pady=(4, 8))
        try:
            icon_big = Image.open(str(_QR_DIR / "app_icon.png"))
            icon_big = icon_big.resize((48, 48), Image.LANCZOS)
            self._app_icon_big_tk = ImageTk.PhotoImage(icon_big)
            tk.Label(id_row, image=self._app_icon_big_tk, bg="#ffffff").pack(
                side=tk.LEFT, padx=(8, 10))
        except Exception:
            pass
        name_col = tk.Frame(id_row, bg="#ffffff")
        name_col.pack(side=tk.LEFT)
        tk.Label(name_col, text="妙语 VoxWise",
                 font=("Microsoft YaHei UI", 18, "bold"),
                 bg="#ffffff", fg="#1a1a1a").pack(anchor=tk.W)
        tk.Label(name_col, text="语音输入小助手 v1.0 · MIT License",
                 font=("Microsoft YaHei UI", 9),
                 bg="#ffffff", fg="#8c8c8c").pack(anchor=tk.W)

        # 应用描述
        desc = ("妙语 VoxWise 是一款 Windows 桌面语音输入自动化工具，通过\n"
                "OpenCV 模板匹配 + VOSK 离线语音识别，\n"
                "支持智谱AI输入法 和 千问语音输入（千问客户端自带） 两种应用，\n"
                "可自由切换，让语音输入变得快速、精准、全自动。")
        ttk.Label(tab, text=desc, font=("Microsoft YaHei UI", 10),
                  foreground="#5c5c5c", justify=tk.CENTER).pack(
            fill=tk.X, pady=(0, 10))

        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)

        # 元信息
        meta_row = tk.Frame(tab); meta_row.pack(fill=tk.X, pady=8)
        for lbl, val in [("平台", "Windows"), ("语言", "Python 3.12"),
                          ("协议", "MIT"),      ("版本", "v1.0")]:
            cell = tk.Frame(meta_row); cell.pack(side=tk.LEFT, expand=True)
            tk.Label(cell, text=lbl, font=("Microsoft YaHei UI", 8),
                     fg="#8c8c8c").pack()
            tk.Label(cell, text=val, font=("Microsoft YaHei UI", 10, "bold"),
                     fg="#1a1a1a").pack()

        ttk.Separator(tab, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        # 赞赏区块
        tk.Label(tab, text="☕  赞赏支持",
                 font=("Microsoft YaHei UI", 11, "bold"),
                 fg="#1a1a1a").pack(pady=(8, 4))
        ttk.Label(tab,
            text="如果 妙语 VoxWise 帮到了你，欢迎打赏一杯咖啡 ☕\n"
                 "你的支持是持续改进的最大动力",
            font=("Microsoft YaHei UI", 8), foreground="gray",
            justify=tk.CENTER).pack(pady=(0, 10))

        qr_row = tk.Frame(tab); qr_row.pack(pady=4)
        for platform, fname in [("微信支付", "wechat_qr.png"),
                                ("支付宝",   "alipay_qr.png")]:
            cell = tk.Frame(qr_row); cell.pack(side=tk.LEFT, padx=20)
            tk.Label(cell, text=platform,
                     font=("Microsoft YaHei UI", 9),
                     fg="#5c5c5c").pack(pady=(0, 4))
            qr_container = tk.Frame(cell, width=130, height=130,
                                     relief="solid", bd=1.5, bg="#f5f5f5")
            qr_container.pack()
            qr_container.pack_propagate(False)
            try:
                qr_path = _QR_DIR / fname
                if qr_path.exists():
                    qr_img = Image.open(str(qr_path))
                    qr_img = qr_img.resize((128, 128), Image.LANCZOS)
                    qr_tk = ImageTk.PhotoImage(qr_img)
                    self._qr_imgs[platform] = qr_tk
                    tk.Label(qr_container, image=qr_tk, bg="#f5f5f5").pack(
                        expand=True)
                else:
                    tk.Label(qr_container,
                             text=f"[{platform}\n收款码]",
                             font=("Microsoft YaHei UI", 8),
                             fg="#aaa", bg="#f5f5f5",
                             justify=tk.CENTER).pack(expand=True)
            except Exception as exc:
                log.warning("加载二维码失败 [%s]: %s", platform, exc)
                tk.Label(qr_container, text="[加载失败]",
                         font=("Microsoft YaHei UI", 8),
                         fg="#c42b1c", bg="#f5f5f5").pack(expand=True)

        ttk.Label(tab,
            text="👆 扫一扫即可赞赏 · 感谢支持！",
            font=("Microsoft YaHei UI", 8), foreground="#8c8c8c").pack(
            pady=(10, 4))

    # ── 交互逻辑 ─────────────────────────────────────
    def _on_input_method_change(self):
        is_zhipu = self._input_method_var.get() == "zhipu"
        state = "normal" if is_zhipu else "disabled"
        for w in (self._activate_entry, self._activate_btn, self._wake_check):
            try: w.config(state=state)
            except tk.TclError: pass
        self._on_wake_toggle()

    def _on_wake_toggle(self):
        is_zhipu = self._input_method_var.get() == "zhipu"
        enabled = self._wake_enabled_var.get() and is_zhipu
        state = "normal" if enabled else "disabled"
        try: self._wake_word_entry.config(state=state)
        except tk.TclError: pass

    def _on_step_audio_toggle(self):
        enabled = self._step_audio_enabled_var.get()
        try:
            self._api_key_entry.config(
                state="normal" if enabled else "disabled")
        except tk.TclError: pass
        for b in self._voice_preview_btns:
            try: b.config(state="normal" if enabled else "disabled")
            except tk.TclError: pass

    def _start_capture(self, target):
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
        key_map = {
            "control_l": "ctrl", "control_r": "ctrl",
            "alt_l": "alt",       "alt_r": "alt",
            "shift_l": "shift",   "shift_r": "shift",
            "super_l": "win",     "super_r": "win",
        }
        key = key_map.get(key, key)
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
            var = (self._activate_var
                   if self._capture_target == "activate"
                   else self._trigger_var)
            var.set(display)

    def _preview_voice(self, voice):
        api_key = self._step_audio_api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("提示", "请先填写 API Key 再试听",
                                   parent=self)
            return
        import threading as _th
        try:
            from step_audio import preview_voice as _pv
            for b in self._voice_preview_btns:
                b.config(state="disabled")

            def _run():
                try:
                    _pv(voice, api_key)
                finally:
                    self.after(0,
                        lambda: [b.config(state="normal")
                                 for b in self._voice_preview_btns])

            _th.Thread(target=_run, daemon=True).start()
        except Exception as exc:
            messagebox.showerror("试听失败", str(exc), parent=self)

    def _on_start(self):
        _do_close_settings()
        if _start_callback:
            get_root().after(300, _start_callback)

    def _on_save(self):
        activate_str = self._activate_var.get()
        trigger_str  = self._trigger_var.get()
        if activate_str in ("", "请按下快捷键..."):
            messagebox.showwarning("提示", "请先录制语音激活快捷键",
                                   parent=self)
            return
        if trigger_str in ("", "请按下快捷键..."):
            messagebox.showwarning("提示", "请先录制助手触发快捷键",
                                   parent=self)
            return

        activate_list = [k.strip().lower()
                         for k in activate_str.split("+")]
        trigger_list  = [k.strip().lower()
                         for k in trigger_str.split("+")]
        auto_start = self._auto_start_var.get()
        silent     = self._silent_var.get()
        input_method = self._input_method_var.get()
        wake_enabled  = (self._wake_enabled_var.get()
                         and input_method == "zhipu")
        wake_word     = self._wake_word_var.get().strip()
        wake_timeout  = self._wake_timeout_var.get()
        step_enabled  = self._step_audio_enabled_var.get()
        step_voice    = self._step_audio_voice_var.get()
        step_api_key  = self._step_audio_api_key_var.get().strip()

        if step_enabled and not step_api_key:
            messagebox.showwarning(
                "提示", "启用 StepAudio 语音播报时 API Key 不能为空",
                parent=self)
            return
        if wake_enabled and not wake_word:
            messagebox.showwarning("提示", "启用唤醒词检测时唤醒词不能为空",
                                   parent=self)
            return
        if wake_timeout < 1:
            wake_timeout = 5

        save({
            "activate_hotkey":          activate_list,
            "trigger_hotkey":           trigger_list,
            "input_method":             input_method,
            "voice_done_stable_frames": self._frames_var.get(),
            "check_interval_ms":        self._interval_var.get(),
            "silent_start":             silent,
            "wake_word_enabled":        wake_enabled,
            "wake_word":                wake_word,
            "wake_idle_timeout_min":    wake_timeout,
            "step_audio_enabled":       step_enabled,
            "step_audio_voice":         step_voice,
            "step_audio_api_key":       step_api_key,
        })

        try:
            set_auto_start(auto_start)
        except Exception as exc:
            log.error("设置开机自启失败: %s", exc)
            messagebox.showerror("错误", f"设置开机自启失败:\n{exc}",
                                 parent=self)
            return

        if self.on_save:
            self.on_save()
        self._on_close()

    def _on_close(self):
        if self._capturing:
            self._capturing = False
            self.unbind("<KeyPress>")
            try:
                self.grab_release()
            except tk.TclError:
                pass
            self._activate_btn.config(state="normal")
            self._trigger_btn.config(state="normal")
        _do_close_settings()


# ── 公共 API ──────────────────────────────────────────
def show_settings(on_save_callback=None, on_start=None, on_stop=None):
    global _start_callback, _stop_callback
    _start_callback = on_start
    _stop_callback  = on_stop
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
    get_root().after(0, _do_close_settings)


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
    get_root().after(0, _do_ask_quit)


def _do_ask_quit():
    root = get_root()
    result = messagebox.askyesno("确认退出",
                                 "确定要退出 妙语VoxWise 吗？",
                                 parent=root)
    if result and _quit_callback:
        _quit_callback()


def set_quit_callback(cb):
    global _quit_callback
    _quit_callback = cb
