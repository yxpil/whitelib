# -*- coding: utf-8 -*-
"""
主程序 —— 透明通道色块点击器

功能概览：
  · 批量导入图片（文件选择 / 文件夹 / 拖拽）
  · 画布上点击色块，容差范围内相连像素一键变透明
  · 吸管取色、橡皮擦、还原、撤销/重做、缩放平移
  · 把规则批量套用到所有导入的图片，输出到指定目录

依赖：PyQt5, Pillow, numpy
"""
from __future__ import annotations

import os
import sys


def resource_path(rel: str) -> str:
    """资源绝对路径；兼容 PyInstaller 打包（sys._MEIPASS）与源码运行。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


APP_VERSION = "1.0.0"

import numpy as np
from PIL import Image
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAction,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from batch_dialog import BatchDialog
from canvas import ImageCanvas
from processor import (
    ALL_EXTS,
    IMG_EXTS,
    RAW_EXTS,
    MagicSpec,
    load_image_array,
    pil_to_qimage,
    qimage_to_array,
    qimage_to_pil,
    save_array,
)


def make_swatch_icon(rgb: tuple[int, int, int], size: int = 16) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(*rgb))
    p = QPainter(pm)
    p.setPen(QColor(20, 20, 20))
    p.drawRect(0, 0, size - 1, size - 1)
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"透明通道色块点击器  ·  Color Block Transparency Tool  v{APP_VERSION}")
        self.resize(1360, 860)
        self.setAcceptDrops(True)

        self.files: list[str] = []
        self.current_index = -1
        self._thumbs: dict[str, QPixmap] = {}
        self.spec = MagicSpec(samples=[], tolerance=32, contiguous=True)

        self._build_ui()
        self._build_toolbar()
        self._load_settings()

    # =============================================================== UI
    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)

        # ---------------- 左侧：文件列表
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 4, 8)

        head = QHBoxLayout()
        title = QLabel("图片列表")
        f = QFont()
        f.setBold(True)
        title.setFont(f)
        head.addWidget(title)
        head.addStretch(1)
        self.lbl_count = QLabel("0 张")
        self.lbl_count.setStyleSheet("color:#8a8f98;")
        head.addWidget(self.lbl_count)
        ll.addLayout(head)

        self.list = QListWidget()
        self.list.setIconSize(QSize(72, 72))
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.currentRowChanged.connect(self.on_select)
        self.list.setStyleSheet(
            "QListWidget::item{height:78px;} QListWidget::item:selected{background:#2f6fbf;}"
        )
        ll.addWidget(self.list, 1)

        brow = QHBoxLayout()
        b_add = QPushButton("添加图片")
        b_addfile = QPushButton("添加文件夹")
        b_del = QPushButton("移除")
        b_clr = QPushButton("清空")
        b_add.clicked.connect(self.add_files_dialog)
        b_addfile.clicked.connect(self.add_folder_dialog)
        b_del.clicked.connect(self.remove_selected)
        b_clr.clicked.connect(self.clear_files)
        brow.addWidget(b_add)
        brow.addWidget(b_addfile)
        brow.addWidget(b_del)
        brow.addWidget(b_clr)
        ll.addLayout(brow)

        # ---------------- 中间：画布
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(4, 8, 4, 8)

        self.canvas = ImageCanvas()
        self.canvas.pixelHovered.connect(self.on_pixel_hovered)
        self.canvas.colorPicked.connect(self.on_color_picked)
        self.canvas.toolApplied.connect(lambda s: self.statusBar().showMessage(s, 4000))
        self.canvas.modifiedChanged.connect(self.on_modified_changed)
        ml.addWidget(self.canvas, 1)

        nav = QHBoxLayout()
        self.btn_prev = QPushButton("← 上一张")
        self.btn_next = QPushButton("下一张 →")
        self.btn_prev.clicked.connect(lambda: self.step(-1))
        self.btn_next.clicked.connect(lambda: self.step(1))
        self.lbl_nav = QLabel("— / —")
        self.lbl_nav.setAlignment(Qt.AlignCenter)
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.lbl_nav, 1)
        nav.addWidget(self.btn_next)
        ml.addLayout(nav)

        # ---------------- 右侧：参数面板
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setFrameShape(QFrame.NoFrame)
        right.setFixedWidth(310)
        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(8, 8, 8, 8)
        pl.setSpacing(10)

        # 工具
        gb_tool = QGroupBox("工具")
        tl = QVBoxLayout(gb_tool)
        self.tool_buttons: dict[str, QToolButton] = {}
        tools = [
            (ImageCanvas.MODE_MAGIC, "① 色块点击", "点击色块 → 相连区域变透明  (快捷键 1)"),
            (ImageCanvas.MODE_PICKER, "② 吸管取色", "取色并记录采样点  (快捷键 2)"),
            (ImageCanvas.MODE_ERASE, "③ 橡皮擦", "左键擦除，右键还原  (快捷键 3)"),
            (ImageCanvas.MODE_RESTORE, "④ 还原笔刷", "把擦除过的区域刷回原样  (快捷键 4)"),
        ]
        for mode, label, tip in tools:
            b = QToolButton()
            b.setText("  " + label)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setMinimumHeight(34)
            b.clicked.connect(lambda _, m=mode: self.set_mode(m))
            self.tool_buttons[mode] = b
            tl.addWidget(b)
        pl.addWidget(gb_tool)

        # 色块参数
        gb_magic = QGroupBox("色块透明化参数")
        form = QFormLayout(gb_magic)

        self.sp_tol = QSpinBox()
        self.sp_tol.setRange(0, 255)
        self.sp_tol.setValue(32)
        self.sp_tol.setToolTip("颜色容差：0 = 只匹配完全相同的颜色；越大匹配范围越宽")
        self.sp_tol.valueChanged.connect(self.on_tol_changed)
        self.sl_tol = QSlider(Qt.Horizontal)
        self.sl_tol.setRange(0, 255)
        self.sl_tol.setValue(32)
        self.sl_tol.valueChanged.connect(self.sp_tol.setValue)
        self.sp_tol.valueChanged.connect(self.sl_tol.setValue)
        tolrow = QHBoxLayout()
        tolrow.addWidget(self.sp_tol)
        tolrow.addWidget(self.sl_tol, 1)
        tolw = QWidget()
        tolw.setLayout(tolrow)
        form.addRow("容差", tolw)

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["相连区域（推荐）", "全局同色像素"])
        self.cmb_mode.currentIndexChanged.connect(self.on_contig_changed)
        form.addRow("匹配范围", self.cmb_mode)

        self.sp_brush = QSpinBox()
        self.sp_brush.setRange(1, 500)
        self.sp_brush.setValue(20)
        self.sp_brush.setSuffix(" px")
        self.sp_brush.valueChanged.connect(self.on_brush_changed)
        form.addRow("笔刷半径", self.sp_brush)

        self.sp_feather = QSpinBox()
        self.sp_feather.setRange(0, 100)
        self.sp_feather.setValue(0)
        self.sp_feather.setSuffix(" px")
        self.sp_feather.setToolTip("笔刷边缘羽化，改为 1~3 可让边缘更柔和")
        self.sp_feather.valueChanged.connect(self.on_feather_changed)
        form.addRow("笔刷羽化", self.sp_feather)

        pl.addWidget(gb_magic)

        # 采样点
        gb_pts = QGroupBox("采样点（用于批量套用）")
        gpl = QVBoxLayout(gb_pts)
        self.list_pts = QListWidget()
        self.list_pts.setMaximumHeight(150)
        self.list_pts.setToolTip("双击可删除该采样点")
        self.list_pts.itemDoubleClicked.connect(self.remove_sample_item)
        gpl.addWidget(self.list_pts)
        prow = QHBoxLayout()
        b_pt_from_canvas = QPushButton("从画布中心添加")
        b_pt_clear = QPushButton("清空")
        b_pt_from_canvas.clicked.connect(self.add_center_sample)
        b_pt_clear.clicked.connect(self.clear_samples)
        prow.addWidget(b_pt_from_canvas)
        prow.addWidget(b_pt_clear)
        gpl.addLayout(prow)
        pl.addWidget(gb_pts)

        # 操作
        gb_act = QGroupBox("操作")
        al = QVBoxLayout(gb_act)
        self.btn_undo = QPushButton("撤销  (Ctrl+Z)")
        self.btn_redo = QPushButton("重做  (Ctrl+Y)")
        self.btn_reset = QPushButton("还原原图  (Ctrl+R)")
        self.btn_undo.clicked.connect(self.canvas.undo)
        self.btn_redo.clicked.connect(self.canvas.redo)
        self.btn_reset.clicked.connect(self.on_reset)
        al.addWidget(self.btn_undo)
        al.addWidget(self.btn_redo)
        al.addWidget(self.btn_reset)
        pl.addWidget(gb_act)

        # 保存
        gb_save = QGroupBox("保存 / 批量")
        sl = QVBoxLayout(gb_save)
        self.btn_save = QPushButton("保存当前图片  (Ctrl+S)")
        self.btn_save_as = QPushButton("另存为…")
        self.btn_batch = QPushButton("批量套用到所有图片…")
        self.btn_batch.setStyleSheet("font-weight:bold; padding:8px;")
        self.btn_save.clicked.connect(lambda: self.save_current(False))
        self.btn_save_as.clicked.connect(lambda: self.save_current(True))
        self.btn_batch.clicked.connect(self.open_batch)
        sl.addWidget(self.btn_save)
        sl.addWidget(self.btn_save_as)
        sl.addWidget(self.btn_batch)
        pl.addWidget(gb_save)

        pl.addStretch(1)
        right.setWidget(panel)

        splitter.addWidget(left)
        splitter.addWidget(mid)
        splitter.addWidget(right)
        splitter.setSizes([260, 780, 310])
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        # 状态栏
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.lbl_pos = QLabel("—")
        self.lbl_color = QLabel("—")
        self.lbl_swatch = QLabel()
        self.lbl_swatch.setFixedSize(16, 16)
        self.lbl_swatch.setStyleSheet("background:#333;border:1px solid #666;")
        sb.addPermanentWidget(self.lbl_pos)
        sb.addPermanentWidget(self.lbl_swatch)
        sb.addPermanentWidget(self.lbl_color)
        sb.showMessage("就绪 —— 拖拽图片到窗口即可导入", 6000)

        self.set_mode(ImageCanvas.MODE_MAGIC)
        self.update_nav()

    def _build_toolbar(self):
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        self.addToolBar(tb)

        def act(text, slot, shortcut=None, tip=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if tip:
                a.setToolTip(tip)
            tb.addAction(a)
            return a

        act("添加图片", self.add_files_dialog, "Ctrl+O")
        act("添加文件夹", self.add_folder_dialog)
        tb.addSeparator()
        act("适应窗口", self.canvas.fit_to_window, "Ctrl+0")
        act("100%", self.canvas.zoom_100, "Ctrl+1")
        act("放大", self.canvas.zoom_in, "Ctrl+=")
        act("缩小", self.canvas.zoom_out, "Ctrl+-")
        tb.addSeparator()
        act("撤销", self.canvas.undo, "Ctrl+Z")
        act("重做", self.canvas.redo, "Ctrl+Y")
        tb.addSeparator()
        act("保存", lambda: self.save_current(False), "Ctrl+S")
        act("另存为", lambda: self.save_current(True), "Ctrl+Shift+S")
        tb.addSeparator()
        act("批量套用", self.open_batch, "Ctrl+B")

    # ============================================================ 文件管理
    def add_files_dialog(self):
        filters = "图片文件 (*{});;RAW 文件 (*{});;所有文件 (*.*)".format(
            " *".join(IMG_EXTS), " *".join(RAW_EXTS)
        )
        files, _ = QFileDialog.getOpenFileNames(self, "选择图片", "", filters)
        if files:
            self.add_files(files)

    def add_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not d:
            return
        found = []
        for root, _dirs, names in os.walk(d):
            for n in sorted(names):
                if os.path.splitext(n)[1].lower() in ALL_EXTS:
                    found.append(os.path.join(root, n))
        if found:
            self.add_files(found)
        else:
            QMessageBox.information(self, "提示", "该文件夹下没有找到支持的图片。")

    def add_files(self, paths: list[str]):
        added = 0
        for p in paths:
            p = os.path.abspath(p)
            if p in self.files:
                continue
            self.files.append(p)
            item = QListWidgetItem(os.path.basename(p))
            item.setToolTip(p)
            item.setData(Qt.UserRole, p)
            self.list.addItem(item)
            added += 1
        self.lbl_count.setText(f"{len(self.files)} 张")
        if added and self.current_index < 0:
            self.list.setCurrentRow(0)
        self.statusBar().showMessage(f"已导入 {added} 张图片（共 {len(self.files)} 张）", 4000)

    def remove_selected(self):
        rows = sorted({i.row() for i in self.list.selectedIndexes()}, reverse=True)
        if not rows:
            return
        for r in rows:
            self.list.takeItem(r)
            self.files.pop(r)
        self.lbl_count.setText(f"{len(self.files)} 张")
        if self.files:
            self.list.setCurrentRow(min(rows[-1], len(self.files) - 1))
        else:
            self.current_index = -1
            self.canvas.set_image(None)
            self.update_nav()

    def clear_files(self):
        if self.files and self.canvas.is_dirty():
            r = QMessageBox.question(
                self, "确认", "当前图片有未保存的修改，确定清空列表吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                return
        self.files.clear()
        self.list.clear()
        self.current_index = -1
        self.canvas.set_image(None)
        self.lbl_count.setText("0 张")
        self.update_nav()

    def on_select(self, row: int):
        if row < 0 or row >= len(self.files):
            return
        if row == self.current_index:
            return
        if self.current_index >= 0 and self.canvas.is_dirty():
            r = QMessageBox.question(
                self, "未保存", "当前图片有未保存的修改，是否保存？",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if r == QMessageBox.Cancel:
                self.list.blockSignals(True)
                self.list.setCurrentRow(self.current_index)
                self.list.blockSignals(False)
                return
            if r == QMessageBox.Save:
                self.save_current(False)
        self.load_index(row)

    def load_index(self, row: int):
        path = self.files[row]
        try:
            arr = np.ascontiguousarray(load_image_array(path))
            # 注意：QImage 不持有 bytes 的所有权，必须先把 buffer 存为局部变量
            # 再 copy()，否则临时对象被回收会导致段错误。
            buf = arr.tobytes()
            qimg = QImage(
                buf, arr.shape[1], arr.shape[0], QImage.Format_RGBA8888
            ).copy()
        except Exception as e:
            QMessageBox.critical(self, "读取失败", f"无法读取：\n{path}\n\n{e}")
            return
        self.current_index = row
        self.canvas.set_image(qimg, reset_view=True)
        self.update_nav()
        self.statusBar().showMessage(
            f"{os.path.basename(path)}  ·  {qimg.width()}×{qimg.height()}", 4000
        )

    def step(self, delta: int):
        if not self.files:
            return
        nxt = self.current_index + delta
        if 0 <= nxt < len(self.files):
            self.list.setCurrentRow(nxt)

    def update_nav(self):
        n = len(self.files)
        self.lbl_nav.setText(f"{self.current_index + 1 if self.current_index >= 0 else 0} / {n}")
        self.btn_prev.setEnabled(self.current_index > 0)
        self.btn_next.setEnabled(0 <= self.current_index < n - 1)

    # ============================================================ 工具切换
    def set_mode(self, mode: str):
        self.canvas.mode = mode
        for m, b in self.tool_buttons.items():
            b.setChecked(m == mode)
        self.canvas.setCursor(Qt.CrossCursor)
        tips = {
            ImageCanvas.MODE_MAGIC: "色块点击：左键 = 透明化相连色块，右键 = 按色还原",
            ImageCanvas.MODE_PICKER: "吸管取色：点击像素记录采样点",
            ImageCanvas.MODE_ERASE: "橡皮擦：左键擦除，右键还原",
            ImageCanvas.MODE_RESTORE: "还原笔刷：把擦除区域刷回原图",
        }
        self.statusBar().showMessage(tips.get(mode, ""), 5000)

    # ============================================================ 参数联动
    def on_tol_changed(self, v):
        self.canvas.tolerance = v
        self.spec.tolerance = v

    def on_contig_changed(self, idx):
        contig = idx == 0
        self.canvas.contiguous = contig
        self.spec.contiguous = contig
        self.statusBar().showMessage(
            "匹配范围：相连区域" if contig else "匹配范围：全局同色像素", 3000
        )

    def on_brush_changed(self, v):
        self.canvas.brush_radius = v

    def on_feather_changed(self, v):
        self.canvas.feather = v

    # ============================================================ 采样点
    def add_sample(self, nx: float, ny: float, rgb=None):
        self.spec.samples.append((float(nx), float(ny)))
        label = f"({nx:.4f}, {ny:.4f})"
        if rgb:
            label += f"   RGB({rgb[0]},{rgb[1]},{rgb[2]})"
        item = QListWidgetItem(label)
        if rgb:
            item.setIcon(make_swatch_icon(rgb))
        item.setData(Qt.UserRole, (nx, ny))
        self.list_pts.addItem(item)
        self.statusBar().showMessage(f"已添加采样点 {label}（共 {len(self.spec.samples)} 个）", 4000)

    def remove_sample_item(self, item: QListWidgetItem):
        idx = self.list_pts.row(item)
        if 0 <= idx < len(self.spec.samples):
            self.spec.samples.pop(idx)
            self.list_pts.takeItem(idx)
            self.statusBar().showMessage(f"已删除采样点（剩 {len(self.spec.samples)} 个）", 3000)

    def clear_samples(self):
        self.spec.samples.clear()
        self.list_pts.clear()

    def add_center_sample(self):
        if not self.canvas.has_image():
            return
        nx, ny = 0.5, 0.5
        c = self.canvas.img.pixelColor(int(self.canvas.img.width() * nx),
                                       int(self.canvas.img.height() * ny))
        self.add_sample(nx, ny, (c.red(), c.green(), c.blue()))

    def on_color_picked(self, r, g, b):
        if not self.canvas.has_image():
            return
        iw, ih = self.canvas.img.width(), self.canvas.img.height()
        pos = self.canvas._cursor_img_pos
        nx = max(0.0, min(1.0, pos.x() / iw))
        ny = max(0.0, min(1.0, pos.y() / ih))
        self.add_sample(nx, ny, (r, g, b))

    # ============================================================ 状态栏
    def on_pixel_hovered(self, x, y, r, g, b):
        if x < 0:
            self.lbl_pos.setText("—")
            self.lbl_color.setText("—")
            return
        self.lbl_pos.setText(f"x={x}  y={y}")
        self.lbl_color.setText(f"RGB({r}, {g}, {b})")
        self.lbl_swatch.setStyleSheet(
            f"background:rgb({r},{g},{b});border:1px solid #666;"
        )

    def on_modified_changed(self, dirty: bool):
        self.setWindowTitle(
            ("● " if dirty else "") + "透明通道色块点击器  ·  Color Block Transparency Tool"
        )
        if self.current_index >= 0:
            item = self.list.item(self.current_index)
            if item:
                base = os.path.basename(self.files[self.current_index])
                item.setText(("● " if dirty else "") + base)

    # ============================================================ 保存
    def on_reset(self):
        self.canvas.reset_changes()
        self.on_modified_changed(False)

    def save_current(self, save_as: bool):
        if not self.canvas.has_image():
            return
        src = self.files[self.current_index]
        if save_as:
            stem = os.path.splitext(os.path.basename(src))[0]
            path, _ = QFileDialog.getSaveFileName(
                self, "另存为", stem + "_clear.png",
                "PNG (*.png);;WebP (*.webp);;JPEG (*.jpg)"
            )
            if not path:
                return
        else:
            path = src
        try:
            arr = qimage_to_array(self.canvas.img)
            save_array(arr, path)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return
        self.canvas._set_dirty(False)
        self.on_modified_changed(False)
        self.statusBar().showMessage(f"已保存：{path}", 5000)

    # ============================================================ 批量
    def open_batch(self):
        if not self.files:
            QMessageBox.information(self, "提示", "请先导入图片。")
            return
        if not self.spec.samples:
            r = QMessageBox.question(
                self, "未设置采样点",
                "还没有记录任何采样点。\n\n"
                "批量处理需要一个「色块基准」。是否把当前画布的中心点作为采样点？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if r != QMessageBox.Yes:
                return
            self.add_center_sample()
        dlg = BatchDialog(self.files, self.spec, self)
        dlg.exec_()

    # ============================================================ 拖拽
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if os.path.isdir(p):
                for root, _d, names in os.walk(p):
                    for n in sorted(names):
                        if os.path.splitext(n)[1].lower() in ALL_EXTS:
                            paths.append(os.path.join(root, n))
            elif os.path.splitext(p)[1].lower() in ALL_EXTS:
                paths.append(p)
        if paths:
            self.add_files(paths)
        event.acceptProposedAction()

    # ============================================================ 设置持久化
    def _settings_path(self):
        return os.path.join(os.path.expanduser("~"), ".colorblock_clicker.json")

    def _load_settings(self):
        import json
        p = self._settings_path()
        if not os.path.exists(p):
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.sp_tol.setValue(int(d.get("tolerance", 32)))
            # 索引 0 = 相连区域(contiguous)，1 = 全局同色
            self.cmb_mode.setCurrentIndex(0 if d.get("contiguous", True) else 1)
            self.sp_brush.setValue(int(d.get("brush", 20)))
            self.sp_feather.setValue(int(d.get("feather", 0)))
        except Exception:
            pass

    def closeEvent(self, event):
        import json
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                json.dump({
                    "tolerance": self.sp_tol.value(),
                    "contiguous": self.cmb_mode.currentIndex() == 0,
                    "brush": self.sp_brush.value(),
                    "feather": self.sp_feather.value(),
                }, f)
        except Exception:
            pass
        if self.canvas.is_dirty():
            r = QMessageBox.question(
                self, "未保存", "当前图片有未保存的修改，确定退出吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()

    # ============================================================ 快捷键
    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key_1:
            self.set_mode(ImageCanvas.MODE_MAGIC)
        elif k == Qt.Key_2:
            self.set_mode(ImageCanvas.MODE_PICKER)
        elif k == Qt.Key_3:
            self.set_mode(ImageCanvas.MODE_ERASE)
        elif k == Qt.Key_4:
            self.set_mode(ImageCanvas.MODE_RESTORE)
        elif k == Qt.Key_Left:
            self.step(-1)
        elif k == Qt.Key_Right:
            self.step(1)
        elif k == Qt.Key_BracketLeft:
            self.sp_brush.setValue(max(1, self.sp_brush.value() - 2))
        elif k == Qt.Key_BracketRight:
            self.sp_brush.setValue(self.sp_brush.value() + 2)
        else:
            super().keyPressEvent(event)


def main():
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("ColorBlockClicker")
    app.setApplicationVersion(APP_VERSION)
    icon_path = resource_path(os.path.join("assets", "icon.ico"))
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    app.setStyleSheet(APP_QSS)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


APP_QSS = """
QMainWindow, QWidget { background: #23262b; color: #e6e8ec;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; }
QGroupBox { border: 1px solid #3a3f47; border-radius: 6px; margin-top: 12px;
    padding-top: 10px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #8fb7ff; }
QPushButton, QToolButton { background: #2f343b; border: 1px solid #3f454e;
    border-radius: 5px; padding: 6px 10px; color: #e6e8ec; }
QPushButton:hover, QToolButton:hover { background: #3a4049; border-color: #5a636f; }
QPushButton:pressed, QToolButton:pressed { background: #2a2f36; }
QToolButton:checked { background: #2f6fbf; border-color: #4c8de0; color: #fff; }
QPushButton:disabled { color: #6b7280; background: #2a2e34; }
QLineEdit, QSpinBox, QComboBox, QListWidget { background: #1c1f24;
    border: 1px solid #3a3f47; border-radius: 5px; padding: 4px 6px; color: #e6e8ec; }
QComboBox::drop-down { border: none; width: 18px; }
QListWidget::item { padding: 4px; }
QSlider::groove:horizontal { height: 4px; background: #3a3f47; border-radius: 2px; }
QSlider::handle:horizontal { background: #5aa0ff; width: 12px; margin: -5px 0;
    border-radius: 6px; }
QProgressBar { border: 1px solid #3a3f47; border-radius: 5px; text-align: center;
    background: #1c1f24; height: 18px; }
QProgressBar::chunk { background: #2f6fbf; border-radius: 4px; }
QToolBar { background: #1e2126; border: none; spacing: 4px; padding: 4px; }
QToolBar QToolButton { padding: 5px 10px; }
QStatusBar { background: #1e2126; color: #9aa3ae; }
QHeaderView::section { background: #2a2e34; border: none; padding: 4px; color: #9aa3ae; }
QTableWidget { background: #1c1f24; gridline-color: #2f343b; border: 1px solid #3a3f47; }
QSplitter::handle { background: #2a2e34; width: 3px; }
QScrollBar:vertical { background: #23262b; width: 10px; }
QScrollBar::handle:vertical { background: #3f454e; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


if __name__ == "__main__":
    main()
