"""启动器选择：有打包版就用打包版，但过期的打包版必须让位给源码。

"过期"是真风险：改了 bug 但没重新打包，快捷方式还在跑旧 exe，
用户会以为「修了还是没修」。所以按源码最新修改时间做新鲜度校验。
"""

from __future__ import annotations

import os
import time

from desktop_organizer import launcher


def _make_fake_project(tmp_path, *, build_exe: bool, exe_newer: bool = True):
    root = tmp_path / "proj"
    src = root / "src" / "desktop_organizer"
    src.mkdir(parents=True)
    newest = src / "executor.py"
    newest.write_text("# code\n", encoding="utf-8")
    exe = root / launcher.FROZEN_EXE
    if build_exe:
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"MZ")
        now = time.time()
        os.utime(newest, (now - 100, now - 100))
        os.utime(exe, (now, now) if exe_newer else (now - 500, now - 500))
    return root, exe


def test_returns_exe_when_it_exists_and_is_fresh(tmp_path):
    root, exe = _make_fake_project(tmp_path, build_exe=True)
    picked = launcher.pick_entrypoint(root)
    assert picked is not None
    assert picked.resolve() == exe.resolve()


def test_returns_none_when_exe_is_missing(tmp_path):
    root, _ = _make_fake_project(tmp_path, build_exe=False)
    assert launcher.pick_entrypoint(root) is None


def test_returns_none_when_exe_is_older_than_sources(tmp_path):
    """改过源码但没重新打包时，绝不能继续跑旧 exe。"""
    root, _ = _make_fake_project(tmp_path, build_exe=True, exe_newer=False)
    assert launcher.pick_entrypoint(root) is None


def test_returns_none_when_only_html_changed(tmp_path):
    """改了界面但没重新打包，同样必须让位给源码模式。"""
    root, exe = _make_fake_project(tmp_path, build_exe=True, exe_newer=False)
    html = root / "src" / "desktop_organizer" / "web" / "index.html"
    html.parent.mkdir(parents=True)
    html.write_text("<html></html>", encoding="utf-8")
    now = time.time()
    os.utime(html, (now, now))
    os.utime(exe, (now - 100, now - 100))
    assert launcher.pick_entrypoint(root) is None

    root = tmp_path / "bare"
    root.mkdir()
    (root / launcher.FROZEN_EXE).parent.mkdir(parents=True)
    (root / launcher.FROZEN_EXE).write_bytes(b"MZ")
    assert launcher.pick_entrypoint(root) is None
