"""图标网格步长必须实测，不能信系统给的常量。

实测（2026-11-03，2560x1440 @100%）：
- `GetSystemMetrics(38/39)`(SM_CXICONSPACING/SM_CYICONSPACING) = 75 / 75
- `LVM_GETITEMSPACING` = 96 / 81
- **桌面真实步长 = 75 / 104**（相邻图标 y 差恒为 104，如 2 / 106 / 210 / 314）

按 75 当行距排出来的坐标会落在 104 网格的格间，被顺手对齐后两个图标抢同一格。
所以步长只从「桌面上真实相邻图标的间距」里统计，取不到才回落到默认值。
"""

from __future__ import annotations

from desktop_organizer import iconpos, layout


def _items(coords):
    return [
        layout.DesktopIconInfo(
            name=f"i{i}",
            current_x=x,
            current_y=y,
            is_special=False,
            is_shortcut=False,
            is_directory=False,
            ext="",
            mtime=0.0,
        )
        for i, (x, y) in enumerate(coords)
    ]


def test_detects_vertical_step_from_single_column():
    items = _items([(11, 2), (11, 106), (11, 210), (11, 314)])
    w, h = layout.icon_step_from_positions(items)
    assert h == 104
    assert w == iconpos.DEFAULT_CELL_W


def test_detects_horizontal_step_from_single_row():
    items = _items([(11, 2), (86, 2), (161, 2)])
    w, h = layout.icon_step_from_positions(items)
    assert w == 75
    assert h == iconpos.DEFAULT_CELL_H


def test_detects_both_steps_from_two_columns():
    items = _items([(11, 2), (11, 106), (86, 2), (86, 106)])
    assert layout.icon_step_from_positions(items) == (75, 104)


def test_ignores_outliers_and_uses_the_common_step():
    items = _items([(11, 2), (11, 106), (11, 210), (500, 900)])
    _w, h = layout.icon_step_from_positions(items)
    assert h == 104


def test_falls_back_when_not_enough_icons():
    assert layout.icon_step_from_positions(_items([(11, 2)])) == (
        iconpos.DEFAULT_CELL_W,
        iconpos.DEFAULT_CELL_H,
    )
    assert layout.icon_step_from_positions([]) == (
        iconpos.DEFAULT_CELL_W,
        iconpos.DEFAULT_CELL_H,
    )


def test_ignores_absurd_differences():
    # 两个图标离得很远（比如分列），差 900px 不可能是步长
    items = _items([(11, 2), (11, 902)])
    _w, h = layout.icon_step_from_positions(items)
    assert h == iconpos.DEFAULT_CELL_H


def test_workspace_uses_measured_step_not_system_metric():
    """排版的格距必须来自实测，否则新坐标会落在旧网格的格间。"""
    items = _items([(11, 2), (11, 106), (11, 210), (86, 2), (86, 106)])
    wa = layout.measure_work_area(rect=(0, 0, 2560, 1392), icons=items)
    assert wa.cell_w == 75
    assert wa.cell_h == 104
    # 行数按真实行距算：(1392-10)//104 = 13
    assert wa.max_rows == 13


def test_workspace_falls_back_to_defaults_without_icons():
    wa = layout.measure_work_area(rect=(0, 0, 2560, 1392), icons=[])
    assert (wa.cell_w, wa.cell_h) == (iconpos.DEFAULT_CELL_W, iconpos.DEFAULT_CELL_H)
    # (1392-10)//104 = 13
    assert wa.max_rows == 13
