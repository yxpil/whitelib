# -*- coding: utf-8 -*-
"""BatchWorker（批量后台线程）测试：含信号回调与失败隔离、路径注入。"""
from __future__ import annotations

import os

import numpy as np
from PyQt5.QtCore import QEventLoop

from processor import MagicSpec, save_array


def _png(path, rgb=(255, 0, 0), size=8):
    arr = np.full((size, size, 4), 255, dtype=np.uint8)
    arr[:, :, :3] = rgb
    save_array(arr, str(path))
    return str(path)


def _run_worker(worker, qapp):
    """启动 BatchWorker 并用事件循环阻塞到 finishedAll 信号真正派发。"""
    loop = QEventLoop()
    items, summary = [], {}

    worker.itemDone.connect(lambda i, p, s, n: items.append((i, s, n)))
    worker.finishedAll.connect(lambda ok, f: (summary.update(ok=ok, fail=f), loop.quit()))
    worker.start()
    loop.exec_()
    worker.wait(2000)
    return items, summary


class TestBatchWorker:
    def test_processes_all_files_ok(self, tmp_path, qapp):
        from batch_dialog import BatchWorker

        src = tmp_path / "src"
        src.mkdir()
        a = _png(src / "a.png", (255, 0, 0))
        b = _png(src / "b.png", (0, 255, 0))
        out = tmp_path / "out"
        out.mkdir()

        spec = MagicSpec(samples=[(4, 4)], tolerance=0, contiguous=True)
        w = BatchWorker([a, b], spec, str(out), ".png", False)
        items, summary = _run_worker(w, qapp)

        assert summary == {"ok": 2, "fail": 0}
        assert sorted(s for _, s, _ in items) == ["ok", "ok"]
        assert (out / "a.png").exists() and (out / "b.png").exists()

    def test_one_bad_file_does_not_break_others(self, tmp_path, qapp):
        # 失败隔离：一个损坏文件失败计数，其余文件仍正常处理
        from batch_dialog import BatchWorker

        src = tmp_path / "src"
        src.mkdir()
        good = _png(src / "good.png")
        bad = src / "broken.png"
        bad.write_bytes(b"this is not a png")
        out = tmp_path / "out"
        out.mkdir()

        spec = MagicSpec(samples=[(4, 4)], tolerance=0, contiguous=True)
        w = BatchWorker([str(bad), good], spec, str(out), ".png", False)
        items, summary = _run_worker(w, qapp)

        assert summary == {"ok": 1, "fail": 1}
        assert sorted(s for _, s, _ in items) == ["fail", "ok"]
        assert (out / "good.png").exists()

    def test_output_path_never_escapes_out_dir(self, tmp_path, qapp):
        # 路径注入：即使输入路径串里含 ../ 段，输出仍按 basename 落在 out_dir 内
        from batch_dialog import BatchWorker

        src = tmp_path / "deep" / "sub"
        src.mkdir(parents=True)
        real = _png(src / "photo.png")
        out = tmp_path / "out"
        out.mkdir()

        tricky = os.path.normpath(os.path.join(str(src), "..", "sub", "photo.png"))
        spec = MagicSpec(samples=[(4, 4)], tolerance=0, contiguous=True)
        w = BatchWorker([tricky], spec, str(out), ".png", False)
        items, summary = _run_worker(w, qapp)

        assert summary == {"ok": 1, "fail": 0}
        produced = list(out.iterdir())
        assert len(produced) == 1
        assert produced[0].name == "photo.png"
        assert os.path.commonpath([str(out), str(produced[0])]) == str(out)

    def test_overwrite_false_adds_suffix_on_second_run(self, tmp_path, qapp):
        from batch_dialog import BatchWorker

        src = tmp_path / "src"
        src.mkdir()
        a = _png(src / "a.png")
        out = tmp_path / "out"
        out.mkdir()
        spec = MagicSpec(samples=[(4, 4)], tolerance=0, contiguous=True)

        for _ in range(2):
            w = BatchWorker([a], spec, str(out), ".png", False)
            _run_worker(w, qapp)
        names = sorted(p.name for p in out.iterdir())
        assert names == ["a.png", "a_1.png"]
