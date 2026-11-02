"""executor.execute / rollback 的行为测试。

全部样本在 sandbox 自建；dry-run 与真实执行都用目录快照对比"有没有动盘"。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from desktop_organizer import executor, journal
from desktop_organizer.model import Plan, PlanAction


@pytest.fixture(autouse=True)
def _isolated_journal_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_ORGANIZER_JOURNAL_DIR", str(tmp_path / "journal-logs"))


def _plan(root: Path, actions: list[PlanAction]) -> Plan:
    return Plan(plan_id="p-test", root=str(root), created_at="2026-11-02T00:00:00", actions=actions)


def _act(action_id: str, src: Path, dst: Path) -> PlanAction:
    return PlanAction(action_id=action_id, src=str(src), dst=str(dst))


def _snapshot(root: Path) -> dict[str, tuple[int, float]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


def test_dry_run_reports_what_would_happen_without_touching_disk(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("hello", encoding="utf-8")
    dst_dir = tmp_path / "文档"
    before = _snapshot(tmp_path)

    result = executor.execute(_plan(tmp_path, [_act("1", src, dst_dir / "a.txt")]), dry_run=True)

    assert result.applied == 1
    assert result.failed == 0
    assert result.ok is True
    assert result.journal_id == ""
    assert _snapshot(tmp_path) == before      # 一个字节都没动
    assert not dst_dir.exists()               # 连目录都没建


def test_real_run_moves_file_and_journals_start_before_done(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("hello", encoding="utf-8")
    dst = tmp_path / "文档" / "a.txt"

    result = executor.execute(_plan(tmp_path, [_act("1", src, dst)]), dry_run=False)

    assert result.applied == 1 and result.ok is True
    assert result.journal_id
    assert not src.exists() and dst.read_text(encoding="utf-8") == "hello"

    records = [r for r in journal.load(result.journal_id) if r["op"] == "move"]
    assert [r["status"] for r in records] == ["start", "done"]
    assert records[0]["src"] == str(src)
    assert records[0]["dst"] == str(dst)


def test_dry_run_never_creates_a_journal_file(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")

    before = journal.list_journals()
    executor.execute(_plan(tmp_path, [_act("1", src, tmp_path / "d" / "a.txt")]), dry_run=True)
    assert journal.list_journals() == before


def test_name_conflict_appends_numeric_suffix_and_never_overwrites(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "文档" / "a.txt"
    dst.parent.mkdir()
    dst.write_text("old", encoding="utf-8")

    result = executor.execute(_plan(tmp_path, [_act("1", src, dst)]), dry_run=False)

    assert result.applied == 1
    assert dst.read_text(encoding="utf-8") == "old"           # 原文件未被覆盖
    moved = dst.with_name("a (1).txt")
    assert moved.read_text(encoding="utf-8") == "new"
    rec = [r for r in journal.load(result.journal_id) if r["op"] == "move"][0]
    assert rec["dst"] == str(moved)                           # 日志记实际目标


def test_duplicate_source_in_plan_is_skipped_after_first_move(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("only", encoding="utf-8")
    plan = _plan(tmp_path, [
        _act("1", src, tmp_path / "o1" / "a.txt"),
        _act("2", src, tmp_path / "o2" / "a.txt"),
    ])

    result = executor.execute(plan, dry_run=False)

    assert result.applied == 1
    assert result.failed == 1                       # 第二个动作找不到源文件
    assert (tmp_path / "o1" / "a.txt").is_file()
    assert not (tmp_path / "o2" / "a.txt").exists()


def test_two_actions_targeting_same_path_do_not_collide(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("A", encoding="utf-8")
    b.write_text("B", encoding="utf-8")
    dst = tmp_path / "out" / "same.txt"

    result = executor.execute(
        _plan(tmp_path, [_act("1", a, dst), _act("2", b, dst)]), dry_run=False
    )

    assert result.applied == 2
    assert (tmp_path / "out" / "same.txt").read_text(encoding="utf-8") == "A"
    assert (tmp_path / "out" / "same (1).txt").read_text(encoding="utf-8") == "B"


def test_guard_rejection_fails_only_that_action_and_continues(tmp_path):
    good = tmp_path / "good.txt"
    good.write_text("x", encoding="utf-8")

    result = executor.execute(
        _plan(tmp_path, [
            PlanAction(action_id="bad", src=str(good), dst=r"C:\Windows\evil.txt"),
            _act("good", good, tmp_path / "out" / "good.txt"),
        ]),
        dry_run=False,
    )

    assert result.failed == 1
    assert result.applied == 1
    assert result.ok is False
    assert any("bad" in e for e in result.errors)
    assert (tmp_path / "out" / "good.txt").is_file()


def test_missing_source_is_recorded_as_failed(tmp_path):
    result = executor.execute(
        _plan(tmp_path, [_act("1", tmp_path / "ghost.txt", tmp_path / "o" / "ghost.txt")]),
        dry_run=False,
    )
    assert result.failed == 1
    assert result.applied == 0


def test_unknown_action_kind_is_rejected_without_touching_disk(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    act = PlanAction(action_id="1", src=str(src), dst=str(tmp_path / "o" / "a.txt"), kind="delete")

    result = executor.execute(_plan(tmp_path, [act]), dry_run=False)

    assert result.failed == 1
    assert result.skipped == 0 and result.applied == 0
    assert src.exists()


def test_rollback_restores_files_in_reverse_order(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("A", encoding="utf-8")
    b.write_text("B", encoding="utf-8")
    plan = _plan(tmp_path, [
        _act("1", a, tmp_path / "out" / "a.txt"),
        _act("2", b, tmp_path / "out" / "b.txt"),
    ])

    done = executor.execute(plan, dry_run=False)
    assert done.applied == 2

    result = executor.rollback(done.journal_id)

    assert result.rolled_back == 2
    assert a.read_text(encoding="utf-8") == "A"
    assert b.read_text(encoding="utf-8") == "B"
    assert not (tmp_path / "out" / "a.txt").exists()
    assert result.journal_id != done.journal_id


def test_rollback_skips_when_source_path_already_occupied(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    dst = tmp_path / "out" / "a.txt"
    done = executor.execute(_plan(tmp_path, [_act("1", src, dst)]), dry_run=False)
    src.write_text("someone else", encoding="utf-8")  # 回滚前源位置被占用

    result = executor.rollback(done.journal_id)

    assert result.rolled_back == 0
    assert result.skipped == 1
    assert src.read_text(encoding="utf-8") == "someone else"   # 绝不覆盖
    assert dst.exists()


def test_rollback_journal_is_written_with_rollback_op(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    done = executor.execute(_plan(tmp_path, [_act("1", src, tmp_path / "o" / "a.txt")]), dry_run=False)

    result = executor.rollback(done.journal_id)

    ops = {r["op"] for r in journal.load(result.journal_id)}
    assert "rollback" in ops
    assert any(r["status"] == "done" for r in journal.load(result.journal_id))


def test_rollback_of_unknown_journal_is_a_noop(tmp_path):
    result = executor.rollback("no-such-journal")
    assert result.rolled_back == 0
    assert result.ok is True


def test_each_created_directory_level_is_guarded(tmp_path, monkeypatch):
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    checked: list[str] = []
    real_safe = executor.guard.assert_safe

    def spy(path, **kw):
        checked.append(str(path))
        return real_safe(path, **kw)

    monkeypatch.setattr(executor.guard, "assert_safe", spy)

    dst = tmp_path / "x" / "y" / "z" / "a.txt"
    executor.execute(_plan(tmp_path, [_act("1", src, dst)]), dry_run=False)

    checked_norm = [p.replace("/", "\\").lower() for p in checked]
    assert any(p.endswith("\\x") for p in checked_norm)
    assert any(p.endswith("\\x\\y") for p in checked_norm)
    assert any(p.endswith("\\z") for p in checked_norm)


def test_directory_creation_is_also_planned_in_dry_run(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")

    result = executor.execute(
        _plan(tmp_path, [_act("1", src, tmp_path / "deep" / "nested" / "a.txt")]), dry_run=True
    )

    assert result.applied == 1
    assert not (tmp_path / "deep").exists()


def test_all_rejected_leaves_no_empty_journal_file(tmp_path):
    """全部被守卫拒绝时不得留下 0 字节日志文件（真实桌面场景就踩过这个坑）。"""
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    before = journal.list_journals()

    result = executor.execute(
        _plan(tmp_path, [
            PlanAction(action_id="1", src=str(src), dst=r"C:\Windows\x1.txt"),
            PlanAction(action_id="2", src=str(src), dst=r"C:\Windows\x2.txt"),
        ]),
        dry_run=False,
    )

    assert result.applied == 0 and result.failed == 2
    assert result.journal_id == ""
    assert journal.list_journals() == before


def test_all_rejected_gives_actionable_hint(tmp_path):
    """全被拒时除了逐条错误，还要有一条能看懂的指引。"""
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")

    result = executor.execute(
        _plan(tmp_path, [PlanAction(action_id="1", src=str(src), dst=r"C:\Windows\x1.txt")]),
        dry_run=False,
    )

    assert any("白名单" in e for e in result.errors)


def test_rollback_removes_directories_created_by_the_move(tmp_path):
    """回滚后不该留下执行时建的空目录。"""
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    dst = tmp_path / "out" / "sub" / "a.txt"

    done = executor.execute(_plan(tmp_path, [_act("1", src, dst)]), dry_run=False)
    assert dst.is_file()

    result = executor.rollback(done.journal_id)

    assert result.rolled_back == 1
    assert src.is_file()
    assert not (tmp_path / "out").exists()


def test_rollback_keeps_directory_that_still_has_files(tmp_path):
    """目录里还有别的文件时不能删。"""
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("A", encoding="utf-8")
    b.write_text("B", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("keep", encoding="utf-8")

    done = executor.execute(_plan(tmp_path, [_act("1", a, out / "a.txt")]), dry_run=False)
    executor.rollback(done.journal_id)

    assert (out / "keep.txt").is_file()
