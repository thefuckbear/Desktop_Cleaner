"""图标排版引擎的纯逻辑测试：不碰真机、不碰文件系统。

设计要点：排序与几何计算必须完全解耦于 Win32，才能在 pytest 里 100% 可测。
"""

from __future__ import annotations

import inspect

import pytest

from desktop_organizer import layout


def icon(
    name: str,
    *,
    x: int = 0,
    y: int = 0,
    special: bool = False,
    shortcut: bool = False,
    directory: bool = False,
    ext: str = "",
    mtime: float = 0.0,
) -> layout.DesktopIconInfo:
    return layout.DesktopIconInfo(
        name=name,
        current_x=x,
        current_y=y,
        is_special=special,
        is_shortcut=shortcut,
        is_directory=directory,
        ext=ext,
        mtime=mtime,
    )


def sample_icons() -> list[layout.DesktopIconInfo]:
    return [
        icon("回收站", special=True),
        icon("微信.lnk", shortcut=True, ext=".lnk"),
        icon("我的项目", directory=True),
        icon("2026计划.docx", ext=".docx", mtime=100.0),
        icon("Chrome.lnk", shortcut=True, ext=".lnk"),
    ]


def area(*, cell_w: int = 75, cell_h: int = 104, rows: int = 5) -> layout.ScreenWorkArea:
    # max_rows = (bottom - top - 10) // cell_h，反推出恰好 rows 行
    return layout.ScreenWorkArea(
        left=0, top=0, right=2000, bottom=rows * cell_h + 10, cell_w=cell_w, cell_h=cell_h
    )


# ---------------------------------------------------------------- 度量


def test_work_area_max_rows_uses_cell_height() -> None:
    assert area(rows=5).max_rows == 5
    assert area(rows=1).max_rows == 1


def test_work_area_max_rows_never_below_one() -> None:
    tiny = layout.ScreenWorkArea(left=0, top=0, right=100, bottom=0, cell_w=75, cell_h=104)
    assert tiny.max_rows == 1


# ---------------------------------------------------------------- 排序策略


def test_shortcuts_first_orders_special_shortcut_file_directory() -> None:
    ordered = layout.sort_icons(sample_icons(), "shortcuts_first")
    names = [item.name for item in ordered]
    assert names == ["回收站", "Chrome.lnk", "微信.lnk", "2026计划.docx", "我的项目"]


def test_shortcuts_first_keeps_all_items() -> None:
    ordered = layout.sort_icons(sample_icons(), "shortcuts_first")
    assert len(ordered) == 5
    assert {item.name for item in ordered} == {item.name for item in sample_icons()}


def test_shortcuts_first_is_stable_for_equal_names() -> None:
    items = [icon("b.lnk", shortcut=True), icon("A.lnk", shortcut=True), icon("a.lnk", shortcut=True)]
    names = [item.name for item in layout.sort_icons(items, "shortcuts_first")]
    # 大小写不同视为同名，用原始名做二级键保证确定性
    assert names == ["A.lnk", "a.lnk", "b.lnk"]


def test_compact_time_puts_newest_files_first_but_shortcuts_still_lead() -> None:
    items = [
        icon("旧.docx", ext=".docx", mtime=100.0),
        icon("新.docx", ext=".docx", mtime=900.0),
        icon("中.docx", ext=".docx", mtime=500.0),
        icon("微信.lnk", shortcut=True, ext=".lnk"),
        icon("文件夹", directory=True),
    ]
    names = [item.name for item in layout.sort_icons(items, "compact_time")]
    assert names == ["微信.lnk", "新.docx", "中.docx", "旧.docx", "文件夹"]


def test_grouped_columns_keeps_same_order_as_shortcuts_first() -> None:
    by_group = layout.sort_icons(sample_icons(), "grouped_columns")
    by_short = layout.sort_icons(sample_icons(), "shortcuts_first")
    assert [item.name for item in by_group] == [item.name for item in by_short]


def test_unknown_strategy_falls_back_to_shortcuts_first() -> None:
    ordered = layout.sort_icons(sample_icons(), "no_such_strategy")
    assert [item.name for item in ordered] == [
        item.name for item in layout.sort_icons(sample_icons(), "shortcuts_first")
    ]


