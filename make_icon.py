# -*- coding: utf-8 -*-
"""
make_icon.py —— 生成应用图标 assets/icon.ico（多尺寸）与 assets/icon.png

图标语义：深色画布上排列若干色块，其中一个色块被"抠"成透明（棋盘格）。
运行:  python make_icon.py
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

BG = (35, 38, 43, 255)          # #23262b 与界面背景一致
BLOCKS = [(255, 60, 60), (40, 160, 90), (66, 66, 66)]
ACCENT = (47, 111, 191)         # #2f6fbf 主题蓝

S = 512  # 以 512 为基准绘制，再降采样，天然获得抗锯齿


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return m


def checker(draw, box, cell):
    """在 box 内画棋盘格，表示"透明区域"。"""
    x0, y0, x1, y1 = box
    for j, y in enumerate(range(y0, y1, cell)):
        for i, x in enumerate(range(x0, x1, cell)):
            c = (210, 214, 220, 255) if (i + j) % 2 == 0 else (150, 156, 164, 255)
            draw.rectangle((x, y, min(x + cell, x1) - 1, min(y + cell, y1) - 1), fill=c)


def build(size=S):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    pad = int(size * 0.06)
    d.rounded_rectangle((pad, pad, size - pad - 1, size - pad - 1),
                        radius=int(size * 0.20), fill=BG)

    # 内描边，增强小尺寸下的轮廓
    d.rounded_rectangle((pad, pad, size - pad - 1, size - pad - 1),
                        radius=int(size * 0.20), outline=ACCENT, width=max(2, size // 90))

    # 2x2 色块网格：左上透明（棋盘格），另外三格实色
    gx0, gy0 = int(size * 0.20), int(size * 0.20)
    gx1, gy1 = int(size * 0.80), int(size * 0.80)
    gap = int(size * 0.035)
    cw = (gx1 - gx0 - gap) // 2
    ch = (gy1 - gy0 - gap) // 2
    r = int(size * 0.045)

    positions = [
        (gx0, gy0),                       # 左上 -> 透明
        (gx0 + cw + gap, gy0),            # 右上
        (gx0, gy0 + ch + gap),            # 左下
        (gx0 + cw + gap, gy0 + ch + gap), # 右下
    ]

    # 左上：棋盘格 + 蓝色虚线感边框
    tx, ty = positions[0]
    box = (tx, ty, tx + cw, ty + ch)
    checker(d, box, max(3, cw // 5))
    d.rounded_rectangle(box, radius=r, outline=ACCENT, width=max(2, size // 110))

    for (bx, by), col in zip(positions[1:], BLOCKS):
        d.rounded_rectangle((bx, by, bx + cw, by + ch), radius=r, fill=col + (255,))

    # 圆形蒙版裁掉外溢（已无外溢，保持直角边界干净）
    im.putalpha(Image.composite(im.getchannel("A"), Image.new("L", (size, size), 0),
                                rounded_mask(size, int(size * 0.20))))
    return im


def main():
    os.makedirs(ASSETS, exist_ok=True)
    im = build(S)

    png = os.path.join(ASSETS, "icon.png")
    im.resize((256, 256), Image.LANCZOS).save(png)

    ico = os.path.join(ASSETS, "icon.ico")
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    im.save(ico, format="ICO", sizes=sizes)

    print(f"[OK] {png}")
    print(f"[OK] {ico}  ({', '.join(str(s[0]) for s in sizes)})")


if __name__ == "__main__":
    main()
