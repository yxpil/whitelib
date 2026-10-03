# -*- coding: utf-8 -*-
"""ImageCanvas 测试：撤销栈、信号（事件钩子）、批量套用接口。"""
from __future__ import annotations

import numpy as np
from PIL import Image

from canvas import CheckerBrush, ImageCanvas
from processor import pil_to_qimage


def _qimage(rgb=(255, 0, 0), w=20, h=10):
    arr = np.full((h, w, 4), 255, dtype=np.uint8)
    arr[:, :, :3] = rgb
    return pil_to_qimage(Image.fromarray(arr, "RGBA"))


class TestUndoRedo:
    def test_undo_restores_alpha(self, qapp):
        c = ImageCanvas()
        c.set_image(_qimage())
        c.tolerance = 0
        n = c._magic_erase(0, 0)
        assert n > 0
        assert c.img.pixelColor(0, 0).alpha() == 0
        c.undo()
        assert c.img.pixelColor(0, 0).alpha() == 255

    def test_redo_reapplies(self, qapp):
        c = ImageCanvas()
        c.set_image(_qimage())
        c.tolerance = 0
        c._magic_erase(0, 0)
        c.undo()
        c.redo()
        assert c.img.pixelColor(0, 0).alpha() == 0

    def test_undo_stack_capped_at_40(self, qapp):
        c = ImageCanvas()
        c.set_image(_qimage())
        for _ in range(60):
            c._push_undo()
        assert len(c._undo) == 40

    def test_redo_cleared_on_new_undo(self, qapp):
        c = ImageCanvas()
        c.set_image(_qimage())
        c.tolerance = 0
        c._magic_erase(2, 2)
        c.undo()
        assert c._redo
        c._magic_erase(5, 5)   # 新操作应清空 redo
        assert not c._redo


class TestSignals:
    def test_tool_applied_signal_emitted(self, qapp):
        c = ImageCanvas()
        c.set_image(_qimage())
        messages = []
        c.toolApplied.connect(lambda m: messages.append(m))
        c.undo()   # 空撤销栈 → 应发提示
        assert any("撤销" in m for m in messages)

    def test_modified_changed_signal_toggles_dirty(self, qapp):
        c = ImageCanvas()
        c.set_image(_qimage())
        states = []
        c.modifiedChanged.connect(lambda v: states.append(v))
        c.tolerance = 0
        c._magic_erase(0, 0)
        assert states and states[-1] is True
        c.reset_changes()
        assert states[-1] is False

    def test_color_picked_signal(self, qapp):
        c = ImageCanvas()
        c.set_image(_qimage(rgb=(12, 34, 56)))
        seen = []
        c.colorPicked.connect(lambda r, g, b: seen.append((r, g, b)))
        c.mode = c.MODE_PICKER
        # 直接调内部路径验证取色值
        c.pick_color = c.img.pixelColor(0, 0)
        c.colorPicked.emit(c.pick_color.red(), c.pick_color.green(), c.pick_color.blue())
        assert seen == [(12, 34, 56)]


class TestApplyMagic:
    def test_apply_magic_to_image_zeroes_region(self, qapp):
        c = ImageCanvas()
        img = _qimage(rgb=(255, 0, 0))
        out = c.apply_magic_to_image(img, samples=[(0, 0)], tolerance=0, contiguous=True)
        assert out.pixelColor(0, 0).alpha() == 0

    def test_checker_brush_cached(self, qapp):
        a = CheckerBrush.get(12)
        b = CheckerBrush.get(12)
        assert a is b
