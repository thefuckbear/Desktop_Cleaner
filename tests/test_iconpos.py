"""图标位置快照/写回的纯逻辑测试（不触碰真实桌面）。"""

from __future__ import annotations

from desktop_organizer import iconpos


def test_cell_of_maps_pixels_to_grid() -> None:
    assert iconpos.cell_of(0, 5, 75, 104) == (0, 0)
    assert iconpos.cell_of(74, 103, 75, 104) == (0, 0)
    assert iconpos.cell_of(74, 108, 75, 104) == (0, 1)
    assert iconpos.cell_of(75, 5, 75, 104) == (1, 0)
    assert iconpos.cell_of(0, 109, 75, 104) == (0, 1)
    assert iconpos.cell_of(150, 213, 75, 104) == (2, 2)


def test_build_snapshot_records_name_and_position() -> None:
    entries = [("HY", 0, 5), ("intro.mp3", 0, 109), ("OBS Studio", 75, 5)]
    snap = iconpos.build_snapshot(entries, cell_w=75, cell_h=104)
    assert snap["grid"] == {"cell_w": 75, "cell_h": 104}
    assert snap["items"]["intro.mp3"] == {"x": 0, "y": 109, "col": 0, "row": 1}
    assert snap["items"]["OBS Studio"]["col"] == 1
    assert snap["count"] == 3


def test_build_snapshot_keeps_first_occurrence_of_duplicate_names() -> None:
    entries = [("dup", 0, 5), ("dup", 75, 5)]
    snap = iconpos.build_snapshot(entries, cell_w=75, cell_h=104)
    assert snap["items"]["dup"]["x"] == 0
    assert snap["count"] == 1


def test_plan_restore_skips_names_that_no_longer_exist() -> None:
    entries = [("a", 0, 5), ("b", 0, 109), ("c", 75, 5)]
    snap = iconpos.build_snapshot(entries, cell_w=75, cell_h=104)
    plan = iconpos.plan_restore(snap, current_names=["a", "c", "new"])
    assert [p["name"] for p in plan] == ["a", "c"]
    assert plan[1] == {"name": "c", "x": 75, "y": 5}


def test_plan_restore_is_empty_for_empty_snapshot() -> None:
    snap = iconpos.build_snapshot([], cell_w=75, cell_h=104)
    assert iconpos.plan_restore(snap, current_names=["a"]) == []


def test_diff_positions_reports_moved_missing_and_extra() -> None:
    before = iconpos.build_snapshot(
        [("a", 0, 5), ("b", 0, 109), ("gone", 75, 5)], cell_w=75, cell_h=104
    )
    after = iconpos.build_snapshot(
        [("a", 0, 5), ("b", 75, 5), ("new", 150, 5)], cell_w=75, cell_h=104
    )
    diff = iconpos.diff_positions(before, after)
    assert diff["moved"] == [{"name": "b", "from": [0, 109], "to": [75, 5]}]
    assert diff["missing"] == ["gone"]
    assert diff["extra"] == ["new"]
    assert diff["same"] is False


def test_diff_positions_reports_same_when_identical() -> None:
    snap = iconpos.build_snapshot([("a", 0, 5)], cell_w=75, cell_h=104)
    diff = iconpos.diff_positions(snap, snap)
    assert diff["same"] is True
    assert diff["moved"] == []


def test_restore_positions_uses_injected_io_instead_of_real_desktop() -> None:
    written: list[tuple[str, int, int]] = []
    toggles: list[bool] = []
    snap = iconpos.build_snapshot(
        [("a", 0, 5), ("b", 0, 109)], cell_w=75, cell_h=104
    )

    result = iconpos.restore_positions(
        snap,
        current_names=["a", "b", "c"],
        write_position=lambda name, x, y: written.append((name, x, y)),
        get_autoarrange=lambda: True,
        set_autoarrange=lambda value: toggles.append(value),
    )

    assert written == [("a", 0, 5), ("b", 0, 109)]
    assert toggles == [False]
    assert result["restored"] == 2
    assert result["skipped"] == 0
    assert result["autoarrange_was_on"] is True


def test_restore_positions_leaves_autoarrange_alone_when_already_off() -> None:
    toggles: list[bool] = []
    snap = iconpos.build_snapshot([("a", 0, 5)], cell_w=75, cell_h=104)

    result = iconpos.restore_positions(
        snap,
        current_names=["a"],
        write_position=lambda *_: None,
        get_autoarrange=lambda: False,
        set_autoarrange=lambda value: toggles.append(value),
    )

    assert toggles == []
    assert result["autoarrange_was_on"] is False


def test_restore_positions_survives_write_failure() -> None:
    def boom(*_args) -> None:
        raise OSError("explorer 拒绝")

    snap = iconpos.build_snapshot([("a", 0, 5), ("b", 0, 109)], cell_w=75, cell_h=104)
    result = iconpos.restore_positions(
        snap,
        current_names=["a", "b"],
        write_position=boom,
        get_autoarrange=lambda: False,
        set_autoarrange=lambda value: None,
    )
    assert result["restored"] == 0
    assert result["skipped"] == 2
    assert any("explorer 拒绝" in e for e in result["errors"])


def test_snapshot_roundtrip_through_json(tmp_path) -> None:
    snap = iconpos.build_snapshot([("中文 名.txt", 0, 5)], cell_w=75, cell_h=104)
    path = tmp_path / "icons.json"
    iconpos.save_snapshot(snap, path)
    loaded = iconpos.load_snapshot(path)
    assert loaded == snap


def test_load_snapshot_returns_none_for_broken_file(tmp_path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{ not json", encoding="utf-8")
    assert iconpos.load_snapshot(path) is None
    assert iconpos.load_snapshot(tmp_path / "missing.json") is None


def test_position_writer_enumerates_icons_only_once(monkeypatch) -> None:
    """249 个图标时，逐个写坐标不能每次都重读整个 ListView。"""
    calls: list[str] = []

    def fake_lv() -> int:
        return 1234

    def fake_iter():
        calls.append("iter")
        return [("a", 0, 0), ("b", 75, 0)]

    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(iconpos, "desktop_listview", fake_lv)
    monkeypatch.setattr(iconpos, "iter_items", fake_iter)
    monkeypatch.setattr(
        iconpos._user32, "SendMessageW",
        lambda lv, msg, wparam, lparam: sent.append((wparam, lparam)) or 0,
    )

    write = iconpos.make_position_writer()
    write("a", 11, 2)
    write("b", 86, 2)

    assert calls == ["iter"], "枚举只应发生一次"
    assert sent == [(0, (2 << 16) | 11), (1, (2 << 16) | 86)]


def test_position_writer_raises_for_unknown_name(monkeypatch) -> None:
    monkeypatch.setattr(iconpos, "desktop_listview", lambda: 1234)
    monkeypatch.setattr(iconpos, "iter_items", lambda: [("a", 0, 0)])
    monkeypatch.setattr(iconpos._user32, "SendMessageW", lambda *a: 0)

    write = iconpos.make_position_writer()
    try:
        write("nope", 0, 0)
    except OSError as exc:
        assert "nope" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当抛出 OSError")
