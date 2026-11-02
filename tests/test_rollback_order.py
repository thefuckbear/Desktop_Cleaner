"""回滚保序的加固测试：创建时间、shell 刷新通知。

桌面开「自动排列」时，图标位置是排序键（名称/大小/修改时间/创建时间）的纯函数。
文件被搬走再搬回，若排序键有任何一个变了，用户就会看到图标「没回原位」。
所以回滚必须把能还原的排序键全都还原，并让 Explorer 重新读取。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from desktop_organizer import executor, journal, shellrefresh
from desktop_organizer.model import Plan, PlanAction


@pytest.fixture(autouse=True)
def _isolated_journal_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_ORGANIZER_JOURNAL_DIR", str(tmp_path / "journal-logs"))


def _plan(root: Path, actions: list[PlanAction]) -> Plan:
    return Plan(plan_id="p-test", root=str(root), created_at="2026-11-03T00:00:00", actions=actions)


def _act(action_id: str, src: Path, dst: Path) -> PlanAction:
    return PlanAction(action_id=action_id, src=str(src), dst=str(dst))


def test_move_record_carries_birthtime_when_available(tmp_path):
    """创建时间也是桌面可选的排序键，必须一并记下来。"""
    src = tmp_path / "a.txt"
    src.write_text("hello", encoding="utf-8")
    st = src.stat()
    if not hasattr(st, "st_birthtime_ns"):
        pytest.skip("当前平台不提供 st_birthtime_ns")

    result = executor.execute(
        _plan(tmp_path, [_act("1", src, tmp_path / "文档" / "a.txt")]), dry_run=False
    )

    start = next(
        r for r in journal.load(result.journal_id)
        if r["op"] == "move" and r["status"] == "start"
    )
    assert start["birthtime_ns"] == st.st_birthtime_ns


def test_rollback_restores_birthtime(tmp_path):
    """跨卷复制会刷新创建时间；回滚后必须回到原值。

    同卷 move 本来就会保留创建时间，所以这里刻意把「移动后」的创建时间
    改成另一个值，模拟跨卷复制造成的刷新，再验证回滚能把它改回来。
    """
    src = tmp_path / "a.txt"
    src.write_text("hello", encoding="utf-8")
    st = src.stat()
    if not hasattr(st, "st_birthtime_ns"):
        pytest.skip("当前平台不提供 st_birthtime_ns")
    before = st.st_birthtime_ns

    dst = tmp_path / "文档" / "a.txt"
    done = executor.execute(_plan(tmp_path, [_act("1", src, dst)]), dry_run=False)
    assert done.applied == 1

    # 模拟跨卷复制把创建时间刷成"复制那一刻"
    refreshed = before + 10_000_000_000
    assert executor._set_birthtime_win(dst, refreshed), "写创建时间失败，无法继续验证"
    assert dst.stat().st_birthtime_ns == refreshed

    executor.rollback(done.journal_id)

    assert src.stat().st_birthtime_ns == before


def test_rollback_broadcasts_shell_refresh(tmp_path, monkeypatch):
    """回滚后必须让 Explorer 重新枚举，否则桌面可能停在缓存位置。"""
    calls: list[tuple[str, str]] = []

    def fake_notify_item(path):
        calls.append(("item", str(path)))
        return True

    def fake_notify_dir(path):
        calls.append(("dir", str(path)))
        return True

    monkeypatch.setattr(shellrefresh, "notify_item", fake_notify_item)
    monkeypatch.setattr(shellrefresh, "notify_dir", fake_notify_dir)
    monkeypatch.setattr(executor, "shellrefresh", shellrefresh, raising=False)

    src = tmp_path / "a.txt"
    src.write_text("hello", encoding="utf-8")
    done = executor.execute(
        _plan(tmp_path, [_act("1", src, tmp_path / "文档" / "a.txt")]), dry_run=False
    )
    executor.rollback(done.journal_id)

    kinds = [k for k, _ in calls]
    assert "dir" in kinds, "回滚后必须广播目录刷新"
    assert ("item", str(src)) in calls, "被还原的文件要单独通知一次"


def test_refresh_is_skipped_when_nothing_rolled_back(tmp_path, monkeypatch):
    """没还原任何文件时不该乱发通知（避免无意义唤醒 Explorer）。"""
    calls: list[str] = []
    monkeypatch.setattr(shellrefresh, "notify_dir", lambda p: calls.append(str(p)) or True)
    monkeypatch.setattr(executor, "shellrefresh", shellrefresh, raising=False)

    src = tmp_path / "a.txt"
    src.write_text("hello", encoding="utf-8")
    dst = tmp_path / "文档" / "a.txt"
    done = executor.execute(_plan(tmp_path, [_act("1", src, dst)]), dry_run=False)
    dst.unlink()  # 目标已被别处清掉，回滚没有可还原的东西
    executor.rollback(done.journal_id)

    assert calls == []


def test_shellrefresh_helpers_are_noop_on_bad_input():
    """坏路径/不存在路径不能让回滚抛异常。"""
    assert shellrefresh.notify_dir("") is False
    assert shellrefresh.notify_item("") is False
    assert shellrefresh.notify_dir(Path("Z:/definitely-not-here-xyz")) is False
    assert shellrefresh.notify_item(Path("Z:/definitely-not-here-xyz")) is False
