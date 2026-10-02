# -*- coding: utf-8 -*-
"""
processor.py —— 图片色块透明化的核心算法与批量处理

独立于 GUI，方便单独调用或做单元测试。

核心：以若干采样点为基准，把容差范围内、并且在空间上与之**相连**的像素
alpha 置 0（"色块连击"）。也可选择 non-contiguous 模式做全局同色去除。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
from PIL import Image
from PyQt5.QtGui import QImage

IMG_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif")
RAW_EXTS = (".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".rw2", ".orf", ".pef", ".srw")
ALL_EXTS = IMG_EXTS + RAW_EXTS


@dataclass
class MagicSpec:
    """色块透明化的参数。samples 使用**归一化坐标**(0~1)，便于跨不同尺寸图片复用。"""
    samples: list[tuple[float, float]] = field(default_factory=list)
    tolerance: int = 32
    contiguous: bool = True

    def sample_pixels(self, w: int, h: int) -> list[tuple[int, int]]:
        out = []
        for (nx, ny) in self.samples:
            out.append((int(round(nx * (w - 1))), int(round(ny * (h - 1)))))
        return out


# --------------------------------------------------------------------- 算法
def _flood_fill(colormask: np.ndarray, sx: int, sy: int) -> np.ndarray:
    """4 连通洪泛填充(行游程版本，比逐像素 BFS 快)。"""
    h, w = colormask.shape
    visited = np.zeros((h, w), dtype=bool)
    if not colormask[sy, sx]:
        return visited
    stack = [(sx, sy)]
    visited[sy, sx] = True
    while stack:
        x, y = stack.pop()
        xl = x
        while xl - 1 >= 0 and colormask[y, xl - 1] and not visited[y, xl - 1]:
            xl -= 1
            visited[y, xl] = True
        xr = x
        while xr + 1 < w and colormask[y, xr + 1] and not visited[y, xr + 1]:
            xr += 1
            visited[y, xr] = True
        for ny in (y - 1, y + 1):
            if ny < 0 or ny >= h:
                continue
            row = colormask[ny, xl:xr + 1]
            if not row.any():
                continue
            idxs = np.nonzero(row)[0]
            prev = -2
            for i in idxs:
                if i != prev + 1:
                    if not visited[ny, xl + i]:
                        visited[ny, xl + i] = True
                        stack.append((xl + i, ny))
                prev = i
    return visited


def erase_color_blocks(
    arr: np.ndarray,
    samples: list[tuple[int, int]],
    tolerance: int = 32,
    contiguous: bool = True,
) -> int:
    """
    原地修改 arr(HxWx4 uint8) 的 alpha。
    返回被置透明的像素总数。
    """
    h, w = arr.shape[0], arr.shape[1]
    total = 0
    for (sx, sy) in samples:
        sx = int(np.clip(sx, 0, w - 1))
        sy = int(np.clip(sy, 0, h - 1))
        target = arr[sy, sx, :3].astype(np.int16)
        diff = np.abs(arr[:, :, :3].astype(np.int16) - target)
        colormask = diff.max(axis=2) <= int(tolerance)
        mask = colormask if not contiguous else _flood_fill(colormask, sx, sy)
        n = int(mask.sum())
        if n:
            arr[mask, 3] = 0
            total += n
    return total


def pick_colors(arr: np.ndarray, samples: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    h, w = arr.shape[0], arr.shape[1]
    out = []
    for (sx, sy) in samples:
        sx = int(np.clip(sx, 0, w - 1))
        sy = int(np.clip(sy, 0, h - 1))
        out.append(tuple(int(v) for v in arr[sy, sx, :3]))
    return out


# ------------------------------------------------------------- 格式互转
def pil_to_qimage(im: Image.Image) -> QImage:
    im = im.convert("RGBA")
    # QImage 不持有 buffer 所有权：必须先 copy()，否则 bytes 被回收会段错误
    data = im.tobytes("raw", "RGBA")
    qimg = QImage(data, im.width, im.height, QImage.Format_RGBA8888)
    return qimg.copy()


def qimage_to_array(qimg: QImage) -> np.ndarray:
    """QImage → HxWx4 uint8 numpy 数组(已拷贝，安全)。"""
    if qimg.format() != QImage.Format_RGBA8888:
        qimg = qimg.convertToFormat(QImage.Format_RGBA8888)
    w, h = qimg.width(), qimg.height()
    ptr = qimg.bits()
    ptr.setsize(h * qimg.bytesPerLine())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, qimg.bytesPerLine() // 4, 4)
    return np.ascontiguousarray(arr[:, :w, :])


def qimage_to_pil(qimg: QImage) -> Image.Image:
    return Image.fromarray(qimage_to_array(qimg), "RGBA")


def load_image_array(path: str) -> np.ndarray:
    """读取图片为 HxWx4 uint8 numpy 数组。RAW 用 rawpy，失败则回退 Pillow。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in RAW_EXTS:
        try:
            import rawpy  # type: ignore
            with rawpy.imread(path) as raw:
                rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False)
            im = Image.fromarray(rgb).convert("RGBA")
            return np.array(im, dtype=np.uint8)
        except Exception:
            pass  # 回退
    im = Image.open(path)
    im = im.convert("RGBA")
    return np.array(im, dtype=np.uint8)


def save_array(arr: np.ndarray, path: str, quality: int = 95):
    """保存数组到文件。透明通道只对 png/webp 等生效；jpg 会合成白底。"""
    ext = os.path.splitext(path)[1].lower()
    im = Image.fromarray(arr, "RGBA")
    if ext in (".jpg", ".jpeg", ".bmp"):
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg.convert("RGB")
        im.save(path, quality=quality)
    elif ext == ".webp":
        im.save(path, quality=quality, method=6)
    else:
        im.save(path)
