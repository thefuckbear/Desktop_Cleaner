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


def _css_rule(selector: str) -> str:
    """取某条样式规则的声明体（先剥掉注释，注释里也可能有花括号）。"""
    css = re.sub(r"/\*.*?\*/", "", _html(), flags=re.S)
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
    assert m, f"缺少样式: {selector}"
    return m.group(1)


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


def test_mini_buttons_override_global_button_width():
    """全局 button{width:100%} 会把小按钮拉成整行、把标题挤成竖排。

    这条规则一旦被删，界面会静默走样（截图才看得出来），必须测住。
    """
    body = _css_rule(".mini")
    assert "width:auto" in body, ".mini 必须覆盖全局 button 的 width:100%"
    assert "display:inline-flex" in body
    assert "flex:none" in body
    assert "white-space:nowrap" in body


def test_panel_header_text_does_not_wrap():
    """表头标题/计数被挤压时会一字一行，必须 nowrap。"""
    assert "white-space:nowrap" in _css_rule(".panel-hd h2")
    assert "white-space:nowrap" in _css_rule(".count")


def test_no_external_network_resources():
    """界面必须完全离线可用：不允许 CDN / 远程字体 / 外部脚本。"""
    html = _html()
    for pat in ("http://", "https://", "//cdn.", "src=\"//"):
        assert pat not in html, f"界面出现了外部资源引用: {pat}"


def test_user_dir_permission_switch_is_wired():
    """写盘许可必须能在界面上打开/关闭，且开关状态来自后端。

    这是"用户报无法移动"那个问题的正解：开关不接上，用户就只能看到一屏拒绝。
    """
    html = _html()
    assert 'id="btnPermit"' in html, "缺少写盘许可开关控件"
    assert '$("btnPermit").onclick' in html, "开关没有绑定点击"
    assert "set_allow_user_dirs" in html, "开关没有调用后端持久化接口"
    assert "settings()" in html, "界面启动时没有读取开关状态"


def test_rollback_log_mentions_timestamps_and_icon_positions():
    """回滚后必须说清"时间戳回来了"和"图标坐标也写回去了"。

    只报文件数量不够——用户上次就是因为图标没回原位而认为回滚失败。
    """
    html = _html()
    assert "修改时间" in html, "回滚提示没有说明时间戳已还原"
    assert "图标位置" in html, "回滚提示没有说明图标坐标已写回"
    assert "快照" in html, "回滚提示没有说明位置来自整理前的快照"
    assert "res.icons" in html, "回滚后没有读取 icons 结果"


def test_plan_does_not_precheck_anything():
    """用户明确要求：扫描后不要默认帮他勾选。

    这条锁住 plan() 里不再出现"按 confidence 自动填充 selected"的老逻辑。
    """
    html = _html()
    assert "confidence >= 0.55" not in html, "计划里又出现了按置信度自动勾选的老逻辑"
    assert "已默认勾选" not in html, "日志里仍在宣称默认勾选"
    assert "未默认勾选" in html, "日志没有告诉用户需要自己勾"


def test_search_and_sort_controls_exist():
    """用户要求的"按文件名搜索 + 按修改时间排序"必须真的接到界面上。"""
    html = _html()
    assert 'id="q"' in html, "缺少文件名搜索框"
    assert 'type="search"' in html
    assert '$("q").addEventListener("input"' in html

    assert 'id="sortBy"' in html, "缺少排序下拉"
    assert "$(\"sortBy\").addEventListener(\"change\"" in html
    for key in ("mtime-desc", "mtime", "name", "size-desc"):
        assert f'value="{key}"' in html, f"排序选项缺少 {key}"


def test_rows_keep_index_into_source_array():
    """排序/过滤后行下标必须回指 state.rows，否则点一行会改到别的文件。"""
    html = _html()
    assert "const i = state.rows.indexOf(r)" in html, "行下标没有回指原数组，排序后会点错文件"
    assert "data-edit=\"${i}\"" in html

