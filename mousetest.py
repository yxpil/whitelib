# -*- coding: utf-8 -*-
"""
mousetest.py —— 模拟真实鼠标事件，覆盖自检没走到的交互路径。

这个脚本存在的意义：pixelHovered 信号签名不匹配的 bug 是靠真机鼠标移动才暴露的，
而之前的 selftest 只调用了底层函数，绕过了 paintEvent/mouseMoveEvent 等 Qt 事件。
本脚本用 QTest 真正派发鼠标/滚轮事件，确保事件链路上的代码都被执行到。

运行:  python mousetest.py
"""
import functools
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
print = functools.partial(__builtins__.print, flush=True)

from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent, QWheelEvent
from PyQt5.QtWidgets import QApplication

HERE = os.path.dirname(os.path.abspath(__file__))
TEST_PNG = os.path.join(HERE, "test_image.png")


def send_mouse(widget, etype, x, y, button=Qt.NoButton, buttons=Qt.NoButton, mods=Qt.NoModifier):
    """构造并派发一个鼠标事件。"""
    pos = QPointF(float(x), float(y))
    gpos = widget.mapToGlobal(QPoint(int(x), int(y)))
    ev = QMouseEvent(etype, pos, gpos, button, buttons, mods)
    QApplication.sendEvent(widget, ev)
    return ev


