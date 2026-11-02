"""测试夹具：临时目录一律落在项目 sandbox 内，绝不碰真实用户目录。

pytest 默认把 tmp_path 建在系统 %TEMP%，既不在 guard 的允许清单里
（写盘类测试会被拒绝），也和"只在沙箱实验"的铁律冲突。
用 pytest_configure 把 basetemp 钉到 sandbox/_pytest-<pid>。
"""

from __future__ import annotations

import os
import shutil

from desktop_organizer.constants import SANDBOX_DIR

_BASE = SANDBOX_DIR / f"_pytest-{os.getpid()}"
_OWNS_BASE = False


def pytest_configure(config):
    global _OWNS_BASE
    if config.option.basetemp is None:
        config.option.basetemp = str(_BASE)
        _OWNS_BASE = True


def pytest_unconfigure(config):
    if _OWNS_BASE:
        shutil.rmtree(_BASE, ignore_errors=True)
