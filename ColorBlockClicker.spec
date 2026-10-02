# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置
# 构建:  pyinstaller ColorBlockClicker.spec --noconfirm
# 产物:  dist/ColorBlockClicker.exe

import os

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        (os.path.join("assets", "icon.ico"), "assets"),
        (os.path.join("assets", "icon.png"), "assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除明显用不到的大模块，减小体积
        "tkinter",
        "matplotlib",
        "scipy",
        "torch",
        "rawpy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ColorBlockClicker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join("assets", "icon.ico"),
    version="version_info.txt",
)
