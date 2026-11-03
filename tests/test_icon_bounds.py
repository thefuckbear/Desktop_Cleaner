"""P8：分辨率 / DPI 变了之后，旧坐标不能把图标写到屏幕外面去。

背景：快照是按当时的屏幕算的。用户换了显示器、调了缩放，或者把笔记本接到外接屏，
旧坐标可能落在当前工作区之外——写回去图标就从桌面消失了，比「没回到原位」更糟。

所以写回前必须把坐标夹回当前工作区；夹过要如实报告，不能假装复原成功。
"""

from __future__ import annotations

import pytest

from desktop_organizer import iconpos


def _snapshot(entries):
    return iconpos.build_snapshot(entries, cell_w=75, cell_h=104)


def test_clamp_keeps_coordinate_inside():
    bounds = {"left": 0, "top": 0, "right": 1000, "bottom": 800, "cell_w": 75, "cell_h": 104}
    assert iconpos.clamp_position(100, 100, bounds) == (100, 100)


def test_clamp_pulls_back_horizontal_overflow():
    bounds = {"left": 0, "top": 0, "right": 1000, "bottom": 800, "cell_w": 75, "cell_h": 104}
    x, y = iconpos.clamp_position(5000, 100, bounds)
    assert 0 <= x < 1000
    assert y == 100


def test_clamp_pulls_back_vertical_overflow():
    bounds = {"left": 0, "top": 0, "right": 1000, "bottom": 800, "cell_w": 75, "cell_h": 104}
    x, y = iconpos.clamp_position(100, 9000, bounds)
    assert x == 100
    assert 0 <= y < 800


def test_clamp_handles_negative_coordinates():
    bounds = {"left": 0, "top": 0, "right": 1000, "bottom": 800, "cell_w": 75, "cell_h": 104}
    x, y = iconpos.clamp_position(-500, -900, bounds)
    assert x >= 0 and y >= 0


def test_clamp_respects_non_zero_origin():
    bounds = {"left": -1920, "top": 0, "right": 0, "bottom": 1080, "cell_w": 75, "cell_h": 104}
    x, y = iconpos.clamp_position(50, 300, bounds)
    assert x <= 0
    assert y == 300


def test_clamp_without_bounds_returns_input():
    assert iconpos.clamp_position(1234, 5678, None) == (1234, 5678)


def test_clamp_tolerates_broken_bounds():
    assert iconpos.clamp_position(10, 20, {"left": 0}) == (10, 20)


def test_restore_clamps_out_of_screen_targets_and_reports():
    snap = _snapshot([("a", 10, 10), ("b", 9000, 9000)])
    written: list[tuple[int, int]] = []

    def writer(name, x, y):
        written.append((x, y))

    result = iconpos.restore_positions(
        snap,
        current_names=["a", "b"],
        write_position=writer,
        get_autoarrange=lambda: False,
        set_autoarrange=lambda _v: None,
        bounds={"left": 0, "top": 0, "right": 1000, "bottom": 800, "cell_w": 75, "cell_h": 104},
    )
    assert len(written) == 2
    assert all(0 <= x < 1000 and 0 <= y < 800 for x, y in written)
    assert result["clamped"] == 1
    assert any("屏幕外" in e or "工作区" in e for e in result["errors"])


def test_restore_without_bounds_writes_snapshot_coordinates_verbatim():
    snap = _snapshot([("a", 9000, 9000)])
    written: list[tuple[int, int]] = []
    result = iconpos.restore_positions(
        snap,
        current_names=["a"],
        write_position=lambda name, x, y: written.append((x, y)),
        get_autoarrange=lambda: False,
        set_autoarrange=lambda _v: None,
    )
    assert written == [(9000, 9000)]
    assert result["clamped"] == 0


def test_work_area_bounds_shape_matches_clamp_expectation():
    """layout.measure_work_area 的返回值要能直接喂给 clamp——两边字段名必须对齐。"""
    from desktop_organizer import layout

    wa = layout.ScreenWorkArea(left=0, top=0, right=1920, bottom=1040, cell_w=75, cell_h=104)
    bounds = layout.work_area_bounds(wa)
    assert bounds["left"] == 0 and bounds["right"] == 1920
    assert bounds["bottom"] == 1040
    assert iconpos.clamp_position(5000, 5000, bounds)[0] < 1920
