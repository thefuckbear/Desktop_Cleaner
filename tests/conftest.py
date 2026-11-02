"""测试夹具：临时目录一律落在项目 sandbox 内，绝不碰真实用户目录。

pytest 默认把 tmp_path 建在系统 %TEMP%，既不在 guard 的允许清单里
（写盘类测试会被拒绝），也和"只在沙箱实验"的铁律冲突。
用 pytest_configure 把 basetemp 钉到 sandbox/_pytest-<pid>。
"""

from __future__ import annotations

import os
import shutil

import pytest

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


@pytest.fixture
def fake_desktop(tmp_path, monkeypatch):
    """把 tmp_path 伪装成"用户桌面"，以便在不碰真实桌面的前提下测写盘许可。

    为什么必须伪装：pytest 的 tmp_path 落在 ``PROJECT_ROOT\\sandbox`` 下，
    会先命中 guard 的允许清单（tier=allowlist）被直接放行，永远走不到
    userdir 分支；而真实桌面绝对不可以作为测试样本。

    做法：允许清单只留日志目录（journal 写入必须能过），用户数据目录指向
    tmp_path。于是 tmp_path 内的路径 = userdir 分支，日志目录 = allowlist。
    """
    from desktop_organizer import guard

    journal_dir = tmp_path / "journal-logs"
    monkeypatch.setattr(guard, "_allowlist", lambda: [guard._norm(journal_dir)])
    monkeypatch.setattr(guard, "_user_data_dirs", lambda: [guard._norm(tmp_path)])
    return tmp_path
