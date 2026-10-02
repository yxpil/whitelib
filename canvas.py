# -*- coding: utf-8 -*-
"""
canvas.py —— 图像画布组件

功能：
  - 显示图片，支持滚轮缩放、中键/空格拖拽平移
  - 吸管取色（点击像素取色）
  - 色块连击（容差内所有相连像素变透明）—— 核心功能
  - 手动橡皮擦（圆形笔刷，左键擦除 / 右键还原）
  - 棋盘格背景展示透明度
  - 撤销 / 重做（保存 alpha 通道历史）

坐标约定：内部一律使用图像原始像素坐标，绘制时做 scale/offset 变换。
"""
from __future__ import annotations

from collections import deque

import numpy as np
from PyQt5.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
)
from PyQt5.QtWidgets import QWidget


class CheckerBrush:
    """生成棋盘格 QBrush(懒加载 + 缓存)。"""

    _cache: dict[int, QBrush] = {}

    @classmethod
    def get(cls, cell: int = 12) -> QBrush:
        if cell not in cls._cache:
            size = cell * 2
            pm = QPixmap(size, size)
            pm.fill(QColor(58, 58, 62))
            p = QPainter(pm)
            p.fillRect(0, 0, cell, cell, QColor(74, 74, 80))
            p.fillRect(cell, cell, cell, cell, QColor(74, 74, 80))
            p.end()
            cls._cache[cell] = QBrush(pm)
        return cls._cache[cell]


