# -*- coding: utf-8 -*-
"""
batch_dialog.py —— 批量处理对话框

把当前画布上选定的色块规则（采样点 / 容差 / 连续性）套用到一批图片上，
支持选择输出目录、输出格式、重名策略，并显示进度与结果。
"""
from __future__ import annotations

import os
import traceback

import numpy as np
from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from processor import (
    MagicSpec,
    erase_color_blocks,
    load_image_array,
    pick_colors,
    save_array,
)


class BatchWorker(QThread):
    """后台线程：逐张处理图片。"""

    progress = pyqtSignal(int, int, str)          # done, total, name
    itemDone = pyqtSignal(int, str, str, int)     # idx, out_path/err, status, n_pixels
    finishedAll = pyqtSignal(int, int)            # ok_count, fail_count

    def __init__(self, files, spec: MagicSpec, out_dir, fmt, overwrite, suffix="", parent=None):
        super().__init__(parent)
        self.files = files
        self.spec = spec
        self.out_dir = out_dir
        self.fmt = fmt
        self.overwrite = overwrite
        self.suffix = suffix
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        ok = fail = 0
        total = len(self.files)
        for i, path in enumerate(self.files):
            if self._abort:
                break
            name = os.path.basename(path)
            self.progress.emit(i, total, name)
            try:
                arr = load_image_array(path)
                h, w = arr.shape[0], arr.shape[1]
                samples = self.spec.sample_pixels(w, h)
                colors = pick_colors(arr, samples)
                n = erase_color_blocks(arr, samples, self.spec.tolerance, self.spec.contiguous)

                stem = os.path.splitext(name)[0] + self.suffix
                out_path = os.path.join(self.out_dir, stem + self.fmt)
                if os.path.exists(out_path) and not self.overwrite:
                    k = 1
                    while os.path.exists(os.path.join(self.out_dir, f"{stem}_{k}{self.fmt}")):
                        k += 1
                    out_path = os.path.join(self.out_dir, f"{stem}_{k}{self.fmt}")
                save_array(arr, out_path)
                ok += 1
                detail = f"{n:,}px  " + "  ".join(f"RGB{c}" for c in colors[:4])
                self.itemDone.emit(i, out_path, "ok", n)
                self.progress.emit(i + 1, total, f"{name}  →  {detail}")
            except Exception as e:
                fail += 1
                self.itemDone.emit(i, str(e), "fail", -1)
                self.progress.emit(i + 1, total, f"{name}  ×  {e}")
        self.finishedAll.emit(ok, fail)


