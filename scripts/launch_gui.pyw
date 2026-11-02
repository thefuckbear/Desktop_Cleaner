"""无控制台启动器：桌面快捷方式指向此文件（用 pythonw.exe 运行）。

只做三件事：把 src 加进 sys.path -> 载入 GUI -> 崩了写日志。
"""

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _crash(message):
    try:
        d = os.path.join(ROOT, "logs")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "launcher-error.log"), "a", encoding="utf-8") as fh:
            fh.write(message + "\n\n")
    except Exception:
        pass


try:
    from desktop_organizer.gui_web import run

    raise SystemExit(run())
except SystemExit:
    raise
except Exception:
    _crash(traceback.format_exc())
    raise
