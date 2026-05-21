from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

OUT_DIR = Path(__file__).parent / "templates"
OUT_DIR.mkdir(exist_ok=True)

DARK_BG = (32, 32, 32)
BAR_BG = (45, 45, 45)
WHITE = (255, 255, 255)
GRAY = (160, 160, 160)
DARK_GRAY = (80, 80, 80)
ORANGE = (255, 165, 0)


def get_font(size, bold=False):
    for name in ["simhei", "msyh", "arial"]:
        try:
            return ImageFont.truetype(f"{name}.ttf" if not bold else f"{name}bd.ttf", size)
        except Exception:
            pass
    try:
        return ImageFont.truetype("C:/Windows/Fonts/simhei.ttf", size)
    except Exception:
        try:
            return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)
        except Exception:
            return ImageFont.load_default()


def draw_rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    x1, y1, x2, y2 = xy
    w = x2 - x1
    h = y2 - y1
    if w < 2 * radius or h < 2 * radius:
        draw.rectangle(xy, fill=fill, outline=outline, width=width)
        return
    draw.ellipse([x1, y1, x1 + 2 * radius, y1 + 2 * radius], fill=fill, outline=outline, width=width)
    draw.ellipse([x2 - 2 * radius, y1, x2, y1 + 2 * radius], fill=fill, outline=outline, width=width)
    draw.ellipse([x1, y2 - 2 * radius, x1 + 2 * radius, y2], fill=fill, outline=outline, width=width)
    draw.ellipse([x2 - 2 * radius, y2 - 2 * radius, x2, y2], fill=fill, outline=outline, width=width)
    draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill, outline=None)
    draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill, outline=None)
    if outline:
        draw.line([x1 + radius, y1, x2 - radius, y1], fill=outline, width=width)
        draw.line([x1 + radius, y2, x2 - radius, y2], fill=outline, width=width)
        draw.line([x1, y1 + radius, x1, y2 - radius], fill=outline, width=width)
        draw.line([x2, y1 + radius, x2, y2 - radius], fill=outline, width=width)


def make_circle(size, fill, border, border_w=2):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = size // 2
    draw.ellipse([1, 1, size - 2, size - 2], fill=fill, outline=border, width=border_w)
    return img


def make_check_btn():
    img = make_circle(44, WHITE, (50, 50, 50), 2)
    draw = ImageDraw.Draw(img)
    font = get_font(28)
    bbox = draw.textbbox((0, 0), "✓", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((44 - tw) // 2 - bbox[0], (44 - th) // 2 - bbox[1]), "✓", fill=(50, 50, 50), font=font)
    return img


def make_x_btn():
    img = make_circle(36, (70, 70, 70), (85, 85, 85), 1)
    draw = ImageDraw.Draw(img)
    font = get_font(22)
    bbox = draw.textbbox((0, 0), "", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((36 - tw) // 2 - bbox[0], (36 - th) // 2 - bbox[1]), "✕", fill=WHITE, font=font)
    return img


def make_close_btn():
    img = make_circle(28, (45, 45, 45), (90, 90, 90), 1)
    draw = ImageDraw.Draw(img)
    font = get_font(16)
    bbox = draw.textbbox((0, 0), "✕", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((28 - tw) // 2 - bbox[0], (28 - th) // 2 - bbox[1]), "✕", fill=GRAY, font=font)
    return img


def make_copy_btn():
    img = make_circle(28, DARK_GRAY, (100, 100, 100), 1)
    draw = ImageDraw.Draw(img)
    s = 12
    cx, cy = 14, 14
    draw.rectangle([cx - 3, cy - 4, cx + 4, cy + 5], outline=WHITE, width=1)
    draw.rectangle([cx - 1, cy - 2, cx + 6, cy + 5], outline=WHITE, width=1)
    return img


# 1. start_speaking.png — 语音条「开始说话」
def make_start_speaking():
    w, h = 340, 56
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_rounded_rect(draw, [0, 0, w, h], 28, fill=BAR_BG, outline=(60, 60, 60), width=1)
    x_btn = make_x_btn()
    img.paste(x_btn, (10, (h - 36) // 2), x_btn)
    font = get_font(20)
    text = "开始说话"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (w - tw) // 2 - bbox[0]
    ty = (h - th) // 2 - bbox[1]
    draw.text((tx, ty), text, fill=GRAY, font=font)
    check = make_check_btn()
    img.paste(check, (w - 54, (h - 44) // 2), check)
    return img


# 2. processing.png — 语音条「处理中」
def make_processing():
    w, h = 340, 56
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_rounded_rect(draw, [0, 0, w, h], 28, fill=BAR_BG, outline=(60, 60, 60), width=1)
    x_btn = make_x_btn()
    img.paste(x_btn, (10, (h - 36) // 2), x_btn)
    font = get_font(20)
    text = "处理中"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (w - tw) // 2 - bbox[0]
    ty = (h - th) // 2 - bbox[1]
    draw.text((tx, ty), text, fill=GRAY, font=font)
    check = make_check_btn()
    img.paste(check, (w - 54, (h - 44) // 2), check)
    return img


# 3. confirm_btn.png — 对勾按钮
def make_confirm_btn():
    return make_check_btn()


# 4. copy_btn.png — 复制按钮
def make_copy_btn_img():
    return make_copy_btn()


# 5. close_btn.png — 关闭按钮
def make_close_btn_img():
    return make_close_btn()


TEMPLATES = {
    "ready_to_speaking.png": make_start_speaking,
    "processing.png": make_processing,
    "confirm_btn.png": make_confirm_btn,
    "copy_btn.png": make_copy_btn_img,
    "close_btn.png": make_close_btn_img,
}

for name, maker in TEMPLATES.items():
    img = maker()
    path = OUT_DIR / name
    img.save(str(path))
    print(f"  [OK] {name}  ({img.size[0]}x{img.size[1]})")

print(f"\n已生成 {len(TEMPLATES)} 个模板文件到 {OUT_DIR}")
