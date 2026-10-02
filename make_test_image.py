# -*- coding: utf-8 -*-
"""生成一张测试图，方便快速验证功能。运行： python make_test_image.py"""
import numpy as np
from PIL import Image, ImageDraw

W, H = 800, 600
arr = np.zeros((H, W, 4), dtype=np.uint8)
arr[:, :, :3] = 245        # 近白色背景
arr[:, :, 3] = 255         # 背景不透明 —— 点击它即可体验"背景变透明"

# 画几个纯色块，其中两块颜色相近（用于测试容差）
im = Image.fromarray(arr, "RGBA")
d = ImageDraw.Draw(im)
d.rectangle([80, 80, 300, 260], fill=(255, 60, 60, 255))       # 红
d.rectangle([360, 80, 560, 260], fill=(66, 66, 66, 255))       # 深灰
d.ellipse([80, 320, 300, 520], fill=(40, 160, 90, 255))        # 绿
d.rectangle([360, 320, 560, 520], fill=(38, 158, 88, 255))     # 与绿色相近(测容差)

# 一些文字感线条
for i in range(0, 160, 12):
    d.line([600, 80 + i, 740, 80 + i], fill=(20, 20, 20, 255), width=3)

im.save("test_image.png")
print("已生成 test_image.png  800x600")
print("试试：容差设 10，点击绿色椭圆，相近的那块也会一起变透明。")