class BatchDialog(QDialog):
    def __init__(self, files: list[str], spec: MagicSpec, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量处理")
        self.resize(880, 620)
        self.files = list(files)
        self.spec = spec
        self.worker: BatchWorker | None = None

        root = QVBoxLayout(self)

        # ---- 规则摘要
        box = QGroupBox("色块规则（来自当前画布）")
        bl = QVBoxLayout(box)
        self.lbl_rule = QLabel()
        self.lbl_rule.setWordWrap(True)
        bl.addWidget(self.lbl_rule)
        root.addWidget(box)

        # ---- 输出设置
        obox = QGroupBox("输出设置")
        ol = QVBoxLayout(obox)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("输出目录："))
        self.ed_out = QLineEdit()
        btn_out = QPushButton("浏览…")
        btn_out.clicked.connect(self.choose_out_dir)
        r1.addWidget(self.ed_out, 1)
        r1.addWidget(btn_out)
        ol.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("输出格式："))
        self.cmb_fmt = QComboBox()
        self.cmb_fmt.addItems([".png", ".webp", ".jpg"])
        r2.addWidget(self.cmb_fmt)
        r2.addSpacing(16)
        self.chk_overwrite = QCheckBox("覆盖同名文件")
        self.chk_overwrite.setChecked(False)
        r2.addWidget(self.chk_overwrite)
        r2.addStretch(1)
        r2.addWidget(QLabel("命名后缀："))
        self.ed_suffix = QLineEdit("_clear")
        self.ed_suffix.setFixedWidth(110)
        r2.addWidget(self.ed_suffix)
        ol.addLayout(r2)
        root.addWidget(obox)

        # ---- 文件表
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["文件", "状态", "透明像素", "输出/错误"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table, 1)

        # ---- 进度
        self.bar = QProgressBar()
        root.addWidget(self.bar)
        self.lbl_status = QLabel("就绪")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        # ---- 按钮
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_start = QPushButton("开始处理")
        self.btn_start.setDefault(True)
        self.btn_start.clicked.connect(self.start)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.close)
        bottom.addWidget(self.btn_start)
        bottom.addWidget(self.btn_close)
        root.addLayout(bottom)

        self.refresh_rule()
        self.reload_table()

    # ------------------------------------------------------------ 辅助
    def refresh_rule(self):
        s = self.spec
        pts = "，".join(f"({x:.3f},{y:.3f})" for x, y in s.samples) or "（无）"
        mode = "相连区域" if s.contiguous else "全局同色"
        self.lbl_rule.setText(
            f"容差 <b>{s.tolerance}</b>　模式 <b>{mode}</b>　采样点 <b>{len(s.samples)}</b> 个<br>"
            f"<span style='color:#9aa'>{pts}</span><br>"
            "<span style='color:#e08'>提示：采样点为归一化坐标，会按每张图片的实际尺寸换算。</span>"
        )

    def reload_table(self):
        self.table.setRowCount(len(self.files))
        for i, f in enumerate(self.files):
            it = QTableWidgetItem(os.path.basename(f))
            it.setToolTip(f)
            self.table.setItem(i, 0, it)
            self.table.setItem(i, 1, QTableWidgetItem("待处理"))
            self.table.setItem(i, 2, QTableWidgetItem("-"))
            self.table.setItem(i, 3, QTableWidgetItem(""))
        self.bar.setMaximum(max(1, len(self.files)))
        self.bar.setValue(0)

    def choose_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.ed_out.text() or "")
        if d:
            self.ed_out.setText(d)

    # ------------------------------------------------------------ 执行
    def start(self):
        if self.worker and self.worker.isRunning():
            return
        out_dir = self.ed_out.text().strip()
        if not out_dir:
            # 默认输出到「源目录/cleared」
            src_dir = os.path.dirname(self.files[0]) if self.files else os.getcwd()
            out_dir = os.path.join(src_dir, "cleared")
            self.ed_out.setText(out_dir)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法创建输出目录：{e}")
            return

        fmt = self.cmb_fmt.currentText()
        suffix = self.ed_suffix.text().strip()
        spec = MagicSpec(self.spec.samples, self.spec.tolerance, self.spec.contiguous)

        self.btn_start.setEnabled(False)
        self.btn_start.setText("处理中…")
        self.reload_table()

        self.worker = BatchWorker(
            self.files, spec, out_dir, fmt, self.chk_overwrite.isChecked(), suffix, self
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.itemDone.connect(self.on_item_done)
        self.worker.finishedAll.connect(self.on_finished)
        self._out_dir = out_dir
        self.worker.start()

    def on_progress(self, done, total, msg):
        self.bar.setValue(done)
        self.lbl_status.setText(msg)

    def on_item_done(self, idx, out_path, status, n):
        if status == "ok":
            self.table.item(idx, 1).setText("✓ 完成")
            self.table.item(idx, 2).setText(f"{n:,}")
            self.table.item(idx, 3).setText(out_path)
        else:
            self.table.item(idx, 1).setText("× 失败")
            self.table.item(idx, 2).setText("-")
            self.table.item(idx, 3).setText(out_path)

    def on_finished(self, ok, fail):
        self.btn_start.setEnabled(True)
        self.btn_start.setText("再次处理")
        self.lbl_status.setText(f"完成：成功 {ok} 张，失败 {fail} 张。输出目录：{self._out_dir}")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            r = QMessageBox.question(
                self, "确认", "任务正在运行，确定要中止并关闭吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.abort()
            self.worker.wait(3000)
        event.accept()