def main():
    if not os.path.exists(TEST_PNG):
        import make_test_image  # noqa

    import main as app_main

    app = QApplication(sys.argv)
    app.setStyleSheet(app_main.APP_QSS)

    w = app_main.MainWindow()
    w.resize(1360, 860)
    w.show()
    app.processEvents()

    w.add_files([TEST_PNG])
    app.processEvents()
    c = w.canvas

    # 收集信号，确认 emit 的参数个数与类型都不炸
    received = {"hover": [], "pick": [], "tool": []}
    c.pixelHovered.connect(lambda *a: received["hover"].append(a))
    c.colorPicked.connect(lambda *a: received["pick"].append(a))
    c.toolApplied.connect(lambda *a: received["tool"].append(a))

    c.fit_to_window()
    app.processEvents()
    print(f"[1] canvas 尺寸 {c.width()}x{c.height()}, scale={c.scale:.4f}")

    # 把「图像坐标」换算成「窗口坐标」，方便精确点中色块
    def wp(ix, iy):
        p = c.to_widget_pos(QPointF(ix, iy))
        return p.x(), p.y()

    # --- 1. 悬停：这是之前崩溃的路径（pixelHovered 5 个参数）
    x, y = wp(190, 170)   # 红色块内部
    send_mouse(c, QMouseEvent.MouseMove, x, y)
    app.processEvents()
    assert len(received["hover"]) > 0, "悬停信号未触发"
    got = received["hover"][-1]
    assert len(got) == 5, f"pixelHovered 参数个数错误: {len(got)}"
    print(f"[2] 悬停信号正常: x={got[0]} y={got[1]} rgb=({got[2]},{got[3]},{got[4]})")
    assert w.lbl_color.text().startswith("RGB"), "状态栏未更新"
    print(f"[3] 状态栏显示: {w.lbl_pos.text()} | {w.lbl_color.text()}")

    # --- 2. 移出边界：走 -1 分支
    send_mouse(c, QMouseEvent.MouseMove, -50, -50)
    app.processEvents()
    print(f"[4] 越界悬停正常: {w.lbl_pos.text()} {w.lbl_color.text()}")

    # --- 3. 吸管取色（工具2）
    w.set_mode("picker")
    x, y = wp(190, 170)
    send_mouse(c, QMouseEvent.MouseButtonPress, x, y, Qt.LeftButton, Qt.LeftButton)
    send_mouse(c, QMouseEvent.MouseButtonRelease, x, y, Qt.LeftButton, Qt.NoButton)
    app.processEvents()
    assert len(received["pick"]) == 1, f"取色信号未触发: {received['pick']}"
    print(f"[5] 吸管取色正常: RGB{received['pick'][0]} → 采样点 {len(w.spec.samples)} 个")
    w.clear_samples()

    # --- 4. 色块点击（工具1）—— 核心功能，走完整鼠标路径
    w.set_mode("magic")
    w.sp_tol.setValue(5)
    x, y = wp(190, 170)
    send_mouse(c, QMouseEvent.MouseButtonPress, x, y, Qt.LeftButton, Qt.LeftButton)
    send_mouse(c, QMouseEvent.MouseButtonRelease, x, y, Qt.LeftButton, Qt.NoButton)
    app.processEvents()
    assert c.img.pixelColor(190, 170).alpha() == 0, "色块点击未生效"
    print(f"[6] 色块点击正常: alpha={c.img.pixelColor(190,170).alpha()}, "
          f"提示='{received['tool'][-1][0] if received['tool'] else ''}'")
    c.undo()

    # --- 5. 橡皮擦拖拽（按下 → 移动 → 抬起）
    w.set_mode("erase")
    c.brush_radius = 12
    x0, y0 = wp(190, 170)
    send_mouse(c, QMouseEvent.MouseButtonPress, x0, y0, Qt.LeftButton, Qt.LeftButton)
    for dx in range(0, 60, 6):
        send_mouse(c, QMouseEvent.MouseMove, x0 + dx, y0, Qt.NoButton, Qt.LeftButton)
    send_mouse(c, QMouseEvent.MouseButtonRelease, x0 + 60, y0, Qt.LeftButton, Qt.NoButton)
    app.processEvents()
    assert c.is_dirty(), "橡皮擦后未标记为已修改"
    print(f"[7] 橡皮擦拖拽正常: dirty={c.is_dirty()}, alpha={c.img.pixelColor(190,170).alpha()}")

    # --- 6. 右键还原
    send_mouse(c, QMouseEvent.MouseButtonPress, x0, y0, Qt.RightButton, Qt.RightButton)
    send_mouse(c, QMouseEvent.MouseButtonRelease, x0, y0, Qt.RightButton, Qt.NoButton)
    app.processEvents()
    print(f"[8] 右键还原正常: alpha={c.img.pixelColor(190,170).alpha()}")

    # --- 7. 中键平移
    ox = c.offset.x()
    send_mouse(c, QMouseEvent.MouseButtonPress, 400, 300, Qt.MiddleButton, Qt.MiddleButton)
    send_mouse(c, QMouseEvent.MouseMove, 460, 340, Qt.NoButton, Qt.MiddleButton)
    send_mouse(c, QMouseEvent.MouseButtonRelease, 460, 340, Qt.MiddleButton, Qt.NoButton)
    app.processEvents()
    assert abs(c.offset.x() - ox) > 1, "平移未生效"
    print(f"[9] 中键平移正常: offset.x {ox:.1f} → {c.offset.x():.1f}")

    # --- 8. 滚轮缩放
    s0 = c.scale
    wheel = QWheelEvent(
        QPointF(400, 300), c.mapToGlobal(QPoint(400, 300)),
        QPoint(0, 120), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
        Qt.ScrollUpdate, False,
    )
    QApplication.sendEvent(c, wheel)
    app.processEvents()
    assert c.scale > s0, "滚轮放大未生效"
    print(f"[10] 滚轮缩放正常: scale {s0:.4f} → {c.scale:.4f}")

    # --- 9. Ctrl+滚轮调笔刷
    r0 = c.brush_radius
    wheel2 = QWheelEvent(
        QPointF(400, 300), c.mapToGlobal(QPoint(400, 300)),
        QPoint(0, 120), QPoint(0, 120), Qt.NoButton, Qt.ControlModifier,
        Qt.ScrollUpdate, False,
    )
    QApplication.sendEvent(c, wheel2)
    app.processEvents()
    assert c.brush_radius > r0, "Ctrl+滚轮调笔刷未生效"
    print(f"[11] Ctrl+滚轮调笔刷正常: {r0} → {c.brush_radius}")

    # --- 10. 强制重绘 paintEvent（各模式下都画一遍）
    for mode in ("magic", "picker", "erase", "restore"):
        w.set_mode(mode)
        c._inside = True
        c._cursor_img_pos = QPointF(100, 100)
        c.repaint()
        app.processEvents()
    print("[12] 四种模式的 paintEvent 重绘正常")

    # --- 11. 键盘快捷键
    from PyQt5.QtGui import QKeyEvent
    for key, expect in ((Qt.Key_1, "magic"), (Qt.Key_2, "picker"),
                        (Qt.Key_3, "erase"), (Qt.Key_4, "restore")):
        QApplication.sendEvent(w, QKeyEvent(QKeyEvent.KeyPress, key, Qt.NoModifier))
        app.processEvents()
        assert c.mode == expect, f"快捷键 {key} 未切到 {expect}"
    print("[13] 键盘快捷键 1/2/3/4 正常")

    # --- 12. 全窗口截图（带真实交互痕迹）
    w.grab().save(os.path.join(HERE, "_mousetest.png"))
    print(f"[14] 截图: _mousetest.png")

    print("\n===== 鼠标/键盘交互测试全部通过 =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
