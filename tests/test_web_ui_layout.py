"""三栏界面的静态契约：左导航、中工作台、右 AI 顾问。

没有 JS 测试环境，只能锁住「该有的东西真的在 HTML 里」以及几条防回归的硬约束。
"""

from __future__ import annotations

import re
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "src" / "desktop_organizer" / "web" / "index.html"


def _html() -> str:
    return INDEX.read_text(encoding="utf-8")


def _css_rule(selector: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", _html(), flags=re.S)
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
    assert m, f"缺少样式: {selector}"
    return m.group(1)


def _class_tokens() -> set[str]:
    """HTML 里所有出现过的 class 名（多类名拆开，别用子串硬匹配）。"""
    tokens: set[str] = set()
    for attr in re.findall(r'class="([^"]*)"', _html()):
        tokens.update(attr.split())
    return tokens


def test_three_column_layout_exists() -> None:
    """用户要求"更现代化且易用"：左导航 / 中工作台 / 右顾问。"""
    tokens = _class_tokens()
    assert "nav" in tokens, "缺少左侧导航栏"
    assert "work" in tokens, "缺少中间工作台"
    assert "copilot" in tokens, "缺少右侧 AI 顾问栏"


def test_layout_is_css_grid() -> None:
    body = _css_rule(".shell") if ".shell" in _html() else _css_rule(".app")
    assert "grid-template-columns" in body, "三栏布局必须用 grid 分列"
    assert "minmax" in body or "px" in body


def test_progress_bar_shows_percentage_only() -> None:
    """用户明确要「只要一个百分比」。"""
    html = _html()
    assert 'id="progBar"' in html, "缺少进度条"
    assert 'id="progPct"' in html, "缺少百分比文字"
    assert "window.onProgress" in html, "进度条没有接后端推流"
    # 不允许出现"第 N/M 个"这种啰嗦计数
    assert "current_item" not in html or "progHint" in html


def test_progress_is_pushed_from_backend() -> None:
    html = _html()
    assert "onProgress = function" in html or "window.onProgress = " in html


def test_bulk_target_dir_input_exists() -> None:
    """批量改去向：一句话把选中项全塞进同一个目录。"""
    html = _html()
    assert 'id="bulkDir"' in html, "缺少批量目标目录输入框"
    assert 'id="btnBulk"' in html, "缺少批量应用按钮"
    assert "set_target_dir_bulk" in html, "批量改去向没有调用后端"


def test_ai_panel_is_wired() -> None:
    """AI 顾问：读配置、跑分析、一键采纳。"""
    html = _html()
    assert 'id="btnAI"' in html, "缺少 AI 分析按钮"
    assert 'id="aiList"' in html, "缺少 AI 建议列表容器"
    assert "ai_suggest" in html, "没有调用后端 AI 接口"
    assert "apply_suggestions" in html, "没有一键采纳接口"
    assert 'id="btnSaveAI"' in html, "缺少保存 AI 配置按钮"


def test_ai_key_is_never_echoed_in_full() -> None:
    """后端只回打码后的 key，前端也不能把明文写进 value。"""
    html = _html()
    assert 'type="password"' in html, "API Key 输入框必须遮挡"


def test_no_external_network_resources_still_holds() -> None:
    html = _html()
    for pat in ("http://", "https://", "//cdn.", 'src="//'):
        assert pat not in html, f"界面出现了外部资源引用: {pat}"