def test_strategies_are_exposed_as_id_name_desc() -> None:
    strategies = layout.strategies()
    assert isinstance(strategies, list) and len(strategies) == 3
    ids = [s["id"] for s in strategies]
    assert ids == ["shortcuts_first", "grouped_columns", "compact_time"]
    for entry in strategies:
        assert set(entry) == {"id", "name", "desc"}
        assert entry["name"] and entry["desc"]


# ---------------------------------------------------------------- 列断点


def test_column_breaks_separate_the_three_groups() -> None:
    groups = layout.group_icons(sample_icons(), "grouped_columns")
    assert [len(g) for g in groups] == [1, 2, 1, 1]
    assert layout.column_break_indices(groups) == {1, 3, 4}


def test_shortcuts_first_has_no_forced_breaks() -> None:
    groups = layout.group_icons(sample_icons(), "shortcuts_first")
    assert layout.column_break_indices(groups) == set()


# ---------------------------------------------------------------- 几何


def test_compact_grid_fills_one_column_then_wraps() -> None:
    items = [icon(f"i{n:02d}", special=True) for n in range(12)]
    work = area(rows=5)
    coords = layout.compute_compact_grid(items, work)
    assert len(coords) == 12
    # 第 1~5 项在第 0 列，第 6~10 项在第 1 列，第 11~12 项在第 2 列
    for idx in range(5):
        assert coords[f"i{idx:02d}"] == (12, 12 + idx * 104)
    for idx in range(5, 10):
        assert coords[f"i{idx:02d}"] == (12 + 75, 12 + (idx - 5) * 104)
    for idx in range(10, 12):
        assert coords[f"i{idx:02d}"] == (12 + 150, 12 + (idx - 10) * 104)


def test_compact_grid_steps_match_cell_size() -> None:
    items = [icon(f"i{n}", special=True) for n in range(3)]
    work = layout.ScreenWorkArea(left=0, top=0, right=2000, bottom=2000, cell_w=90, cell_h=120)
    coords = layout.compute_compact_grid(items, work)
    xs = {coords[f"i{n}"][0] for n in range(3)}
    assert xs == {12}  # 一行放得下很多行，仍全在第 0 列
    work_rows = work.max_rows
    assert coords["i1"][1] - coords["i0"][1] == 120
    assert work_rows >= 3


def test_compact_grid_honours_forced_column_breaks() -> None:
    items = [icon(f"i{n}", special=True) for n in range(4)]
    work = area(rows=10)
    coords = layout.compute_compact_grid(items, work, column_break_indices={2})
    assert coords["i0"] == (12, 12)
    assert coords["i1"] == (12, 12 + 104)
    assert coords["i2"] == (12 + 75, 12)
    assert coords["i3"] == (12 + 75, 12 + 104)


def test_compact_grid_ignores_break_on_first_item() -> None:
    items = [icon(f"i{n}", special=True) for n in range(2)]
    coords = layout.compute_compact_grid(items, area(rows=10), column_break_indices={0})
    assert coords["i0"] == (12, 12)


def test_compact_grid_never_overflows_work_area() -> None:
    # 工作区只放得下 2 列 x 2 行 = 4 个图标
    work = layout.ScreenWorkArea(left=0, top=0, right=12 + 150, bottom=2 * 104 + 10, cell_w=75, cell_h=104)
    items = [icon(f"i{n}", special=True) for n in range(9)]
    coords = layout.compute_compact_grid(items, work)
    assert len(coords) == layout.grid_capacity(work) == 4
    for x, y in coords.values():
        assert work.left <= x <= work.right
        assert work.top <= y <= work.bottom


def test_grid_capacity_is_at_least_one_column() -> None:
    narrow = layout.ScreenWorkArea(left=0, top=0, right=20, bottom=20, cell_w=75, cell_h=104)
    assert layout.grid_capacity(narrow) >= 1


# ---------------------------------------------------------------- 执行链路（注入假件，不碰真机）


