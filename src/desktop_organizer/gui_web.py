"""pywebview 桌面窗口：把 web/index.html 包进原生窗口，用 Bridge 做前后端通道。

为什么用 pywebview 而不是 Tk：
- Windows 10/11 自带 WebView2 运行时，无需额外分发浏览器内核；
- 窗口是原生窗口（非浏览器 tab），任务栏图标、缩放、多显示器都正常；
- HTML/CSS 可以做出 Tk 做不到的视觉质感。

纪律：本模块只负责「开窗 + 接线」，任何文件操作都必须经过 Bridge。
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

from . import constants
from .bridge import Bridge

WEB_DIR = Path(__file__).resolve().parent / "web"
INDEX_HTML = WEB_DIR / "index.html"

WINDOW_TITLE = f"{constants.APP_NAME}"
WINDOW_W = 1180
WINDOW_H = 780
MIN_W = 940
MIN_H = 640

# WebView2 的 profile 落到 data/webview：不持久化时每次都要重建运行时环境，
# 实测界面就绪从 835ms 退化到 1916ms（同一台机器、同一个 HTML）。
WEBVIEW_PROFILE = constants.DATA_DIR / "webview"

# WebView2 默认会拉起一整个浏览器进程族（GPU 进程、多个渲染进程、后台联网）。
# 我们只是一个本地静态页，这些能力全是纯开销：关掉它们能显著压低常驻内存。
# 注意不要用 --single-process：WebView2 在单进程模式下容易直接崩。
_CHROMIUM_ARGS = (
    "--disable-gpu",
    "--disable-gpu-compositing",
    "--renderer-process-limit=1",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-sync",
    "--disable-extensions",
    "--disable-features=Translate,BackForwardCache,OptimizationHints,MediaRouter",
    "--no-first-run",
    "--no-default-browser-check",
)

_ENV_BROWSER_ARGS = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"


def chromium_args() -> list[str]:
    """交给 WebView2 的附加命令行参数。每次返回新列表，免得调用方改坏常量。"""
    return list(_CHROMIUM_ARGS)


def apply_chromium_env() -> None:
    """把瘦身参数写进环境变量——WebView2 只认这一条通道。

    用户若已经自己设了这个变量，追加而不是覆盖，别把人家的排障参数弄丢。
    """
    ours = " ".join(chromium_args())
    existing = os.environ.get(_ENV_BROWSER_ARGS, "").strip()
    os.environ[_ENV_BROWSER_ARGS] = f"{existing} {ours}".strip() if existing else ours


def start_kwargs() -> dict:
    """``webview.start`` 的参数。抽成函数是为了能单测，不必真开窗。"""
    WEBVIEW_PROFILE.mkdir(parents=True, exist_ok=True)
    return {
        "gui": "edgechromium",  # 强制 WebView2，避免回落到老的 MSHTML
        "debug": bool(os.environ.get("DESKTOP_ORGANIZER_DEBUG")),
        "private_mode": False,
        "storage_path": str(WEBVIEW_PROFILE),
    }


def _log_file() -> Path:
    path = constants.PROJECT_ROOT / "logs" / "gui.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _record(message: str) -> None:
    """GUI 崩在 pythonw 里没有控制台，必须落盘才查得到。"""
    try:
        with _log_file().open("a", encoding="utf-8") as fh:
            fh.write(message.rstrip() + "\n")
    except OSError:
        pass


def run(root: str | None = None, depth: int = 1) -> int:
    try:
        import webview  # 延迟导入：没装 pywebview 时 CLI 其它命令仍可用
    except ImportError:
        _record("pywebview 未安装，无法启动 GUI")
        print("缺少 pywebview，请执行: python -m pip install pywebview", file=sys.stderr)
        return 2

    if not INDEX_HTML.is_file():
        _record(f"界面文件缺失: {INDEX_HTML}")
        print(f"界面文件缺失: {INDEX_HTML}", file=sys.stderr)
        return 3

    bridge = Bridge(root=root, depth=depth)
    _record(f"启动 GUI root={bridge.root}")
    apply_chromium_env()

    window = webview.create_window(
        WINDOW_TITLE,
        url=str(INDEX_HTML),
        js_api=bridge,
        width=WINDOW_W,
        height=WINDOW_H,
        min_size=(MIN_W, MIN_H),
        background_color="#080a16",
        text_select=False,
        confirm_close=False,
        easy_drag=False,
    )
    if window is None:  # pragma: no cover - 只在不支持的平台发生
        return 4

    # 把窗口交给 bridge：后台任务（扫描/执行/回滚）靠它把进度推回前端。
    try:
        bridge.set_window(window)
    except Exception:  # noqa: BLE001 - 进度条坏了不能连窗口一起崩
        _record(traceback.format_exc())

    try:
        # gui='edgechromium'：强制用 WebView2；profile 持久化见 start_kwargs
        webview.start(**start_kwargs())
    except Exception:  # noqa: BLE001 - 把崩溃原因留档而不是无声退出
        _record(traceback.format_exc())
        return 1
    finally:
        _record("GUI 已退出")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="desktop-organizer-gui", add_help=True)
    parser.add_argument("--root", default=None, help="要整理的目录，默认桌面")
    parser.add_argument("--depth", type=int, default=1, help="扫描层数，默认 1")
    args = parser.parse_args(argv)
    return run(root=args.root, depth=args.depth)


if __name__ == "__main__":
    raise SystemExit(main())
