# -*- coding: utf-8 -*-
"""
selftest.py —— 无头自检

验证：窗口构建 → 加载图片 → 色块点击 → 撤销/重做 → 橡皮擦 → 视图变换
      → 采样点 → 批量处理 → 导出结果 → 界面截图

运行:  python selftest.py
"""
import functools
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
print = functools.partial(__builtins__.print, flush=True)

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

HERE = os.path.dirname(os.path.abspath(__file__))
TEST_PNG = os.path.join(HERE, "test_image.png")


def ensure_test_image():
    if not os.path.exists(TEST_PNG):
        sys.path.insert(0, HERE)
        import make_test_image  # noqa: F401


def main():
    ensure_test_image()

    import main as app_main
    from batch_dialog import BatchDialog
    from processor import MagicSpec, load_image_array, save_array

    app = QApplication(sys.argv)
    app.setStyleSheet(app_main.APP_QSS)

    w = app_main.MainWindow()
    w.resize(1360, 860)
    w.show()
    app.processEvents()
    print("[1] 主窗口构建完成")

    w.add_files([TEST_PNG])
    app.processEvents()
    assert w.current_index == 0, "图片未加载"
    print(f"[2] 图片加载成功: {w.canvas.img.width()}x{w.canvas.img.height()}")

    # --- 色块点击
    w.sp_tol.setValue(5)
    w.cmb_mode.setCurrentIndex(0)
    n = w.canvas._magic_erase(190, 170)          # 红色块
    app.processEvents()
    assert n > 30000, f"色块点击未生效 (n={n})"
    assert w.canvas.img.pixelColor(190, 170).alpha() == 0, "目标像素未透明"
    print(f"[3] 色块点击: 透明化 {n:,} 像素, alpha={w.canvas.img.pixelColor(190,170).alpha()}")

    # --- 撤销 / 重做
    w.canvas.undo(); app.processEvents()
    assert w.canvas.img.pixelColor(190, 170).alpha() == 255, "撤销失败"
    w.canvas.redo(); app.processEvents()
    assert w.canvas.img.pixelColor(190, 170).alpha() == 0, "重做失败"
    print("[4] 撤销 / 重做 正常")

    # --- 橡皮擦 + 羽化
    w.canvas.brush_radius = 15
    w.canvas.feather = 3
    w.canvas._erase_at(400, 300, erase=True)
    app.processEvents()
    a_center = w.canvas.img.pixelColor(400, 300).alpha()
    assert a_center < 255, "橡皮擦失败"
    print(f"[5] 橡皮擦(含羽化) 正常: 中心 alpha={a_center}")

    # --- 还原笔刷
    w.canvas._erase_at(400, 300, erase=False)
    app.processEvents()
    print(f"[6] 还原笔刷 正常: alpha={w.canvas.img.pixelColor(400,300).alpha()}")

    # --- 全局同色模式
    w.cmb_mode.setCurrentIndex(1)
    app.processEvents()
    assert w.canvas.contiguous is False
    w.cmb_mode.setCurrentIndex(0)
    print("[7] 匹配范围切换 正常")

    # --- 视图
    for fn in (w.canvas.zoom_in, w.canvas.zoom_out, w.canvas.zoom_100, w.canvas.fit_to_window):
        fn(); app.processEvents()
    print(f"[8] 视图变换 正常 (scale={w.canvas.scale:.4f})")

    # --- 采样点
    w.add_sample(0.2375, 0.2833, (255, 60, 60))
    w.clear_samples()
    w.add_sample(0.2375, 0.7000, (40, 160, 90))
    w.add_sample(0.5500, 0.2833, (66, 66, 66))
    assert len(w.spec.samples) == 2, f"采样点数异常: {len(w.spec.samples)}"
    print(f"[9] 采样点管理 正常: {w.spec.samples}")

    # --- 界面截图
    shot = os.path.join(HERE, "_screenshot.png")
    w.grab().save(shot)
    print(f"[10] 界面截图: {shot}")

    # --- 批量处理（同步直调，避免依赖事件循环）
    out_dir = os.path.join(HERE, "_batch_out")
    os.makedirs(out_dir, exist_ok=True)
    spec = MagicSpec(samples=w.spec.samples, tolerance=5, contiguous=True)
    arr = load_image_array(TEST_PNG)
    h, wd = arr.shape[0], arr.shape[1]
    samples_px = spec.sample_pixels(wd, h)
    from processor import erase_color_blocks
    total = erase_color_blocks(arr, samples_px, spec.tolerance, spec.contiguous)
    out_png = os.path.join(out_dir, "test_clear.png")
    save_array(arr, out_png)
    assert total > 0, "批量处理未产生效果"
    print(f"[11] 批量处理 正常: 累计透明 {total:,} 像素 → {out_png}")

    # --- 验证输出：被点的色块透明，其余区域保持不透明
    check = load_image_array(out_png)
    assert check.shape[2] == 4, "输出无 alpha 通道"
    n_trans = int((check[:, :, 3] == 0).sum())
    assert n_trans == total, f"透明像素数不符: 输出 {n_trans} vs 处理 {total}"
    assert check[10, 10, 3] == 255, "白色背景被误伤（应保持不透明）"
    print(f"[12] 输出验证: 透明 {n_trans:,} 像素与处理数一致, 白色背景未误伤, "
          f"尺寸 {check.shape[1]}x{check.shape[0]}")

    print("\n===== 全部自检通过 =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
