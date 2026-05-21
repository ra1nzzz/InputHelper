import tkinter as tk
from PIL import Image, ImageTk
import pyautogui
import time
from config import TEMPLATES_DIR, REQUIRED_TEMPLATES, setup_logging, ensure_dirs, log

setup_logging()
ensure_dirs()


class CaptureApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("InputHelper — 模板截图工具")
        self.root.geometry("520x480")
        self.root.resizable(False, False)
        self.screenshot = None
        self.photo = None
        self.crop_win = None
        self.canvas = None
        self.start_x = 0
        self.start_y = 0
        self.rect_id = None
        self.current_name = None
        self._build()

    def _build(self):
        tk.Label(self.root, text="模板截图工具", font=("Microsoft YaHei", 16, "bold")).pack(pady=(15, 5))
        tk.Label(self.root, text="依次截取智谱AI输入法界面元素，用于自动化识别", font=("Microsoft YaHei", 9)).pack(pady=(0, 10))

        self.frame = tk.Frame(self.root)
        self.frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

        self._refresh_list()

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="退出", width=12, command=self.root.destroy, font=("Microsoft YaHei", 10)).pack()

    def _refresh_list(self):
        for w in self.frame.winfo_children():
            w.destroy()
        for fname, desc in REQUIRED_TEMPLATES:
            exists = (TEMPLATES_DIR / fname).exists()
            row = tk.Frame(self.frame)
            row.pack(fill=tk.X, pady=3)
            tk.Button(
                row, text=f"截取: {desc}", width=36, anchor="w",
                font=("Microsoft YaHei", 9),
                command=lambda f=fname, d=desc: self._start_capture(f, d),
            ).pack(side=tk.LEFT)
            color = "green" if exists else "red"
            text = "✓ 已存在" if exists else "✗ 未截取"
            tk.Label(row, text=text, fg=color, font=("Microsoft YaHei", 9)).pack(side=tk.RIGHT, padx=8)

    def _start_capture(self, fname, desc):
        self.current_name = fname
        self.root.iconify()
        self.root.update()
        time.sleep(0.6)
        self.screenshot = pyautogui.screenshot()
        self._open_crop_window(desc)

    def _open_crop_window(self, desc):
        self.crop_win = tk.Toplevel(self.root)
        self.crop_win.attributes("-fullscreen", True)
        self.crop_win.attributes("-topmost", True)
        self.canvas = tk.Canvas(self.crop_win, cursor="cross")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.photo = ImageTk.PhotoImage(self.screenshot)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        sw = self.screenshot.width
        self.canvas.create_text(
            sw // 2, 28,
            text=f"请框选: {desc}    按 ESC 取消",
            fill="red", font=("Microsoft YaHei", 18, "bold"),
        )
        self.canvas.bind("<ButtonPress-1>", self._on_down)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_up)
        self.crop_win.bind("<Escape>", self._on_cancel)

    def _on_down(self, e):
        self.start_x, self.start_y = e.x, e.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=2)

    def _on_drag(self, e):
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, e.x, e.y)

    def _on_up(self, e):
        x1, y1 = min(self.start_x, e.x), min(self.start_y, e.y)
        x2, y2 = max(self.start_x, e.x), max(self.start_y, e.y)
        if x2 - x1 < 5 or y2 - y1 < 5:
            return
        cropped = self.screenshot.crop((x1, y1, x2, y2))
        save_path = TEMPLATES_DIR / self.current_name
        cropped.save(str(save_path))
        log.info("已保存模板: %s -> %s", self.current_name, save_path)
        self._close_crop()

    def _on_cancel(self, _e=None):
        self._close_crop()

    def _close_crop(self):
        if self.crop_win:
            self.crop_win.destroy()
            self.crop_win = None
        self.root.deiconify()
        self._refresh_list()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    CaptureApp().run()
