"""前端单文件 HTML 的静态一致性检查。

没有 JS 测试环境，但"JS 里绑定了一个 HTML 里不存在的 id"这种错
会让按钮直接失效且不报错，必须靠静态检查兜住。
"""

from __future__ import annotations

import re
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "src" / "desktop_organizer" / "web" / "index.html"


def _html() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_index_exists():
    assert INDEX.is_file()


def test_every_bound_element_id_exists_in_html():
    """$("xxx").onclick / $("xxx").disabled 里的 id 必须真实存在。"""
    html = _html()
    declared = set(re.findall(r'id="([A-Za-z0-9_]+)"', html))
    used = set(re.findall(r'\$\("([A-Za-z0-9_]+)"\)', html))
    missing = sorted(used - declared)
    assert not missing, f"JS 引用了不存在的元素 id: {missing}"


def test_selection_shortcuts_are_present():
    """一键全选 / 全不选是用户明确要求的功能。"""
    html = _html()
    assert 'id="btnSelAll"' in html
    assert 'id="btnSelNone"' in html
    assert '$("btnSelAll").onclick' in html
    assert '$("btnSelNone").onclick' in html


def test_no_external_network_resources():
    """界面必须完全离线可用：不允许 CDN / 远程字体 / 外部脚本。"""
    html = _html()
    for pat in ("http://", "https://", "//cdn.", "src=\"//"):
        assert pat not in html, f"界面出现了外部资源引用: {pat}"