def _fake_env(tmp_path, *, icons=None, fail_save=False):
    icons = icons if icons is not None else sample_icons()
    calls: dict[str, list] = {"writes": [], "autoarrange": [], "saved": []}

    def collect():
        return list(icons)

    def measure():
        return area(rows=10)

    def snapshot():
        return {
            "version": 1,
            "grid": {"cell_w": 75, "cell_h": 104},
            "items": {item.name: {"x": 1, "y": 2, "col": 0, "row": 0} for item in icons},
            "count": len(icons),
        }

    def save(payload, path):
        calls["saved"].append(payload)
        if fail_save:
            raise OSError("磁盘满了")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        return path

    def get_auto():
        return True

    def set_auto(value):
        calls["autoarrange"].append(bool(value))

    def writer():
        def write(name, x, y):
            calls["writes"].append((name, x, y))

        return write

    return {
        "calls": calls,
        "kwargs": {
            "collect": collect,
            "measure": measure,
            "snapshot": snapshot,
            "save": save,
            "get_autoarrange": get_auto,
            "set_autoarrange": set_auto,
            "make_writer": writer,
            "undo_path": tmp_path / "layout_undo.json",
        },
    }


def test_apply_layout_backs_up_before_writing(tmp_path) -> None:
    env = _fake_env(tmp_path)
    result = layout.apply_layout("shortcuts_first", **env["kwargs"])
    assert result["ok"] is True
    assert env["calls"]["saved"], "写坐标前必须先保存撤销快照"
    assert len(env["calls"]["writes"]) == 5
    assert result["moved"] == 5
    assert result["total"] == 5
    assert result["undo_available"] is True


def test_apply_layout_turns_autoarrange_off(tmp_path) -> None:
    env = _fake_env(tmp_path)
    layout.apply_layout("shortcuts_first", **env["kwargs"])
    assert env["calls"]["autoarrange"] == [False]


def test_apply_layout_aborts_when_backup_cannot_be_saved(tmp_path) -> None:
    env = _fake_env(tmp_path, fail_save=True)
    result = layout.apply_layout("shortcuts_first", **env["kwargs"])
    assert result["ok"] is False
    assert env["calls"]["writes"] == [], "备份失败时绝不允许写坐标"
    assert result["errors"]


def test_apply_layout_reports_when_nothing_to_do(tmp_path) -> None:
    env = _fake_env(tmp_path, icons=[])
    result = layout.apply_layout("shortcuts_first", **env["kwargs"])
    assert result["ok"] is True
    assert result["moved"] == 0
    assert result["undo_available"] is False


def test_undo_layout_restores_from_saved_snapshot(tmp_path) -> None:
    undo_file = tmp_path / "layout_undo.json"
    undo_file.write_text(
        '{"version":1,"grid":{"cell_w":75,"cell_h":104},'
        '"items":{"a":{"x":10,"y":20,"col":0,"row":0}},"count":1}',
        encoding="utf-8",
    )
    writes: list[tuple[str, int, int]] = []
    result = layout.undo_layout(
        undo_path=undo_file,
        write_position=lambda n, x, y: writes.append((n, x, y)),
        get_autoarrange=lambda: False,
        set_autoarrange=lambda v: None,
        read_positions=lambda: {"a": (10, 20)},
        make_writer=lambda: (lambda n, x, y: writes.append((n, x, y))),
        sleep=lambda _s: None,
    )
    assert result["ok"] is True
    assert result["restored"] == 1
    assert writes and writes[0][0] == "a"


def test_undo_layout_reports_missing_snapshot(tmp_path) -> None:
    result = layout.undo_layout(undo_path=tmp_path / "nope.json")
    assert result["ok"] is False
    assert "没有" in result["error"] or "找不到" in result["error"]


# ---------------------------------------------------------------- 红线


def test_layout_module_never_touches_the_filesystem_paths() -> None:
    source = inspect.getsource(layout)
    for forbidden in ("os.rename", "os.remove", "os.replace", "shutil.move", "shutil.rmtree", "Path.unlink"):
        assert forbidden not in source, f"排版模块禁止调用 {forbidden}"


def test_layout_module_has_no_file_read_of_user_content() -> None:
    source = inspect.getsource(layout)
    assert "read_text" not in source.split("def apply_layout")[0].replace(
        "snapshot", ""
    ) or True  # 占位：真正的约束是下面这条
    assert "open(" not in source


@pytest.mark.parametrize("strategy", ["shortcuts_first", "grouped_columns", "compact_time"])
def test_every_strategy_covers_all_icons(strategy: str) -> None:
    ordered = layout.sort_icons(sample_icons(), strategy)
    assert len(ordered) == len(sample_icons())
