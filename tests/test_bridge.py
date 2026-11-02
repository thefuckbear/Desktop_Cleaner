"""GUI 桥接层测试：前端只能通过这里触达核心，且默认不写盘。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from desktop_organizer import bridge, guard


def _make(root: Path, names: list[str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for n in names:
        (root / n).write_bytes(b"z" * 12)


def test_bridge_scan_returns_json_safe_rows(tmp_path: Path) -> None:
    _make(tmp_path, ["a.png", "b.pdf", "c.zip"])
    b = bridge.Bridge(root=str(tmp_path), depth=1, store_path=tmp_path / "pref.json")
    payload = b.scan()
    # 必须能直接序列化成 JSON（前端要 transport）
    json.dumps(payload)
    assert payload["total"] >= 3
    names = {row["name"] for row in payload["rows"]}
    assert {"a.png", "b.pdf", "c.zip"} <= names
    row = payload["rows"][0]
    for key in ("path", "name", "category", "importance", "confidence", "target_dir", "action_id"):
        assert key in row


def test_bridge_rejects_system_dir(tmp_path: Path) -> None:
    b = bridge.Bridge(root=str(tmp_path), depth=1, store_path=tmp_path / "pref.json")
    b.root = r"C:\Windows\System32"
    with pytest.raises(guard.GuardError):
        b.scan()


def test_bridge_apply_defaults_to_dry_run(tmp_path: Path) -> None:
    _make(tmp_path, ["a.png", "b.pdf"])
    b = bridge.Bridge(root=str(tmp_path), depth=1, store_path=tmp_path / "pref.json")
    b.scan()
    b.plan()
    result = b.apply()  # 不传 dry_run，必须走默认 dry-run
    assert result["dry_run"] is True
    assert result["applied"] >= 1
    # 文件必须一个都没动
    assert not (tmp_path / "图片").exists()
    assert (tmp_path / "a.png").is_file()


def test_bridge_apply_real_move_and_rollback(tmp_path: Path) -> None:
    _make(tmp_path, ["a.png", "b.pdf"])
    b = bridge.Bridge(root=str(tmp_path), depth=1, store_path=tmp_path / "pref.json")
    b.scan()
    b.plan()
    result = b.apply(dry_run=False)
    assert result["applied"] == 2
    assert not (tmp_path / "a.png").exists()
    journal_id = result["journal_id"]
    assert journal_id

    back = b.rollback()
    assert back["rolled_back"] == 2
    assert (tmp_path / "a.png").is_file()
    assert (tmp_path / "b.pdf").is_file()


def test_bridge_only_applies_selected_actions(tmp_path: Path) -> None:
    _make(tmp_path, ["a.png", "b.pdf", "c.zip"])
    b = bridge.Bridge(root=str(tmp_path), depth=1, store_path=tmp_path / "pref.json")
    b.scan()
    plan = b.plan()
    chosen = [r["action_id"] for r in plan["rows"] if r["name"] == "a.png"]
    result = b.apply(action_ids=chosen, dry_run=False)
    assert result["applied"] == 1
    assert not (tmp_path / "a.png").exists()
    assert (tmp_path / "b.pdf").is_file()


def test_bridge_remember_choice_persists(tmp_path: Path) -> None:
    _make(tmp_path, ["weird.xyz"])
    pref = tmp_path / "pref.json"
    b = bridge.Bridge(root=str(tmp_path), depth=1, store_path=pref)
    b.scan()
    b.plan()
    row = b.plan()["rows"][0]
    ok = b.remember(path=row["path"], category="代码", importance="high", target_dir="代码/重要")
    assert ok["saved"] is True
    assert pref.is_file()
    # 新实例仍能读到（落盘生效）
    b2 = bridge.Bridge(root=str(tmp_path), depth=1, store_path=pref)
    again = b2.plan_for(row["path"])
    assert again is not None
    assert again["category"] == "代码"


def test_bridge_journals_lists_history(tmp_path: Path) -> None:
    _make(tmp_path, ["a.png"])
    b = bridge.Bridge(root=str(tmp_path), depth=1, store_path=tmp_path / "pref.json")
    b.scan()
    b.plan()
    b.apply(dry_run=False)
    payload = b.journals()
    json.dumps(payload)
    assert payload["total"] >= 1


# ---------- 写盘许可开关（前端开关的唯一后端出口）----------


def test_bridge_settings_deny_by_default(tmp_path: Path) -> None:
    b = bridge.Bridge(
        root=str(tmp_path),
        store_path=tmp_path / "pref.json",
        settings_path=tmp_path / "settings.json",
    )
    payload = b.settings()
    json.dumps(payload)
    assert payload["allow_user_dirs"] is False


def test_bridge_set_allow_user_dirs_persists(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.json"
    b = bridge.Bridge(root=str(tmp_path), settings_path=settings_file)
    assert b.set_allow_user_dirs(True)["allow_user_dirs"] is True

    # 新实例 = 下次启动，必须还记得
    again = bridge.Bridge(root=str(tmp_path), settings_path=settings_file)
    assert again.settings()["allow_user_dirs"] is True
    assert again.set_allow_user_dirs(False)["allow_user_dirs"] is False
    assert bridge.Bridge(root=str(tmp_path), settings_path=settings_file).settings()["allow_user_dirs"] is False


def test_bridge_apply_uses_the_persisted_permission(fake_desktop: Path) -> None:
    """开关关着时一条都不动；打开后同样的计划就能真移动。"""
    _make(fake_desktop, ["a.png", "b.pdf"])
    settings_file = fake_desktop / "settings.json"
    b = bridge.Bridge(
        root=str(fake_desktop),
        depth=1,
        store_path=fake_desktop / "pref.json",
        settings_path=settings_file,
    )
    b.scan()
    b.plan()

    blocked = b.apply(dry_run=False)
    assert blocked["applied"] == 0
    assert (fake_desktop / "a.png").is_file()
    assert any("用户目录" in e for e in blocked["errors"])

    b.set_allow_user_dirs(True)
    done = b.apply(dry_run=False)
    assert done["applied"] == 2
    assert not (fake_desktop / "a.png").exists()

    back = b.rollback()
    assert back["rolled_back"] == 2
    assert (fake_desktop / "a.png").is_file()
