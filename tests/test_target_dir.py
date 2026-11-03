"""自由去向目录的校验与「单行/批量改去向」。

安全边界：用户能自由命名文件夹，但绝不能借这个名字把文件送出整理目录，
也不能写进系统目录。所有输入都要先过 targetdir.validate，再过 guard。
"""

from __future__ import annotations

import os

import pytest

from desktop_organizer import bridge, targetdir


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "..",
        "../x",
        "../../Windows",
        "foo/../../bar",
        "C:\\Windows",
        "C:/Windows",
        "/etc",
        "a:b",
        "a?b",
        "a*b",
        "a<b",
        "a|b",
        'a"b',
        "x" * 200,
    ],
)
def test_rejects_illegal_target(bad: str) -> None:
    ok, reason = targetdir.validate(bad, root="C:/tmp/root")
    assert ok is False
    assert reason


@pytest.mark.parametrize(
    "good,expected_parts",
    [
        ("2026/专案组", ("2026", "专案组")),
        ("临时脚本", ("临时脚本",)),
        ("a/b/c", ("a", "b", "c")),
        ("a//b", ("a", "b")),
    ],
)
def test_accepts_legal_target(good: str, expected_parts: tuple[str, ...]) -> None:
    ok, value = targetdir.validate(good, root="C:/tmp/root")
    assert ok is True
    assert tuple(part for part in value.split(os.sep) if part) == expected_parts


def test_rejects_escape_after_normpath(tmp_path) -> None:
    ok, _ = targetdir.validate("x/../../..", root=str(tmp_path))
    assert ok is False


def test_dot_segments_inside_are_collapsed() -> None:
    ok, value = targetdir.validate("a/./b", root="C:/tmp/root")
    assert ok is True
    assert value == os.path.join("a", "b")


# ---------------------------------------------------------------- Bridge 接入


def _fake_bridge(tmp_path):
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    b = bridge.Bridge(
        root=str(tmp_path), depth=1, store_path=str(tmp_path / "pref.json")
    )
    b.plan()
    return b


def test_set_target_dir_updates_one_row(tmp_path) -> None:
    b = _fake_bridge(tmp_path)
    target = next(r for r in b.plan()["rows"] if r["name"] == "a.txt")

    res = b.set_target_dir(target["path"], "2026/专案组")
    assert res["ok"] is True
    assert res["updated"] == 1

    row = b.plan_for(target["path"])
    assert row is not None
    assert row["target_dir"].replace(os.sep, "/") == "2026/专案组"


def test_set_target_dir_bulk_updates_many(tmp_path) -> None:
    b = _fake_bridge(tmp_path)
    paths = [r["path"] for r in b.plan()["rows"][:2]]
    res = b.set_target_dir_bulk(paths, "临时脚本")
    assert res["ok"] is True
    assert res["updated"] == 2
    for path in paths:
        row = b.plan_for(path)
        assert row is not None
        assert row["target_dir"].replace(os.sep, "/") == "临时脚本"


def test_illegal_target_leaves_plan_untouched(tmp_path) -> None:
    b = _fake_bridge(tmp_path)
    target = next(r for r in b.plan()["rows"] if r["name"] == "a.txt")
    before = b.plan_for(target["path"])["target_dir"]

    res = b.set_target_dir(target["path"], "../../Windows")
    assert res["ok"] is False
    assert res["updated"] == 0
    assert b.plan_for(target["path"])["target_dir"] == before


def test_set_target_dir_without_plan_reports_error(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    b = bridge.Bridge(
        root=str(tmp_path), depth=1, store_path=str(tmp_path / "pref.json")
    )
    res = b.set_target_dir(str(tmp_path / "a.txt"), "新目录")
    assert res["ok"] is False
    assert "计划" in res["error"]
