"""桥接层的排版入口：只转发坐标操作，绝不碰文件。"""

from __future__ import annotations

import json

from desktop_organizer import bridge, iconpos, layout


def _brief(name: str, x: int, y: int) -> layout.DesktopIconInfo:
    return layout.DesktopIconInfo(
        name=name,
        current_x=x,
        current_y=y,
        is_special=False,
        is_shortcut=name.endswith(".lnk"),
        is_directory=False,
        ext=".lnk" if name.endswith(".lnk") else ".txt",
        mtime=1_700_000_000.0,
    )


def _area() -> layout.ScreenWorkArea:
    return layout.ScreenWorkArea(left=0, top=0, right=300, bottom=400, cell_w=75, cell_h=104)


def _patch_layout(monkeypatch, *, icons, writes):
    """把 layout 的真机依赖换成假件，保证测试绝不碰真实桌面。

    layout.apply_layout 的默认值是 iconpos 里的那几个函数，所以替换点也在 iconpos。
    """

    def _record(name: str, x: int, y: int) -> None:
        writes.append((name, x, y))

    monkeypatch.setattr(layout, "collect_icons", lambda: list(icons))
    monkeypatch.setattr(layout, "measure_work_area", lambda: _area())
    monkeypatch.setattr(iconpos, "get_autoarrange", lambda: False)
    monkeypatch.setattr(iconpos, "set_autoarrange", lambda value: None)
    monkeypatch.setattr(iconpos, "make_position_writer", lambda: _record)
    monkeypatch.setattr(
        iconpos,
        "snapshot_live",
        lambda: iconpos.build_snapshot([(i.name, i.current_x, i.current_y) for i in icons]),
    )
    # bridge 会显式传 read_positions=iconpos.read_positions_live，不替换的话
    # 单测就会去读真实桌面。返回空字典 = "读不到任何图标"，不会误判成没到位。
    monkeypatch.setattr(iconpos, "read_positions_live", lambda: {})


def test_get_layout_strategies_exposes_three(tmp_path) -> None:
    b = bridge.Bridge(root=str(tmp_path), settings_path=tmp_path / "settings.json")
    rows = b.get_layout_strategies()
    assert [r["id"] for r in rows] == ["shortcuts_first", "grouped_columns", "compact_time"]
    assert all(set(r) == {"id", "name", "desc"} for r in rows)


def test_apply_desktop_layout_writes_positions_and_keeps_undo(tmp_path, monkeypatch) -> None:
    writes: list = []
    icons = [_brief("b.txt", 0, 0), _brief("Chrome.lnk", 0, 104)]
    _patch_layout(monkeypatch, icons=icons, writes=writes)

    b = bridge.Bridge(root=str(tmp_path), settings_path=tmp_path / "settings.json")
    payload = json.loads(json.dumps(b.apply_desktop_layout("shortcuts_first")))

    assert payload["ok"] is True
    assert payload["total"] == 2
    assert payload["moved"] == 2
    assert payload["strategy"] == "shortcuts_first"
    assert payload["undo_available"] is True
    assert writes, "应该真的写了坐标"
    assert (tmp_path / "layout_undo.json").is_file()


def test_apply_layout_refuses_unknown_strategy_but_still_works(tmp_path, monkeypatch) -> None:
    writes: list = []
    _patch_layout(monkeypatch, icons=[_brief("a.txt", 0, 0)], writes=writes)
    b = bridge.Bridge(root=str(tmp_path), settings_path=tmp_path / "settings.json")
    payload = b.apply_desktop_layout("不存在的策略")
    assert payload["ok"] is True
    assert payload["strategy"] == "shortcuts_first"


