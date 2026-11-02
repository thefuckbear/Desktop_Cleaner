"""启动器选择（决定「用打包 exe 还是用源码」）。

背景：桌面快捷方式最初指向 ``pythonw scripts\\launch_gui.pyw``，而铁律禁止
改写桌面已有文件，所以不能把快捷方式改指 exe。让启动器自己发现 exe，
就能原地提速，用户无需重建快捷方式。

新鲜度校验：改了源码却没重新打包时，必须让位给源码模式 ——
否则用户会看到「修了还是没修」，这是最伤信任的一类 bug。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN_EXE = Path("dist") / "DesktopOrganizer" / "DesktopOrganizer.exe"
SRC_DIR = Path("src")


def _newest_source_mtime(project_root: Path) -> float:
    """src 下所有文件的最新修改时间。

    不能只看 *.py：界面都在 web/index.html 里，改样式后 exe 就成了旧包，
    用户会看到「改了没生效」。
    """
    src = project_root / SRC_DIR
    newest = 0.0
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


def pick_entrypoint(project_root: str | Path) -> Path | None:
    """返回可用的打包版 exe；缺失、过期或没有源码树时返回 None。"""
    root = Path(project_root)
    exe = root / FROZEN_EXE
    if not exe.is_file():
        return None
    newest_src = _newest_source_mtime(root)
    if newest_src <= 0.0:
        return None  # 没有源码树就无从判断新鲜度，宁可用源码模式
    try:
        if exe.stat().st_mtime < newest_src:
            return None  # 打包产物比源码旧，不能跑
    except OSError:
        return None
    return exe


def exec_frozen(exe: str | Path, argv: list[str] | None = None) -> None:
    """用打包版进程替换当前进程（保留无控制台特性）。"""
    os.execv(str(exe), [str(exe), *(argv or [])])
    raise SystemExit(0)  # pragma: no cover - execv 成功时不会返回
