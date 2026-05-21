from PIL import Image, ImageDraw


def create_app_icon(size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = size * 0.06
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill="#4A90D9", outline="#2C5F8A", width=max(2, int(size * 0.03))
    )
    cx, cy = size / 2, size / 2
    s = size * 0.18
    draw.polygon(
        [(cx - s * 0.6, cy - s), (cx - s * 0.6, cy + s * 0.2), (cx + s * 1.0, cy - s * 0.4)],
        fill="white"
    )
    mic_w = size * 0.25
    mic_h = size * 0.06
    mic_y = cy + s * 0.4
    draw.rounded_rectangle(
        [cx - mic_w / 2, mic_y, cx + mic_w / 2, mic_y + mic_h],
        radius=int(mic_h / 2), fill="white"
    )
    return img


if __name__ == "__main__":
    icon = create_app_icon(256)
    icon.save("app_icon.png")
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon_ico = create_app_icon(256)
    icon_ico.save("app_icon.ico", sizes=ico_sizes)
    print("图标已生成: app_icon.png, app_icon.ico")
