"""journal.py 的行为测试：追加式 JSONL 操作日志（崩溃可恢复的核心）。"""

from __future__ import annotations

import json
import os

import pytest

from desktop_organizer import journal
from desktop_organizer.model import GuardError


@pytest.fixture(autouse=True)
def _isolated_journal_dir(tmp_path, monkeypatch):
    """日志目录重定向到沙箱临时目录，绝不污染项目真实 logs/。"""
    target = tmp_path / "journal-logs"
    monkeypatch.setenv("DESKTOP_ORGANIZER_JOURNAL_DIR", str(target))
    return target


def test_new_journal_creates_jsonl_file_and_lists_it(_isolated_journal_dir):
    journal_id = journal.new_journal(str(_isolated_journal_dir.parent))

    assert journal_id
    assert (_isolated_journal_dir / f"{journal_id}.jsonl").is_file()
    assert journal_id in journal.list_journals()


def test_write_ahead_start_then_done_records_both_with_full_fields(_isolated_journal_dir):
    journal_id = journal.new_journal(str(_isolated_journal_dir.parent))

    journal.log(journal_id, 1, "move", r"D:\a\b.txt", r"D:\a\文档\b.txt", "start")
    journal.log(journal_id, 1, "move", r"D:\a\b.txt", r"D:\a\文档\b.txt", "done")

    records = journal.load(journal_id)
    assert [r["status"] for r in records] == ["start", "done"]
    assert [r["seq"] for r in records] == [1, 1]
    first = records[0]
    assert first["journal_id"] == journal_id
    assert first["op"] == "move"
    assert first["src"] == r"D:\a\b.txt"
    assert first["dst"] == r"D:\a\文档\b.txt"
    assert isinstance(first["ts"], str) and first["ts"]


def test_failed_record_carries_error_message(_isolated_journal_dir):
    journal_id = journal.new_journal(str(_isolated_journal_dir.parent))

    journal.log(journal_id, 7, "move", r"D:\a\c.txt", r"D:\a\x\c.txt", "failed", "文件被占用")

    record = journal.load(journal_id)[-1]
    assert record["status"] == "failed"
    assert record["error"] == "文件被占用"


def test_load_unknown_journal_returns_empty_list(_isolated_journal_dir):
    assert journal.load("no-such-journal") == []


def test_load_skips_corrupted_lines_instead_of_raising(_isolated_journal_dir):
    journal_id = journal.new_journal(str(_isolated_journal_dir.parent))
    journal.log(journal_id, 1, "mkdir", "", r"D:\a\x", "done")
    with open(_isolated_journal_dir / f"{journal_id}.jsonl", "a", encoding="utf-8") as fh:
        fh.write("{ this is not json\n")
    journal.log(journal_id, 2, "move", r"D:\a\d.txt", r"D:\a\x\d.txt", "done")

    records = journal.load(journal_id)
    assert [r["seq"] for r in records] == [1, 2]


def test_record_is_flushed_and_fsynced_before_log_returns(_isolated_journal_dir):
    journal_id = journal.new_journal(str(_isolated_journal_dir.parent))
    journal.log(journal_id, 1, "move", r"D:\a\e.txt", r"D:\a\x\e.txt", "start")

    # 另开一个句柄独立读取：不依赖进程内缓冲，模拟崩溃后另一进程读日志。
    path = _isolated_journal_dir / f"{journal_id}.jsonl"
    with open(path, "rb") as fh:
        raw = fh.read()
    line = json.loads(raw.decode("utf-8").strip())
    assert line["src"] == r"D:\a\e.txt"


def test_list_journals_is_sorted_and_ignores_foreign_files(_isolated_journal_dir):
    _isolated_journal_dir.mkdir(parents=True, exist_ok=True)
    # 直接造三个已知 id 的文件，排除随机 id 干扰排序断言
    for name in ("bbb", "aaa", "ccc"):
        (_isolated_journal_dir / f"{name}.jsonl").write_text("", encoding="utf-8")
    (_isolated_journal_dir / "notes.txt").write_text("x", encoding="utf-8")

    listed = journal.list_journals()
    assert listed[:3] == ["aaa", "bbb", "ccc"]
    assert "notes" not in listed


def test_journal_id_with_path_traversal_is_rejected(_isolated_journal_dir):
    for bad in ("../evil", r"..\evil", "a/b", ""):
        with pytest.raises(ValueError):
            journal.log(bad, 1, "move", "a", "b", "start")


def test_journal_dir_under_system_path_is_refused_by_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_ORGANIZER_JOURNAL_DIR", r"C:\Windows\Temp\dj-journal")
    with pytest.raises(GuardError):
        journal.new_journal(str(tmp_path))
