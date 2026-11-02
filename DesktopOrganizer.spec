# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：onedir + 无控制台窗口。

为什么 onedir 而不是 onefile：
onefile 每次启动都要把内容解压到 %TEMP%\\_MEIxxxx，冷启动反而更慢，
而本项目被吐槽的正是「2.42s 冷启动」。onedir 只做内存映射，首帧更快。
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(os.path.abspath(SPECPATH)).resolve()  # noqa: F821 - SPECPATH 由 PyInstaller 注入
WEB_DIR = ROOT / "src" / "desktop_organizer" / "web"
ICON = ROOT / "assets" / "icon.ico"

datas = [(str(WEB_DIR), "desktop_organizer/web")]
for extra in (ICON,):
    if extra.is_file():
        datas.append((str(extra), "assets"))

hiddenimports = ["webview", "webview.platforms.edgechromium", "clr_loader", "pythonnet"]
binaries = []
for pkg in ("webview", "clr_loader", "pythonnet"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:  # noqa: BLE001 - 某个包没装时不该阻塞打包
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(  # noqa: F821
    [str(ROOT / "scripts" / "app_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pytest", "pip", "setuptools"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DesktopOrganizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ICON) if ICON.is_file() else None,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DesktopOrganizer",
)