def test_undo_desktop_layout_restores_from_backup(tmp_path, monkeypatch) -> None:
    writes: list = []
    icons = [_brief("a.txt", 150, 150)]
    _patch_layout(monkeypatch, icons=icons, writes=writes)
    b = bridge.Bridge(root=str(tmp_path), settings_path=tmp_path / "settings.json")
    b.apply_desktop_layout()

    # 撤销时把真机写回/回读也换掉，只验证协议不乱走
    monkeypatch.setattr(iconpos, "get_autoarrange", lambda: False)
    monkeypatch.setattr(iconpos, "set_autoarrange", lambda value: None)
    monkeypatch.setattr(iconpos, "make_position_writer", lambda: lambda name, x, y: None)
    monkeypatch.setattr(iconpos, "read_positions_live", lambda: {"a.txt": (150, 150)})

    result = b.undo_desktop_layout()
    assert result["ok"] is True
    assert result["restored"] >= 1


def test_undo_without_backup_reports_error(tmp_path) -> None:
    b = bridge.Bridge(root=str(tmp_path), settings_path=tmp_path / "settings.json")
    result = b.undo_desktop_layout()
    assert result["ok"] is False
    assert "撤销" in result["error"] or "layout_undo" in result["error"]


def test_undo_path_follows_settings_path(tmp_path) -> None:
    b = bridge.Bridge(root=str(tmp_path), settings_path=tmp_path / "sub" / "settings.json")
    assert b._layout_undo_path() == tmp_path / "sub" / "layout_undo.json"


def test_undo_path_defaults_when_settings_path_is_none(monkeypatch, tmp_path) -> None:
    from desktop_organizer import settings as settings_module

    monkeypatch.setattr(
        settings_module, "settings_path", lambda path=None: tmp_path / "settings.json"
    )
    b = bridge.Bridge(root=str(tmp_path))
    assert b._layout_undo_path() == tmp_path / "layout_undo.json"


def test_get_layout_sort_keys_exposes_composable_keys(tmp_path) -> None:
    b = bridge.Bridge(root=str(tmp_path), settings_path=tmp_path / "settings.json")
    rows = b.get_layout_sort_keys()
    ids = [r["id"] for r in rows]
    assert "system_first" in ids and "shortcuts_first" in ids and "by_category" in ids
    assert all(set(r) == {"id", "name", "desc"} for r in rows)


def test_apply_desktop_layout_accepts_composite_sort_keys(tmp_path, monkeypatch) -> None:
    writes: list = []
    icons = [_brief("回收站", 0, 0), _brief("Chrome.lnk", 0, 104)]
    icons[0] = layout.DesktopIconInfo(
        name="回收站",
        current_x=0,
        current_y=0,
        is_special=True,
        is_shortcut=False,
        is_directory=False,
        ext="",
        mtime=1_700_000_000.0,
        is_system=True,
    )
    _patch_layout(monkeypatch, icons=icons, writes=writes)

    b = bridge.Bridge(root=str(tmp_path), settings_path=tmp_path / "settings.json")
    payload = b.apply_desktop_layout(sort_keys=["system_first", "shortcuts_first", "by_name"])

    assert payload["ok"] is True
    assert payload["strategy"] == "system_first+shortcuts_first+by_name"
    assert writes[0][:2] == ("回收站", 12), f"系统图标必须排在左上角第一格，实际 {writes[:2]}"


def test_apply_desktop_layout_passes_a_reader_so_late_moves_are_detected(
    tmp_path, monkeypatch
) -> None:
    writes: list = []
    icons = [_brief("a.txt", 0, 0)]
    _patch_layout(monkeypatch, icons=icons, writes=writes)
    # 模拟 Explorer 把写进去的 (12,12) 挪到别处：有 reader 才会被发现并在 errors 里报出来
    monkeypatch.setattr(iconpos, "read_positions_live", lambda: {"a.txt": (500, 500)})

    b = bridge.Bridge(root=str(tmp_path), settings_path=tmp_path / "settings.json")
    payload = b.apply_desktop_layout()

    assert payload["misfit"] >= 1
    assert any("未就位" in e for e in payload["errors"])
