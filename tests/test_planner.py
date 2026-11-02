"""计划生成：过滤、目标路径、低置信降级、已在目标目录不生成动作。"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from desktop_organizer.constants import PROJECT_ROOT
from desktop_organizer.model import FileItem, Proposal
from desktop_organizer.planner import build_plan
from desktop_organizer.store import PreferenceStore

ROOT = str(PROJECT_ROOT / "sandbox" / "plan-root")
DAY = 86400.0


def item(name: str, *, age_days: float = 10, **kwargs) -> FileItem:
    ext = "." + name.rsplit(".", 1)[1].lower() if "." in name else ""
    return FileItem(
        path=os.path.join(ROOT, name),
        name=name,
        ext=ext,
        size=123,
        mtime=time.time() - age_days * DAY,
        **kwargs,
    )


@pytest.fixture()
def store_path() -> Path:
    directory = PROJECT_ROOT / "sandbox" / "pytest-tmp" / ("plan-" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=True)
    yield directory / "preferences.json"
    shutil.rmtree(directory, ignore_errors=True)


def test_skipped_items_are_ignored() -> None:
    plan = build_plan([item("a.png", skipped_reason="云占位符")], ROOT)
    assert plan.actions == []


def test_action_targets_full_absolute_path() -> None:
    plan = build_plan([item("a.png")], ROOT)
    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.src == os.path.join(ROOT, "a.png")
    assert action.dst == os.path.join(ROOT, "图片", "常用", "a.png")
    assert os.path.isabs(action.dst)
    assert action.action_id.startswith("act-")
    assert "扩展名 .png" in action.reason


def test_file_already_in_target_dir_produces_no_action() -> None:
    already = FileItem(
        path=os.path.join(ROOT, "图片", "常用", "a.png"),
        name="a.png",
        ext=".png",
        mtime=time.time() - 10 * DAY,
    )
    assert build_plan([already], ROOT).actions == []


def test_low_confidence_goes_to_other_with_warning() -> None:
    plan = build_plan([item("mystery.dat")], ROOT)
    assert len(plan.actions) == 1
    assert plan.actions[0].dst == os.path.join(ROOT, "其他", "归档", "mystery.dat")
    assert any("1 个文件置信度低" in w for w in plan.warnings)


def test_high_confidence_hits_are_not_warned() -> None:
    plan = build_plan([item("a.png")], ROOT)
    assert plan.warnings == []


def test_plan_is_json_serializable_and_has_ids() -> None:
    plan = build_plan([item("a.png")], ROOT)
    assert plan.plan_id.startswith("plan-")
    datetime.fromisoformat(plan.created_at)
    json.dumps(plan.to_dict(), ensure_ascii=False)


def test_store_preference_drives_plan(store_path: Path) -> None:
    target = item("mystery.dat")
    store = PreferenceStore(store_path)
    choice = Proposal(
        path=target.path,
        target_dir="文档/重要",
        category="文档",
        importance="high",
        confidence=1.0,
    )
    store.remember(target, None, choice)
    store.remember(target, None, choice)

    plan = build_plan([target], ROOT, store)
    assert plan.actions[0].dst == os.path.join(ROOT, "文档", "重要", "mystery.dat")
    assert plan.warnings == []


def test_plan_does_not_touch_filesystem(tmp_path=None) -> None:
    """纯计算：条目路径不存在时也照常出计划。"""
    ghost = item("ghost.png")
    assert not os.path.exists(ghost.path)
    assert len(build_plan([ghost], ROOT).actions) == 1
