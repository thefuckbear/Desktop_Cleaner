"""分类器与规则引擎的行为测试（TDD：先失败，再实现）。"""

from __future__ import annotations

import json
import time

import pytest

from desktop_organizer.classify import classify
from desktop_organizer.model import FileItem, Proposal
from desktop_organizer.rules import (
    DEFAULT_RULES,
    Rule,
    match,
    rules_from_dicts,
    rules_to_dicts,
)
from desktop_organizer.store import PreferenceStore

DAY = 86400.0
SANDBOX = r"C:\Users\HY\Desktop\Projects\Desktop_Cleaner\sandbox\pytest-tmp"


@pytest.fixture()
def sandbox_dir():
    """每个用例独立目录，用完清理，避免偏好计数跨用例累积。"""
    import shutil
    import uuid
    from pathlib import Path

    directory = Path(SANDBOX) / ("classify-" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=True)
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


def make(
    name: str,
    *,
    ext: str | None = None,
    size: int = 100,
    age_days: float | None = None,
    **kwargs,
) -> FileItem:
    """构造 FileItem，不触碰真实文件。age_days=None 表示 mtime 未知。"""
    if ext is None:
        ext = "." + name.rsplit(".", 1)[1].lower() if "." in name else ""
    mtime = 0.0 if age_days is None else time.time() - age_days * DAY
    return FileItem(
        path=SANDBOX + "\\" + name,
        name=name,
        ext=ext,
        size=size,
        mtime=mtime,
        **kwargs,
    )


@pytest.mark.parametrize(
    "name, expected",
    [
        ("photo.png", "图片"),
        ("report.docx", "文档"),
        ("sheet.xlsx", "表格"),
        ("deck.pptx", "演示"),
        ("manual.pdf", "PDF"),
        ("movie.mp4", "音视频"),
        ("bundle.zip", "压缩包"),
        ("setup.exe", "安装包"),
        ("app.py", "代码"),
        ("shortcut.lnk", "快捷方式"),
        ("font.ttf", "字体"),
        ("book.epub", "电子书"),
        ("data.dat", "其他"),
    ],
)
def test_extension_maps_to_category(name: str, expected: str) -> None:
    """13 个类别全部覆盖。"""
    assert classify(make(name, age_days=30)).category == expected


def test_extension_hit_confidence_and_reason() -> None:
    proposal = classify(make("photo.png", age_days=30))
    assert proposal.confidence == pytest.approx(0.9)
    assert "扩展名 .png → 图片" in " ".join(proposal.reasons)


def test_keyword_only_hit_gets_medium_confidence() -> None:
    proposal = classify(make("我的简历", age_days=30))
    assert proposal.category == "文档"
    assert proposal.confidence == pytest.approx(0.7)


def test_unknown_extension_falls_back() -> None:
    proposal = classify(make("data.dat", age_days=30))
    assert proposal.category == "其他"
    assert proposal.confidence == pytest.approx(0.3)
    assert proposal.importance == "low"


def test_target_dir_is_category_over_importance_dir() -> None:
    proposal = classify(make("photo.png", age_days=10))
    assert proposal.category == "图片"
    assert proposal.importance == "medium"
    assert proposal.target_dir == "图片/常用"


def test_recent_work_file_is_high_importance() -> None:
    assert classify(make("report.docx", age_days=3)).importance == "high"


def test_recent_but_non_work_file_stays_medium() -> None:
    assert classify(make("photo.png", age_days=3)).importance == "medium"


def test_stale_file_is_low_importance() -> None:
    assert classify(make("report.docx", age_days=120)).importance == "low"


def test_unknown_mtime_is_low_importance() -> None:
    assert classify(make("report.docx", age_days=None)).importance == "low"


def test_rule_hit_exposes_rule_id() -> None:
    proposal = classify(make("微信截图_20261102.png", age_days=10))
    assert proposal.rule_id == "rule-screenshot"
    assert proposal.category == "图片"
    assert proposal.importance == "high"


def test_rule_priority_picks_first_hit() -> None:
    item = make("photo.png", age_days=10)
    low = Rule(id="r-low", matcher={"ext_in": [".png"]}, target_category="文档", priority=10)
    high = Rule(id="r-high", matcher={"ext_in": [".png"]}, target_category="图片", priority=99)
    hit = match(item, [low, high])
    assert hit is not None
    assert hit.id == "r-high"


def test_rule_age_condition_requires_known_mtime() -> None:
    rule = Rule(id="r-new", matcher={"ext_in": [".zip"], "age_days_lt": 3}, target_category="压缩包", priority=50)
    assert match(make("bundle.zip", age_days=1), [rule]) is not None
    assert match(make("bundle.zip", age_days=None), [rule]) is None


def test_default_rules_json_roundtrip() -> None:
    payload = rules_to_dicts(DEFAULT_RULES)
    assert json.dumps(payload, ensure_ascii=False)
    assert [r.id for r in rules_from_dicts(payload)] == [r.id for r in DEFAULT_RULES]


def test_store_preference_wins_over_rules(sandbox_dir) -> None:
    """改判学习生效：store 里的选择优先于内置规则。"""
    store = PreferenceStore(sandbox_dir / "preferences.json")
    item = make("微信截图_20261102.png", age_days=10)
    original = classify(item)
    store.remember(
        item,
        original,
        Proposal(
            path=item.path,
            target_dir="文档/重要",
            category="文档",
            importance="high",
            confidence=1.0,
        ),
    )

    learned = classify(item, store)
    assert learned.category == "文档"
    assert learned.importance == "high"
    assert learned.confidence == pytest.approx(0.95)
    assert "沿用你的历史选择" in " ".join(learned.reasons)


def test_user_rule_from_store_overrides_builtin(sandbox_dir) -> None:
    """用户规则同 id 覆盖内置规则（通过 preferences.json 落盘）。"""
    path = sandbox_dir / "preferences.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "version": 1,
                "ext_overrides": {},
                "name_overrides": {},
                "rules": [
                    {
                        "id": "rule-screenshot",
                        "matcher": {"name_contains": ["截图"]},
                        "target_category": "文档",
                        "importance": "medium",
                        "confidence": 0.88,
                        "priority": 95,
                    }
                ],
                "stats": {},
            },
            fh,
            ensure_ascii=False,
        )
    store = PreferenceStore(path)
    proposal = classify(make("微信截图_1.png", age_days=10), store)
    assert proposal.category == "文档"
    assert proposal.importance == "medium"
    assert proposal.confidence == pytest.approx(0.88)
