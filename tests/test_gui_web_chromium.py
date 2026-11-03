"""GUI 启动参数瘦身：WebView2 默认会开一整个浏览器进程族，必须显式关掉。"""

from __future__ import annotations

import builtins

from desktop_organizer import gui_web


def test_chromium_args_disable_what_we_do_not_need() -> None:
    args = gui_web.chromium_args()
    joined = " ".join(args)
    # 本地静态页不需要 GPU 合成、不需要多渲染进程、不需要后台联网
    assert "--disable-gpu" in joined
    assert "--renderer-process-limit=1" in joined
    assert "--disable-background-networking" in joined
    assert "--disable-features=" in joined
    assert "--single-process" not in joined  # 单进程会让 WebView2 崩，别用


def test_chromium_args_is_stable_and_returns_fresh_list() -> None:
    first = gui_web.chromium_args()
    second = gui_web.chromium_args()
    assert first == second
    assert first is not second  # 调用方改了不应污染下一次


def test_apply_chromium_env_sets_browser_arguments(monkeypatch) -> None:
    monkeypatch.delenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", raising=False)
    gui_web.apply_chromium_env()
    value = __import__("os").environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"]
    assert "--disable-gpu" in value


def test_apply_chromium_env_keeps_user_arguments(monkeypatch) -> None:
    import os

    monkeypatch.setenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--user-flag")
    gui_web.apply_chromium_env()
    value = os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"]
    assert "--user-flag" in value
    assert "--disable-gpu" in value


def test_run_injects_window_into_bridge(monkeypatch) -> None:
    """窗口创建后必须把 window 交给 bridge，否则进度条永远收不到消息。"""
    seen: dict = {}

    class _FakeWindow:
        def evaluate_js(self, script):  # pragma: no cover - 这里不该被调用
            return None

    class _FakeWebview:
        def create_window(self, *a, **kw):
            return _FakeWindow()

        def start(self, **kw):
            seen["start_kwargs"] = kw

    fake = _FakeWebview()
    monkeypatch.setitem(__import__("sys").modules, "webview", fake)
    monkeypatch.setattr(gui_web, "apply_chromium_env", lambda: None)

    real_bridge = gui_web.Bridge

    class _SpyBridge(real_bridge):
        def set_window(self, window):
            seen["window"] = window
            super().set_window(window)

    monkeypatch.setattr(gui_web, "Bridge", _SpyBridge)

    code = gui_web.run()
    assert code == 0
    assert isinstance(seen.get("window"), _FakeWindow)
    assert seen["start_kwargs"].get("gui") == "edgechromium"
