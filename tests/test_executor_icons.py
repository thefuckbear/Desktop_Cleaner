"""执行器与图标快照的联动：整理前拍照、回滚后写回。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from desktop_organizer import executor, iconpos, journal
from desktop_organizer.model import Plan, PlanAction


def _plan(root: Path, actions: list[tuple[str, str]]) -> Plan:
    return Plan(
        plan_id="p-icons",
        root=str(root),
        created_at="2026-11-03T00:00:00",
        actions=[
            PlanAction(action_id=f"a{i}", src=str(root / name), dst=str(root / rel), kind="move")
            for i, (name, rel) in enumerate(actions, start=1)
        ],
    )


def _fake_snapshot() -> dict:
    return iconpos.build_snapshot(
        [("x.txt", 0, 5), ("keep.txt", 75, 5), ("gone.txt", 0, 109)], cell_w=75, cell_h=104
    )


def _snapshot_file(journal_id: str) -> Path:
    return journal.journal_dir() / "icons" / f"{journal_id}.json"


def _patch_live_snapshot(monkeypatch, snap: dict) -> list[int]:
    calls: list[int] = []

    def _snap(*, cell_w: int = 75, cell_h: int = 104) -> dict:
        calls.append(1)
        return snap

    monkeypatch.setattr(iconpos, "snapshot_live", _snap)
    return calls


def test_execute_saves_icon_snapshot_before_moving(tmp_path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "x.txt").write_text("x", encoding="utf-8")
    calls = _patch_live_snapshot(monkeypatch, _fake_snapshot())

    result = executor.execute(_plan(root, [("x.txt", "文档/x.txt")]), dry_run=False, capture_icons=True)

    assert result.applied == 1
    assert calls, "整理前必须给桌面拍一张坐标快照"
    saved = _snapshot_file(result.journal_id)
    assert saved.is_file(), f"快照应落到 {saved}"
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["items"]["x.txt"]["x"] == 0


def test_dry_run_does_not_take_snapshot(tmp_path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "x.txt").write_text("x", encoding="utf-8")
    calls = _patch_live_snapshot(monkeypatch, _fake_snapshot())

    result = executor.execute(_plan(root, [("x.txt", "文档/x.txt")]), capture_icons=True)

    assert result.applied == 1
    assert calls == []
    assert result.journal_id == ""


def test_snapshot_is_skipped_for_non_desktop_roots(tmp_path, monkeypatch) -> None:
    """整理的是普通目录时不该去读 Explorer 的桌面控件（又慢又没意义）。"""
    root = tmp_path / "root"
    root.mkdir()
    (root / "x.txt").write_text("x", encoding="utf-8")
    calls = _patch_live_snapshot(monkeypatch, _fake_snapshot())
    monkeypatch.setattr(iconpos, "is_desktop_path", lambda _p: False)

    result = executor.execute(_plan(root, [("x.txt", "文档/x.txt")]), dry_run=False)

    assert result.applied == 1
    assert calls == []


def test_snapshot_happens_automatically_for_the_desktop_root(tmp_path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "x.txt").write_text("x", encoding="utf-8")
    calls = _patch_live_snapshot(monkeypatch, _fake_snapshot())
    monkeypatch.setattr(iconpos, "is_desktop_path", lambda _p: True)

    result = executor.execute(_plan(root, [("x.txt", "文档/x.txt")]), dry_run=False)

    assert result.applied == 1
    assert calls == [1], "整理桌面本身时必须自动抓一次快照"
    assert _snapshot_file(result.journal_id).is_file()


def test_rollback_restores_positions_from_the_snapshot(tmp_path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "x.txt").write_text("x", encoding="utf-8")
    _patch_live_snapshot(monkeypatch, _fake_snapshot())

    applied = executor.execute(_plan(root, [("x.txt", "文档/x.txt")]), dry_run=False, capture_icons=True)
    assert applied.journal_id

    captured: dict = {}

    def _restore(snapshot, *, current_names, write_position, get_autoarrange, set_autoarrange, **_kw):
        captured["snapshot"] = snapshot
        captured["current_names"] = list(current_names)
        captured["has_verifier"] = _kw.get("read_positions") is not None
        return {
            "restored": 2,
            "skipped": 1,
            "autoarrange_was_on": True,
            "errors": [],
            "planned": 2,
        }

    monkeypatch.setattr(iconpos, "restore_positions", _restore)
    monkeypatch.setattr(iconpos, "iter_items", lambda: [("x.txt", 0, 5)])

    result = executor.rollback(applied.journal_id)

    assert result.rolled_back == 1
    assert captured["current_names"] == ["x.txt"]
    assert captured["snapshot"]["items"]["x.txt"]["x"] == 0
    assert captured["has_verifier"] is True, "写回必须带回读校验，否则被 Explorer 覆盖也不会知道"
    assert result.icons is not None
    assert result.icons["restored"] == 2


def test_rollback_without_snapshot_does_not_crash(tmp_path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "x.txt").write_text("x", encoding="utf-8")
    _patch_live_snapshot(monkeypatch, _fake_snapshot())
    applied = executor.execute(_plan(root, [("x.txt", "文档/x.txt")]), dry_run=False, capture_icons=True)

    _snapshot_file(applied.journal_id).unlink()

    def _boom(*_a, **_k):  # pragma: no cover - 不该被调用
        raise AssertionError("没有快照时不应尝试写回坐标")

    monkeypatch.setattr(iconpos, "restore_positions", _boom)
    result = executor.rollback(applied.journal_id)

    assert result.rolled_back == 1
    assert result.icons is None


def test_snapshot_failure_does_not_block_the_move(tmp_path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "x.txt").write_text("x", encoding="utf-8")

    def _explode(**_kwargs):
        raise OSError("读不到桌面控件")

    monkeypatch.setattr(iconpos, "snapshot_live", _explode)

    result = executor.execute(_plan(root, [("x.txt", "文档/x.txt")]), dry_run=False, capture_icons=True)

    assert result.applied == 1
    assert any("图标" in e for e in result.errors)


def test_icon_restore_can_be_skipped(tmp_path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "x.txt").write_text("x", encoding="utf-8")
    _patch_live_snapshot(monkeypatch, _fake_snapshot())
    applied = executor.execute(_plan(root, [("x.txt", "文档/x.txt")]), dry_run=False, capture_icons=True)

    def _boom(*_a, **_k):  # pragma: no cover
        raise AssertionError("显式关闭时不应写回坐标")

    monkeypatch.setattr(iconpos, "restore_positions", _boom)
    result = executor.rollback(applied.journal_id, restore_icons=False)

    assert result.rolled_back == 1
    assert result.icons is None


@pytest.mark.parametrize("value", ["1", "true", "yes"])
def test_settings_like_strings_are_not_treated_as_enabled(tmp_path, value) -> None:
    """回归：图标写回只在显式真值时发生，字符串一律不算。"""
    assert iconpos.plan_restore({"items": {}}, current_names=["a"]) == []
