"""偏好库：持久化、原子写、损坏恢复、改判累加。"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

import pytest

from desktop_organizer.constants import PROJECT_ROOT
from desktop_organizer.model import FileItem, Proposal
from desktop_organizer.store import PreferenceStore

SANDBOX = PROJECT_ROOT / "sandbox" / "pytest-tmp"


def _item(name: str, ext: str) -> FileItem:
    return FileItem(
        path=str(SANDBOX / name),
        name=name,
        ext=ext,
        size=10,
        mtime=time.time(),
    )


def _choice(item: FileItem, category: str, importance: str) -> Proposal:
    return Proposal(
        path=item.path,
        target_dir=f"{category}/{importance}",
        category=category,
        importance=importance,
        confidence=1.0,
        reasons=["用户改判"],
    )


@pytest.fixture()
def store_path() -> Path:
    directory = SANDBOX / ("store-" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=True)
    yield directory / "preferences.json"
    shutil.rmtree(directory, ignore_errors=True)


def test_lookup_miss_returns_none(store_path: Path) -> None:
    store = PreferenceStore(store_path)
    assert store.lookup(_item("a.png", ".png")) is None


def test_remember_persists_across_instances(store_path: Path) -> None:
    item = _item("a.png", ".png")
    store = PreferenceStore(store_path)
    store.remember(item, proposal=None, user_choice=_choice(item, "文档", "high"))

    reloaded = PreferenceStore(store_path)
    hit = reloaded.lookup(item)
    assert hit is not None
    assert hit.category == "文档"
    assert hit.importance == "high"


def test_second_remember_becomes_strong_preference(store_path: Path) -> None:
    item = _item("a.png", ".png")
    store = PreferenceStore(store_path)
    store.remember(item, None, _choice(item, "文档", "high"))
    first = store.lookup(item)
    assert first is not None
    assert first.confidence < 0.95

    store.remember(item, None, _choice(item, "文档", "high"))
    second = store.lookup(item)
    assert second is not None
    assert second.confidence == pytest.approx(0.95)

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert raw["ext_overrides"][".png"]["count"] == 2


def test_name_override_for_extensionless_file(store_path: Path) -> None:
    item = _item("我的笔记", "")
    store = PreferenceStore(store_path)
    store.remember(item, None, _choice(item, "文档", "medium"))
    hit = PreferenceStore(store_path).lookup(item)
    assert hit is not None
    assert hit.category == "文档"
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert "我的笔记" in raw["name_overrides"]


def test_atomic_save_leaves_no_tmp_file(store_path: Path) -> None:
    store = PreferenceStore(store_path)
    store.save()
    leftovers = [p.name for p in store_path.parent.iterdir()]
    assert leftovers == ["preferences.json"]


def test_corrupt_json_is_quarantined_and_reset(store_path: Path) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text("{ this is not json", encoding="utf-8")

    store = PreferenceStore(store_path)  # 不得抛异常
    assert store.lookup(_item("a.png", ".png")) is None
    assert (store_path.parent / "preferences.json.bak").exists()


def test_export_rules_promotes_strong_override(store_path: Path) -> None:
    item = _item("a.png", ".png")
    store = PreferenceStore(store_path)
    store.remember(item, None, _choice(item, "文档", "high"))
    store.remember(item, None, _choice(item, "文档", "high"))

    rules = store.export_rules()
    assert isinstance(rules, list)
    assert json.dumps(rules, ensure_ascii=False)
    ext_rule = next(r for r in rules if r["matcher"].get("ext_in") == [".png"])
    assert ext_rule["target_category"] == "文档"
    assert ext_rule["confidence"] == pytest.approx(0.95)
