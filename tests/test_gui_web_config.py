"""GUI 启动参数（不真正开窗，只校验配置）。

为什么要持久化 WebView2 profile：
实测冷启动 1916ms 里有 1660ms 花在 WebView2/.NET 初始化；把 profile 落到磁盘
（``private_mode=False``）后同一台机器降到 835ms，这才是「冷启动 < 2s」的来源。
"""

from __future__ import annotations

from pathlib import Path

from desktop_organizer import constants, gui_web


def test_start_kwargs_persists_the_webview_profile():
    kwargs = gui_web.start_kwargs()
    assert kwargs["private_mode"] is False
    assert Path(kwargs["storage_path"]).is_absolute()


def test_webview_profile_lives_under_project_root():
    """profile 目录必须在可写白名单内，否则 guard 之外的路径会脏。"""
    profile = Path(gui_web.start_kwargs()["storage_path"])
    assert profile.parent.parent == constants.PROJECT_ROOT


def test_start_kwargs_forces_edgechromium_and_respects_debug_flag(monkeypatch):
    monkeypatch.delenv("DESKTOP_ORGANIZER_DEBUG", raising=False)
    assert gui_web.start_kwargs()["gui"] == "edgechromium"
    assert gui_web.start_kwargs()["debug"] is False

    monkeypatch.setenv("DESKTOP_ORGANIZER_DEBUG", "1")
    assert gui_web.start_kwargs()["debug"] is True


def test_webview_profile_is_gitignored():
    """profile 里有浏览器缓存，绝不能进仓库。"""
    ignore = (constants.PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/" in ignore
