"""追加式操作日志（write-ahead journal，崩溃可恢复的核心）。

设计要点：
- 一条操作写两行：执行前 ``status="start"``，成功后 ``status="done"``。
  崩溃后若某条 ``start`` 没有配对的 ``done``，说明该操作"可能已执行"，
  回滚逻辑据此倒序复原，绝不凭空假设文件还在原处。
- 每条记录写入后立即 flush + os.fsync，断电也不丢已宣告的意图。
- 目录固定为 ``<项目根>/logs/journal``（logs/ 已 gitignore）；
  测试可用环境变量 ``DESKTOP_ORGANIZER_JOURNAL_DIR`` 整体重定向。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from . import guard
from .constants import PROJECT_ROOT

_JOURNAL_DIR_ENV = "DESKTOP_ORGANIZER_JOURNAL_DIR"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_VALID_OPS = frozenset({"move", "mkdir"})
_VALID_STATUS = frozenset({"start", "done", "failed"})


def journal_dir() -> Path:
    override = os.environ.get(_JOURNAL_DIR_ENV)
    if override:
        return Path(override)
    return PROJECT_ROOT / "logs" / "journal"


def _path_for(journal_id: str) -> Path:
    if not isinstance(journal_id, str) or not _ID_RE.match(journal_id):
        # 拒绝 ../ 与绝对路径，journal_id 只允许白名单字符，防止越权写盘。
        raise ValueError(f"非法的 journal_id: {journal_id!r}")
    return journal_dir() / f"{journal_id}.jsonl"


def _ensure_dir() -> Path:
    directory = journal_dir()
    guard.assert_safe(directory)  # 写盘前必须过守卫
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def new_journal(root: str) -> str:
    """新建一份日志并返回 journal_id。

    ``root`` 为本次操作的源根目录，仅用于调用方语义对齐：
    日志统一落在 logs/journal，不按 root 分目录，避免源根不可写时日志也写不了。
    """
    del root  # 有意不参与路径计算，见上
    _ensure_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    journal_id = f"j-{stamp}-{uuid.uuid4().hex[:8]}"
    _path_for(journal_id).touch()
    return journal_id


def log(
    journal_id: str,
    seq: int,
    op: str,
    src: str,
    dst: str,
    status: str,
    error: str = "",
) -> None:
    """追加一条记录并落盘（flush + fsync）。"""
    path = _path_for(journal_id)
    if op not in _VALID_OPS:
        raise ValueError(f"未知操作类型: {op!r}")
    if status not in _VALID_STATUS:
        raise ValueError(f"未知状态: {status!r}")
    _ensure_dir()

    record = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "journal_id": journal_id,
        "seq": int(seq),
        "op": op,
        "src": src,
        "dst": dst,
        "status": status,
        "error": error,
    }
    line = json.dumps(record, ensure_ascii=False)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def load(journal_id: str) -> list[dict]:
    """读回全部记录，按写入顺序；损坏行跳过而非抛错（崩溃常留半行）。"""
    path = _path_for(journal_id)
    if not path.is_file():
        return []
    records: list[dict] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(item, dict):
                records.append(item)
    return records


def list_journals() -> list[str]:
    """列出全部 journal_id，按名字（即时间前缀）升序。"""
    directory = journal_dir()
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.jsonl") if p.is_file())
