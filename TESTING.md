# whitelib 测试说明
- 测试完成：是（2026-10-04）
- 测试日期：2026-10-04
- 测试内容：单元测试覆盖算法层（行游程洪泛填充连通性、erase_color_blocks 容差与越界裁剪、pick_colors、MagicSpec 归一化、PNG/JPG/QImage 往返、无扩展名拒绝）；集成测试覆盖 BatchWorker 后台线程批量处理全链路与失败隔离；注入测试验证输入路径含 `../` 时输出按 basename 落在 out_dir 内不外逃；钩子测试验证 ImageCanvas 的 toolApplied/modifiedChanged/colorPicked 信号按序触发、坏文件不影响整批。涉及模块：processor/算法层、BatchWorker、ImageCanvas。
- 运行命令：python -m pytest tests/ -v（QT_QPA_PLATFORM=offscreen）
- 测试框架：pytest（PyQt5 offscreen）
- 模型：豆包（Doubao）生成

## 运行方式

```powershell
pip install numpy Pillow PyQt5
$env:QT_QPA_PLATFORM = "offscreen"   # 无显示器环境
python -m pytest tests/ -v
```

- 预期：**34 passed**（Python 3.14 / Windows）。
- 另保留原有无头脚本 `python selftest.py`（全链路 GUI 自检，非 pytest）。

## 目录与覆盖

| 文件 | 覆盖点 |
| --- | --- |
| `tests/test_processor.py` | 算法层：行游程洪泛填充（连通/隔离/对角不连通）、`erase_color_blocks`（相连 vs 全局、容差 0 精确匹配、容差扩散、越界采样裁剪、多样本、空采样）、`pick_colors`、`MagicSpec.sample_pixels` 归一化坐标、PNG 往返、JPG 合成白底、无扩展名拒绝、QImage/PIL 互转 |
| `tests/test_batch_worker.py` | `BatchWorker` 后台线程：全部成功、**坏文件失败隔离**（一张损坏图不影响其它图）、**路径注入**（输入路径串含 `../` 时输出仍按 basename 落在 out_dir 内、不外逃）、重名自动加 `_1` 后缀 |
| `tests/test_canvas.py` | `ImageCanvas` 撤销/redo、撤销栈 40 步上限、新操作清 redo、信号钩子（`toolApplied`/`modifiedChanged`/`colorPicked`）、`apply_magic_to_image`、棋盘格缓存 |

## 注入与钩子测试说明

- **路径注入**：批量处理的输入来自用户拖入的文件/文件夹。`BatchWorker` 用
  `os.path.basename(path)` 推导输出名，测试构造含 `../` 的路径串，断言产物
  只按 basename 落到 out_dir 内、不产生任何 out_dir 之外的文件。
- **失败隔离（钩子）**：`BatchWorker` 的 `itemDone` 信号相当于每个文件完成后的
  回调；测试中故意放一张损坏图片，断言该条记为 `fail`、其余仍 `ok`，
  且最终 `finishedAll(ok, fail)` 计数正确——一个坏输入不会拖垮整批任务。
- **信号事件**：`ImageCanvas` 的 `toolApplied`/`modifiedChanged`/`colorPicked`
  是画布事件钩子，测试断言它们在 undo/redo、擦除、取色时按预期触发。
- 本仓库无 subprocess/shell/SQL/模板拼接，无命令注入面；文件读写为本地操作。