class ImageCanvas(QWidget):
    """图像编辑画布。"""

    pixelHovered = pyqtSignal(int, int, int, int, int)  # x, y, r, g, b  (x=-1 表示超出)
    colorPicked = pyqtSignal(int, int, int)
    toolApplied = pyqtSignal(str)  # 操作描述，用于状态栏提示
    modifiedChanged = pyqtSignal(bool)

    MODE_ERASE = "erase"
    MODE_RESTORE = "restore"
    MODE_PICKER = "picker"
    MODE_MAGIC = "magic"

    MIN_SCALE = 0.05
    MAX_SCALE = 32.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(320, 240)

        self.base: QImage | None = None      # 原始图像(未改动，用于还原)
        self.img: QImage | None = None       # 当前图像 RGBA8888
        self._alpha0: np.ndarray | None = None  # 原始 alpha 快照

        self.scale = 1.0
        self.offset = QPointF(0.0, 0.0)

        self.mode = self.MODE_ERASE
        self.brush_radius = 20
        self.tolerance = 32
        self.contiguous = True
        self.feather = 0

        # 取色相关
        self.pick_color = QColor(255, 255, 255)

        # 交互状态
        self._painting = False
        self._panning = False
        self._pan_start = QPointF()
        self._pan_offset0 = QPointF()
        self._cursor_img_pos = QPointF()  # 光标在图像坐标系的位置
        self._inside = False

        # 撤销栈
        self._undo: list[np.ndarray] = []
        self._redo: list[np.ndarray] = []
        self._undo_limit = 40
        self._dirty = False

    # ------------------------------------------------------------------ 数据
    def set_image(self, image: QImage | None, reset_view: bool = True):
        """设置当前编辑的图片（会重置撤销栈）。"""
        if image is None or image.isNull():
            self.base = None
            self.img = None
            self._alpha0 = None
        else:
            # 统一转成 RGBA8888，方便直接操作内存
            if image.format() != QImage.Format_RGBA8888:
                image = image.convertToFormat(QImage.Format_RGBA8888)
            self.base = image.copy()
            self.img = image.copy()
            self._alpha0 = self._read_alpha()
        self._undo.clear()
        self._redo.clear()
        self._set_dirty(False)
        if reset_view:
            self.fit_to_window()
        self.update()

    def has_image(self) -> bool:
        return self.img is not None and not self.img.isNull()

    def image(self) -> QImage | None:
        return self.img

    def reset_changes(self):
        """还原到原始图像。"""
        if self.base is None:
            return
        self._push_undo()
        self.img = self.base.copy()
        self._set_dirty(False)
        self.update()
        self.toolApplied.emit("已还原为原图")

    def is_dirty(self) -> bool:
        return self._dirty

    def _set_dirty(self, value: bool):
        if self._dirty != value:
            self._dirty = value
            self.modifiedChanged.emit(value)

    # ------------------------------------------------------- alpha 读写工具
    def _read_alpha(self) -> np.ndarray:
        img = self.img
        w, h = img.width(), img.height()
        ptr = img.bits()
        ptr.setsize(h * img.bytesPerLine())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, img.bytesPerLine() // 4, 4)
        return arr[:, :w, 3].copy()

    def _write_alpha(self, alpha: np.ndarray):
        img = self.img
        w, h = img.width(), img.height()
        ptr = img.bits()
        ptr.setsize(h * img.bytesPerLine())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, img.bytesPerLine() // 4, 4)
        arr[:, :w, 3] = alpha
        self.img = img  # 触发? QImage 是隐式共享的，这里强制 detach

    def _rgb_array(self) -> np.ndarray:
        """返回 HxWx4 的 numpy 视图(只读使用)。"""
        img = self.img
        h, w = img.height(), img.width()
        ptr = img.bits()
        ptr.setsize(h * img.bytesPerLine())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, img.bytesPerLine() // 4, 4)
        return arr[:, :w, :]

    # --------------------------------------------------------------- 撤销
    def _push_undo(self):
        if self._alpha0 is None:
            return
        self._undo.append(self._alpha0.copy())
        if len(self._undo) > self._undo_limit:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self):
        if not self._undo:
            self.toolApplied.emit("没有可撤销的操作")
            return
        self._redo.append(self._alpha0.copy())
        self._alpha0 = self._undo.pop()
        self._write_alpha(self._alpha0)
        self._set_dirty(not np.array_equal(self._alpha0, self._read_base_alpha()))
        self.update()
        self.toolApplied.emit("撤销")

    def redo(self):
        if not self._redo:
            self.toolApplied.emit("没有可重做的操作")
            return
        self._undo.append(self._alpha0.copy())
        self._alpha0 = self._redo.pop()
        self._write_alpha(self._alpha0)
        self._set_dirty(not np.array_equal(self._alpha0, self._read_base_alpha()))
        self.update()
        self.toolApplied.emit("重做")

    def _read_base_alpha(self) -> np.ndarray:
        base = self.base
        h, w = base.height(), base.width()
        ptr = base.bits()
        ptr.setsize(h * base.bytesPerLine())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, base.bytesPerLine() // 4, 4)
        return arr[:, :w, 3]

    # ------------------------------------------------------------- 视图变换
    def fit_to_window(self):
        if not self.has_image():
            return
        iw, ih = self.img.width(), self.img.height()
        ww, wh = max(1, self.width() - 24), max(1, self.height() - 24)
        self.scale = min(ww / iw, wh / ih)
        self.scale = max(self.MIN_SCALE, min(self.MAX_SCALE, self.scale))
        self.offset = QPointF(
            (self.width() - iw * self.scale) / 2,
            (self.height() - ih * self.scale) / 2,
        )
        self.update()

    def zoom_in(self):
        self.zoom_at(QPointF(self.width() / 2, self.height() / 2), 1.25)

    def zoom_out(self):
        self.zoom_at(QPointF(self.width() / 2, self.height() / 2), 1 / 1.25)

    def zoom_100(self):
        if not self.has_image():
            return
        self.scale = 1.0
        self.offset = QPointF(
            (self.width() - self.img.width()) / 2,
            (self.height() - self.img.height()) / 2,
        )
        self.update()

    def zoom_at(self, pos: QPointF, factor: float):
        if not self.has_image():
            return
        old = self.scale
        new = max(self.MIN_SCALE, min(self.MAX_SCALE, old * factor))
        if abs(new - old) < 1e-9:
            return
        # 保持 pos 处的图像点不动
        img_pt = (pos - self.offset) / old
        self.scale = new
        self.offset = pos - img_pt * new
        self.update()

    def to_image_pos(self, widget_pos: QPointF) -> QPointF:
        return (widget_pos - self.offset) / self.scale

    def to_widget_pos(self, img_pos: QPointF) -> QPointF:
        return img_pos * self.scale + self.offset

    # ------------------------------------------------------------- 绘制
    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(42, 42, 46))

        if not self.has_image():
            p.setPen(QColor(140, 140, 148))
            p.drawText(self.rect(), Qt.AlignCenter, "拖入图片或点击「添加图片」开始")
            p.end()
            return

        iw, ih = self.img.width(), self.img.height()
        dst = QRectF(self.offset, self.offset + QPointF(iw * self.scale, ih * self.scale))

        # 棋盘格背景
        p.fillRect(dst, CheckerBrush.get(12))
        # 图像（平滑缩放）
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.scale < 4.0)
        p.drawImage(dst, self.img)

        # 外边框
        p.setPen(QPen(QColor(90, 90, 98), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(dst.adjusted(0, 0, -1, -1))

        # 笔刷 / 光标预览
        if self._inside and self.mode in (self.MODE_ERASE, self.MODE_RESTORE):
            r = self.brush_radius * self.scale
            center = self.to_widget_pos(self._cursor_img_pos)
            p.setRenderHint(QPainter.Antialiasing, True)
            color = QColor(255, 92, 92) if self.mode == self.MODE_ERASE else QColor(92, 200, 255)
            p.setPen(QPen(color, 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(center, r, r)
        elif self._inside and self.mode in (self.MODE_PICKER, self.MODE_MAGIC):
            center = self.to_widget_pos(self._cursor_img_pos)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(QColor(255, 255, 255), 1))
            p.drawLine(QPointF(center.x() - 9, center.y()), QPointF(center.x() - 3, center.y()))
            p.drawLine(QPointF(center.x() + 3, center.y()), QPointF(center.x() + 9, center.y()))
            p.drawLine(QPointF(center.x(), center.y() - 9), QPointF(center.x(), center.y() - 3))
            p.drawLine(QPointF(center.x(), center.y() + 3), QPointF(center.x(), center.y() + 9))
            if self.mode == self.MODE_MAGIC:
                p.setPen(QPen(QColor(255, 180, 60), 1.5))
                p.drawRect(QRectF(center.x() - 6, center.y() - 6, 12, 12))

        p.end()

    # ------------------------------------------------------------- 鼠标
    def mousePressEvent(self, event):
        if not self.has_image():
            return
        pos = QPointF(event.pos())

        # 平移：中键 / 空格+左键
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and event.modifiers() & Qt.ShiftModifier
        ):
            self._panning = True
            self._pan_start = pos
            self._pan_offset0 = QPointF(self.offset)
            self.setCursor(Qt.ClosedHandCursor)
            return

        img_pos = self.to_image_pos(pos)
        ix, iy = int(img_pos.x()), int(img_pos.y())
        if not self._in_bounds(ix, iy):
            return

        if self.mode == self.MODE_PICKER:
            c = self.img.pixelColor(ix, iy)
            self.pick_color = QColor(c.red(), c.green(), c.blue())
            self.colorPicked.emit(c.red(), c.green(), c.blue())
            self.toolApplied.emit(f"取色 RGB({c.red()}, {c.green()}, {c.blue()})")
            return

        if self.mode == self.MODE_MAGIC:
            if event.button() == Qt.RightButton:
                # 右键：反向 —— 把该色块外/透明区域还原？这里做“按颜色还原 alpha”
                self._restore_by_color(ix, iy)
            else:
                self._magic_erase(ix, iy)
            return

        # 橡皮擦 / 还原
        if self.mode == self.MODE_ERASE:
            if event.button() == Qt.LeftButton:
                self._push_undo()
                self._painting = True
                self._erase_at(ix, iy, erase=True)
            elif event.button() == Qt.RightButton:
                self._push_undo()
                self._painting = True
                self._erase_at(ix, iy, erase=False)
        elif self.mode == self.MODE_RESTORE:
            if event.button() in (Qt.LeftButton, Qt.RightButton):
                self._push_undo()
                self._painting = True
                self._erase_at(ix, iy, erase=False)

    def mouseMoveEvent(self, event):
        if not self.has_image():
            return
        pos = QPointF(event.pos())
        self._inside = True

        if self._panning:
            self.offset = self._pan_offset0 + (pos - self._pan_start)
            self.update()
            return

        img_pos = self.to_image_pos(pos)
        ix, iy = int(img_pos.x()), int(img_pos.y())
        self._cursor_img_pos = img_pos

        if self._in_bounds(ix, iy):
            c = self.img.pixelColor(ix, iy)
            self.pixelHovered.emit(ix, iy, c.red(), c.green(), c.blue())
        else:
            self.pixelHovered.emit(-1, -1, 0, 0, 0)

        if self._painting and self._in_bounds(ix, iy):
            self._erase_at(ix, iy, erase=(self.mode == self.MODE_ERASE))
        self.update()

    def mouseReleaseEvent(self, event):
        if self._panning:
            self._panning = False
            self.setCursor(Qt.CrossCursor)
            return
        if self._painting:
            self._painting = False
            self._set_dirty(True)
            self.update()

    def leaveEvent(self, event):
        self._inside = False
        self.update()

    def wheelEvent(self, event):
        if not self.has_image():
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        if event.modifiers() & Qt.ControlModifier:
            # Ctrl + 滚轮 = 调整笔刷大小
            step = max(1, int(self.brush_radius * 0.15))
            self.brush_radius = max(1, min(500, self.brush_radius + (step if delta > 0 else -step)))
            self.toolApplied.emit(f"笔刷半径 {self.brush_radius}px")
            self.update()
            return
        self.zoom_at(QPointF(event.pos()), factor)

    # ------------------------------------------------------- 图像处理核心
    def _in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.img.width() and 0 <= y < self.img.height()

    def _erase_at(self, x: int, y: int, erase: bool = True):
        """圆形笔刷擦除/还原 alpha。"""
        r = self.brush_radius
        h, w = self.img.height(), self.img.width()
        x0, x1 = max(0, x - r), min(w, x + r + 1)
        y0, y1 = max(0, y - r), min(h, y + r + 1)
        if x0 >= x1 or y0 >= y1:
            return
        yy, xx = np.ogrid[y0:y1, x0:x1]
        dist = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)

        if erase:
            mask = (dist <= r).astype(np.float32)
        else:
            mask = (dist <= r).astype(np.float32)

        # 羽化：边缘渐变
        f = max(0, self.feather)
        if f > 0:
            inner = np.clip((r - dist) / max(1.0, f), 0.0, 1.0)
            mask = inner.astype(np.float32)

        alpha = self._alpha0
        region = alpha[y0:y1, x0:x1].astype(np.float32)
        if erase:
            region = region * (1.0 - mask)
        else:
            # 还原：取「当前 alpha」与「原图 alpha × 笔刷强度」的较大者，
            # 避免羽化边缘反复涂抹留下残影
            base_region = self._read_base_alpha()[y0:y1, x0:x1].astype(np.float32)
            region = np.maximum(region, base_region * mask)
        alpha[y0:y1, x0:x1] = np.clip(region, 0, 255).astype(np.uint8)
        self._write_alpha(alpha)
        self.update()

    def _magic_erase(self, x: int, y: int) -> int:
        """
        连通色块透明化：以 (x, y) 像素颜色为基准，容差范围内所有**相连**的
        像素 alpha 置 0。若 contiguous=False，则全局同色像素全部透明化。
        返回受影响像素数量。
        """
        self._push_undo()
        arr = self._rgb_array()
        h, w = arr.shape[0], arr.shape[1]

        target = arr[y, x, :3].astype(np.int16)
        tol = int(self.tolerance)

        # 颜色距离（切比雪夫距离，快且直观）
        diff = np.abs(arr[:, :, :3].astype(np.int16) - target)
        colormask = (diff.max(axis=2) <= tol)

        if not self.contiguous:
            region = colormask
        else:
            region = self._flood_fill(colormask, x, y)

        count = int(region.sum())
        if count == 0:
            self.toolApplied.emit("未匹配到任何像素")
            return 0

        alpha = self._alpha0
        alpha[region] = 0
        self._write_alpha(alpha)
        self._set_dirty(True)
        self.update()
        self.toolApplied.emit(
            f"色块透明化：{count:,} 像素  RGB({target[0]}, {target[1]}, {target[2]})"
        )
        return count

    def _flood_fill(self, colormask: np.ndarray, sx: int, sy: int) -> np.ndarray:
        """
        基于 colormask 的 4 连通洪泛填充（NumPy 加速版本）。
        用扫描线 + 增量扩张，比纯 Python deque 快很多。
        """
        h, w = colormask.shape
        visited = np.zeros((h, w), dtype=bool)
        if not colormask[sy, sx]:
            return visited

        # 使用行内游程(span)填涂的 BFS，避免逐像素入队
        stack = [(sx, sy)]
        visited[sy, sx] = True
        while stack:
            x, y = stack.pop()

            # 向左、向右扩展当前行
            xl = x
            while xl - 1 >= 0 and colormask[y, xl - 1] and not visited[y, xl - 1]:
                xl -= 1
                visited[y, xl] = True
            xr = x
            while xr + 1 < w and colormask[y, xr + 1] and not visited[y, xr + 1]:
                xr += 1
                visited[y, xr] = True

            # 检查上下两行
            for ny in (y - 1, y + 1):
                if ny < 0 or ny >= h:
                    continue
                row = colormask[ny, xl:xr + 1]
                if not row.any():
                    continue
                idxs = np.nonzero(row)[0]
                # 把连续段里未被访问的起点入栈
                prev = -2
                for i in idxs:
                    if i != prev + 1:
                        if not visited[ny, xl + i]:
                            visited[ny, xl + i] = True
                            stack.append((xl + i, ny))
                    prev = i
        return visited

    def _restore_by_color(self, x: int, y: int) -> int:
        """反向操作：把与该像素同色(容差内)的像素 alpha 还原为原图 alpha。"""
        self._push_undo()
        arr = self._rgb_array()
        target = arr[y, x, :3].astype(np.int16)
        diff = np.abs(arr[:, :, :3].astype(np.int16) - target)
        colormask = (diff.max(axis=2) <= int(self.tolerance))
        count = int(colormask.sum())
        if count == 0:
            return 0
        alpha = self._alpha0
        base_alpha = self._read_base_alpha()
        alpha[colormask] = base_alpha[colormask]
        self._write_alpha(alpha)
        self._set_dirty(True)
        self.update()
        self.toolApplied.emit(f"按色还原：{count:,} 像素")
        return count

    # ------------------------------------------------ 供外部调用的批量接口
    def apply_magic_to_image(
        self,
        image: QImage,
        samples: list[tuple[int, int]],
        tolerance: int,
        contiguous: bool = True,
    ) -> QImage:
        """
        对任意图片执行色块透明化(用于批量套用到其它图片)。
        samples: 采样点列表 [(x, y), ...]，相对该图片的像素坐标。
        """
        if image.format() != QImage.Format_RGBA8888:
            image = image.convertToFormat(QImage.Format_RGBA8888)
        h, w = image.height(), image.width()
        ptr = image.bits()
        ptr.setsize(h * image.bytesPerLine())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, image.bytesPerLine() // 4, 4)
        arr = arr[:, :w, :]

        for (sx, sy) in samples:
            sx = int(np.clip(sx, 0, w - 1))
            sy = int(np.clip(sy, 0, h - 1))
            target = arr[sy, sx, :3].astype(np.int16)
            diff = np.abs(arr[:, :, :3].astype(np.int16) - target)
            colormask = (diff.max(axis=2) <= int(tolerance))
            if not contiguous:
                mask = colormask
            else:
                mask = self._flood_fill(colormask, sx, sy)
            arr[mask, 3] = 0
        return image
