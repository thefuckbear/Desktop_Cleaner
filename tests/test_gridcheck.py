"""桌面格子占用比对：用「哪些格子有图标」来验收回滚是否真的复原。"""

from __future__ import annotations

from desktop_organizer import iconpos, gridcheck


def _snap(entries):
    return iconpos.build_snapshot(entries, cell_w=75, cell_h=104)


def test_grid_occupancy_returns_sorted_cells() -> None:
    snap = _snap([("a", 0, 5), ("b", 75, 5), ("c", 0, 109)])
    assert gridcheck.grid_occupancy(snap) == [(0, 0), (0, 1), (1, 0)]


def test_compare_grids_reports_same_when_identical() -> None:
    a = _snap([("a", 0, 5), ("b", 75, 5)])
    b = _snap([("a", 0, 5), ("b", 75, 5)])
    diff = gridcheck.compare_grids(a, b)
    assert diff["same"] is True
    assert diff["missing_cells"] == []
    assert diff["extra_cells"] == []


def test_compare_grids_detects_missing_and_extra_cells() -> None:
    before = _snap([("a", 0, 5), ("b", 75, 5)])
    after = _snap([("a", 75, 5), ("b", 150, 5)])
    diff = gridcheck.compare_grids(before, after)
    assert diff["same"] is False
    assert diff["missing_cells"] == [(0, 0)]
    assert diff["extra_cells"] == [(2, 0)]


def test_compare_grids_counts_name_moved_between_cells() -> None:
    before = _snap([("a", 0, 5), ("b", 75, 5)])
    after = _snap([("a", 75, 5), ("b", 0, 5)])
    diff = gridcheck.compare_grids(before, after)
    assert sorted(diff["moved_names"]) == ["a", "b"]


def test_occupied_cells_from_flat_image_is_empty() -> None:
    img = gridcheck.make_blank_image(cols=3, rows=2, cell_w=75, cell_h=104)
    assert gridcheck.occupied_cells_from_image(img, cell_w=75, cell_h=104, cols=3, rows=2) == []


def test_occupied_cells_from_image_detects_painted_cell() -> None:
    img = gridcheck.make_blank_image(cols=3, rows=2, cell_w=75, cell_h=104)
    gridcheck.paint_cell(img, col=1, row=1, cell_w=75, cell_h=104)
    cells = gridcheck.occupied_cells_from_image(img, cell_w=75, cell_h=104, cols=3, rows=2)
    assert cells == [(1, 1)]


def test_occupied_cells_respects_threshold() -> None:
    img = gridcheck.make_blank_image(cols=2, rows=1, cell_w=75, cell_h=104)
    gridcheck.paint_cell(img, col=0, row=0, cell_w=75, cell_h=104, coverage=0.001)
    # 默认阈值下「一个像素的亮点」不算占用；把阈值调低到 0.0001 就应该能认出来。
    assert gridcheck.occupied_cells_from_image(img, cell_w=75, cell_h=104, cols=2, rows=1) == []
    assert gridcheck.occupied_cells_from_image(
        img, cell_w=75, cell_h=104, cols=2, rows=1, min_ratio=0.0001
    ) == [(0, 0)]


def test_report_text_mentions_missing_and_extra() -> None:
    before = _snap([("a", 0, 5)])
    after = _snap([("b", 225, 5)])
    text = gridcheck.report_text(before, after)
    assert "未回到原位" in text or "缺失" in text
    assert "多出" in text


def test_report_text_is_positive_when_identical() -> None:
    snap = _snap([("a", 0, 5)])
    text = gridcheck.report_text(snap, snap)
    assert "一致" in text
