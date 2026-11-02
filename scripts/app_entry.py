"""PyInstaller 打包入口（无控制台窗口）。

与 scripts/launch_gui.pyw 的区别：打包后不需要往 sys.path 里塞 src，
所以这里只做「开窗」，其它交给 gui_web.run。
"""

import sys
import traceback
from pathlib import Path


def _crash(message: str) -> None:
    try:
        base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
        logs = base / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / "launcher-error.log").open("a", encoding="utf-8") as fh:
            fh.write(message + "\n\n")
    except Exception:  # noqa: BLE001 - 记录失败也不能挡住退出
        pass


try:
    from desktop_organizer.gui_web import run

    raise SystemExit(run())
except SystemExit:
    raise
except Exception:  # noqa: BLE001 - 打包后没有控制台，必须落盘
    _crash(traceback.format_exc())
    raise
