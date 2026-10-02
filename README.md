# 透明通道色块点击器

一个基于 **PyQt5** 的图片抠图工具：点击画布上的色块，容差范围内**相连**的像素一键变透明，
并且可以把同一套规则**批量套用**到导入的所有图片上。

![screenshot](_screenshot.png)

## 下载 exe（免安装）

无需 Python 环境，直接到 [Releases](../../releases) 下载 `ColorBlockClicker.exe`
双击运行即可（Windows 10/11 64 位）。

> 首次启动会比常规程序慢几秒（单文件自解压），之后正常。

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

生成一张测试图验证效果：

```bash
python make_test_image.py
```

然后 `python main.py`，把 `test_image.png` 拖进窗口即可。

## 核心功能

| 功能 | 说明 |
| --- | --- |
| 批量导入 | 工具栏「添加图片 / 添加文件夹」，或直接把文件/文件夹**拖进窗口**（递归扫描） |
| 色块点击 | 工具①，左键点击色块 → 相连像素 alpha 置 0；**右键** = 按色还原 |
| 吸管取色 | 工具②，取色并记录**归一化采样点**，供批量套用 |
| 橡皮擦 | 工具③，左键擦除、右键还原，圆形笔刷 + 可调羽化 |
| 还原笔刷 | 工具④，把擦过的区域刷回原图 |
| 容差 | 0~255，切比雪夫颜色距离；0 = 仅完全相同的颜色 |
| 匹配范围 | 「相连区域」（洪水填充）/「全局同色像素」两种模式 |
| 撤销/重做 | 40 步 alpha 历史，`Ctrl+Z` / `Ctrl+Y` |
| 批量套用 | `Ctrl+B`，把当前规则应用到全部图片，输出到指定目录 |
| 视图 | 滚轮缩放、`Ctrl+滚轮` 调笔刷、Shift+左键/中键平移、棋盘格显示透明 |

## 快捷键

| 键 | 作用 |
| --- | --- |
| `1` `2` `3` `4` | 切换 色块点击 / 吸管 / 橡皮擦 / 还原笔刷 |
| `[` `]` | 减小 / 增大笔刷半径 |
| `←` `→` | 上一张 / 下一张 |
| `Ctrl+O` | 添加图片 |
| `Ctrl+0` / `Ctrl+1` | 适应窗口 / 100% |
| `Ctrl+=` / `Ctrl+-` | 放大 / 缩小 |
| `Ctrl+Z` / `Ctrl+Y` | 撤销 / 重做 |
| `Ctrl+R` | 还原为原图 |
| `Ctrl+S` / `Ctrl+Shift+S` | 保存 / 另存为 |
| `Ctrl+B` | 批量套用 |

## 批量处理原理

采样点保存为**归一化坐标 (0~1)**，批量处理时按每张图片的实际尺寸换算回像素坐标，
因此在尺寸不同的图片之间也能大致对位。容差与「相连/全局」模式会原样套用。

> 若各图色块位置差异较大，建议：在画布上多点几个采样点（不同色块各点一次），
> 每个采样点都会独立执行一次透明化。

## 输出格式

`png` / `webp` 保留透明通道；`jpg` / `bmp` 会自动合成白色背景（这两种格式本身不支持透明度）。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `main.py` | 主程序：主窗口、工具栏、参数面板、文件列表、拖拽、设置持久化 |
| `canvas.py` | 画布组件：显示、缩放平移、取色、笔刷、色块洪水填充、撤销栈 |
| `processor.py` | 算法层：`erase_color_blocks()`、`_flood_fill()`、读写转换（可脱离 GUI 使用） |
| `batch_dialog.py` | 批量处理对话框 + 后台线程 `BatchWorker` |
| `selftest.py` | 无头自检：窗口构建、抠图、撤销、批量导出等全链路验证 |
| `smoke_test_exe.py` | 打包后 exe 冒烟测试：启动、窗口标题、界面渲染截图 |
| `make_test_image.py` | 生成测试图 |
| `make_icon.py` | 生成应用图标 `assets/icon.ico` |
| `build_exe.bat` / `ColorBlockClicker.spec` | PyInstaller 打包配置与一键脚本 |
| `.github/workflows/build.yml` | CI：tag 推送时自动自检 + 构建 exe + 发布 Release |

## 单独调用算法

```python
import numpy as np
from processor import load_image_array, erase_color_blocks, save_array

arr = load_image_array("in.png")          # HxWx4 uint8
n = erase_color_blocks(arr, samples=[(100, 100)], tolerance=20, contiguous=True)
print("透明像素:", n)
save_array(arr, "out.png")
```

## 可选项：RAW 支持

```bash
pip install rawpy
```

安装后会自动识别 `.cr2 .nef .arw .dng` 等相机 RAW 文件；未安装时这类文件会被跳过。
