# -*- coding: utf-8 -*-
"""processor.py 算法层单元测试（不依赖 GUI）。"""
from __future__ import annotations

import os

import numpy as np
import pytest
from PIL import Image

from processor import (
    MagicSpec,
    _flood_fill,
    erase_color_blocks,
    load_image_array,
    pick_colors,
    pil_to_qimage,
    qimage_to_array,
    qimage_to_pil,
    save_array,
)


def two_block_image() -> np.ndarray:
    """10x20：左半红块、右半蓝块，alpha 全 255。"""
    arr = np.full((10, 20, 4), 255, dtype=np.uint8)
    arr[:, :10, :3] = [255, 0, 0]
    arr[:, 10:, :3] = [0, 0, 255]
    return arr


class TestFloodFill:
    def test_fills_whole_connected_run(self):
        mask = np.zeros((10, 20), dtype=bool)
        mask[:, :10] = True
        vis = _flood_fill(mask, 0, 0)
        assert vis[:, :10].all()
        assert not vis[:, 10:].any()

    def test_does_not_cross_color_barrier(self):
        mask = np.zeros((6, 6), dtype=bool)
        mask[0:2, 0:2] = True   # 连通块 A
        mask[5, 5] = True       # 孤立点 B
        vis = _flood_fill(mask, 0, 0)
        assert vis[0:2, 0:2].all()
        assert not vis[5, 5]

    def test_seed_outside_mask_returns_empty(self):
        mask = np.zeros((4, 4), dtype=bool)
        assert not _flood_fill(mask, 0, 0).any()

    def test_diagonal_is_not_connected(self):
        # 对角相邻在 4 连通下不算相连
        mask = np.zeros((3, 3), dtype=bool)
        mask[0, 0] = True
        mask[2, 2] = True
        vis = _flood_fill(mask, 0, 0)
        assert vis[0, 0]
        assert not vis[2, 2]


class TestEraseColorBlocks:
    def test_contiguous_only_erases_connected_block(self):
        arr = two_block_image()
        n = erase_color_blocks(arr, [(0, 0)], tolerance=0, contiguous=True)
        assert n == 10 * 10          # 只清掉左边红块
        assert (arr[:, :10, 3] == 0).all()
        assert (arr[:, 10:, 3] == 255).all()   # 蓝块不受影响

    def test_global_mode_erases_everywhere_same_color(self):
        arr = np.full((10, 30, 4), 255, dtype=np.uint8)
        arr[:, :5, :3] = [255, 0, 0]
        arr[:, 20:, :3] = [255, 0, 0]   # 两处不相连的红
        n = erase_color_blocks(arr, [(0, 0)], tolerance=0, contiguous=False)
        assert n == 10 * 5 + 10 * 10

    def test_tolerance_zero_requires_exact_color(self):
        arr = np.full((4, 4, 4), 255, dtype=np.uint8)
        arr[:, :, :3] = [10, 10, 10]
        n = erase_color_blocks(arr, [(0, 0)], tolerance=0, contiguous=True)
        assert n == 16  # 整图同色

    def test_tolerance_spreads_nearby_colors(self):
        # 3 像素纵向排列：颜色差 0 / 3 / 100
        arr = np.zeros((3, 1, 4), dtype=np.uint8)
        arr[0, 0, :3] = [0, 0, 0]
        arr[1, 0, :3] = [3, 0, 0]
        arr[2, 0, :3] = [100, 0, 0]
        arr[:, :, 3] = 255
        n0 = erase_color_blocks(arr.copy(), [(0, 0)], tolerance=0, contiguous=True)
        assert n0 == 1              # tol=0 只命中精确匹配
        n3 = erase_color_blocks(arr.copy(), [(0, 0)], tolerance=3, contiguous=True)
        assert n3 == 2              # 差 3 的相邻像素也被纳入

    def test_out_of_range_samples_are_clipped_not_crashing(self):
        arr = two_block_image()
        n = erase_color_blocks(arr, [(-999, 99999)], tolerance=0, contiguous=True)
        assert n > 0  # 被裁到右下角蓝块

    def test_multiple_samples_each_erased(self):
        arr = two_block_image()
        n = erase_color_blocks(arr, [(0, 0), (19, 0)], tolerance=0, contiguous=True)
        assert n == 10 * 20  # 左右两块都清掉

    def test_empty_samples_noop(self):
        arr = two_block_image()
        before = arr.copy()
        assert erase_color_blocks(arr, [], tolerance=0) == 0
        assert np.array_equal(arr, before)


class TestPickColors:
    def test_returns_rgb(self):
        arr = two_block_image()
        assert pick_colors(arr, [(0, 0)]) == [(255, 0, 0)]

    def test_clips_out_of_range(self):
        arr = two_block_image()
        assert pick_colors(arr, [(999, -99)]) == [(0, 0, 255)]


class TestMagicSpec:
    def test_sample_pixels_maps_normalised_coords(self):
        spec = MagicSpec(samples=[(0.0, 0.0), (1.0, 1.0)], tolerance=10)
        assert spec.sample_pixels(201, 11) == [(0, 0), (200, 10)]

    def test_tiny_image_maps_to_zero(self):
        spec = MagicSpec(samples=[(0.5, 0.5)], tolerance=1)
        assert spec.sample_pixels(1, 1) == [(0, 0)]


class TestIO:
    def test_png_roundtrip(self, tmp_path):
        arr = two_block_image()
        p = tmp_path / "round.png"
        save_array(arr, str(p))
        back = load_image_array(str(p))
        assert back.shape == arr.shape
        assert np.array_equal(back, arr)

    def test_jpg_composites_white_background(self, tmp_path):
        # 带透明区域的图存成 jpg：透明像素应被合成到白底上
        arr = np.zeros((4, 4, 4), dtype=np.uint8)
        arr[0, 0, :3] = [0, 0, 0]
        arr[0, 0, 3] = 0          # 全透明黑
        arr[1, :, :3] = [255, 0, 0]
        arr[1, :, 3] = 255
        p = tmp_path / "x.jpg"
        save_array(arr, str(p))
        back = load_image_array(str(p))
        # JPEG 有损，允许少量误差
        assert back[0, 0, 3] == 255
        assert back[0, 0, :3].mean() > 200   # 接近白色

    def test_unknown_extension_rejected_by_pillow(self, tmp_path):
        # 无扩展名时 Pillow 无法推断格式，save_array 会向上抛 ValueError
        # （GUI 里输出格式始终来自下拉框，不会出现这种路径）
        arr = two_block_image()
        p = tmp_path / "noext"
        with pytest.raises(ValueError):
            save_array(arr, str(p))

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(Exception):
            load_image_array(str(tmp_path / "nope.png"))


class TestQImageConversion:
    def test_pil_qimage_array_roundtrip(self, qapp):
        arr = two_block_image()
        im = Image.fromarray(arr, "RGBA")
        qimg = pil_to_qimage(im)
        back = qimage_to_array(qimg)
        assert back.shape == arr.shape
        assert np.array_equal(back, arr)

    def test_qimage_to_pil_roundtrip(self, qapp):
        arr = two_block_image()
        im = Image.fromarray(arr, "RGBA")
        out = qimage_to_pil(pil_to_qimage(im))
        assert out.size == (20, 10)
