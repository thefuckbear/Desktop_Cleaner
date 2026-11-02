"""执行器：把 Plan 变成真实的文件移动，并提供可回滚的 WAL 记录。

安全约束（不可协商）：
- ``dry_run=True`` 是默认值，此时除了内存里的计数什么都不写，连目标目录都不建。
- 每条动作写盘前都要过 ``guard.assert_safe``；建目录逐级校验，不允许"只验最终文件"。
- 目标已存在时一律追加 ``(n)`` 后缀，**绝不覆盖**已有文件。
- 单条失败只记录不中断，保证一个坏文件不会毁掉整批。
- 先写 ``start`` 再动盘，成功后写 ``done``；崩溃后据"孤儿 start"判断哪些可能已执行。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import guard, journal
from .model import ExecResult, GuardError, Plan, PlanAction

_VALID_KINDS = frozenset({"move"})
_MAX_SUFFIX = 999


def _unique_dst(dst: Path) -> Path:
    """目标已存在时生成 ``name (1).ext``。dry-run 下也走同样逻辑，保证预览结果可信。"""
    if not dst.exists():
        return dst
    stem, suffix, parent = dst.stem, dst.suffix, dst.parent
    for n in range(1, _MAX_SUFFIX + 1):
        candidate = parent / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
    raise OSError(f"目标目录内同名文件过多，放弃: {dst}")


def _ensure_parents(dst_dir: Path, *, dry_run: bool) -> None:
    """逐级校验并（非 dry-run 时）创建缺失目录。"""
    chain: list[Path] = []
    node = dst_dir
    while not node.exists():
        chain.append(node)
        parent = node.parent
        if parent == node:  # 到达盘符根
            break
        node = parent
    for item in reversed(chain):
        guard.assert_safe(item)   # 每一级都过守卫，防止中间层被重定向到禁区
        if not dry_run:
            item.mkdir(exist_ok=True)


def _apply_one(action: PlanAction, *, dry_run: bool, journal_id: str, seq: int) -> str:
    """执行单条动作。返回空字符串表示成功，否则返回错误描述。"""
    if action.kind not in _VALID_KINDS:
        return f"[{action.action_id}] 不支持的动作类型: {action.kind!r}（只允许 move）"

    src = Path(action.src)
    dst = Path(action.dst)

    try:
        guard.assert_safe(src)
        guard.assert_safe(dst)
    except GuardError as exc:
        return f"[{action.action_id}] {exc}"

    if not src.is_file():
        return f"[{action.action_id}] 源文件不存在或不是普通文件: {src}"

    try:
        _ensure_parents(dst.parent, dry_run=dry_run)
    except GuardError as exc:
        return f"[{action.action_id}] {exc}"
    except OSError as exc:
        return f"[{action.action_id}] 创建目标目录失败: {exc}"

    final_dst = dst
    try:
        if not dry_run:
            final_dst = _unique_dst(dst)
            guard.assert_safe(final_dst)
    except GuardError as exc:
        return f"[{action.action_id}] {exc}"
    except OSError as exc:
        return f"[{action.action_id}] {exc}"

    if dry_run:
        return ""

    try:
        journal.log(journal_id, seq, "move", str(src), str(final_dst), "start")
        shutil.move(str(src), str(final_dst))
        journal.log(journal_id, seq, "move", str(src), str(final_dst), "done")
    except Exception as exc:  # noqa: BLE001 - 单条失败不能中断整批
        try:
            journal.log(journal_id, seq, "move", str(src), str(final_dst), "failed", error=str(exc))
        except Exception:  # 日志写不进去也不能连带炸掉
            pass
        return f"[{action.action_id}] 移动失败: {exc}"
    return ""


def execute(plan: Plan, dry_run: bool = True) -> ExecResult:
    """执行计划。``dry_run`` 默认 True，只有显式传 False 才会真正动盘。"""
    result = ExecResult()
    if not plan.actions:
        result.ok = True
        return result

    journal_id = "" if dry_run else journal.new_journal(plan.root)
    result.journal_id = journal_id

    for seq, action in enumerate(plan.actions, start=1):
        error = _apply_one(action, dry_run=dry_run, journal_id=journal_id, seq=seq)
        if error:
            result.failed += 1
            result.errors.append(error)
        else:
            result.applied += 1

    result.ok = result.failed == 0
    return result


def _rollback_targets(records: list[dict]) -> list[dict]:
    """挑出需要复原的记录：已完成的 move，以及"有 start 没 done"的疑似已执行。"""
    done = [r for r in records if r.get("op") == "move" and r.get("status") == "done"]
    done_seqs = {r.get("seq") for r in done}
    started = [
        r for r in records
        if r.get("op") == "move" and r.get("status") == "start" and r.get("seq") not in done_seqs
    ]
    return done + started


def rollback(journal_id: str) -> ExecResult:
    """按日志倒序把文件移回原处。源位置已被占用时跳过，绝不覆盖。"""
    result = ExecResult()
    records = journal.load(journal_id)
    targets = _rollback_targets(records)
    if not targets:
        result.ok = True
        return result

    new_id_ = journal.new_journal("")
    result.journal_id = new_id_

    for seq, record in enumerate(reversed(targets), start=1):
        src = str(record.get("src", ""))
        dst = str(record.get("dst", ""))
        if not src or not dst:
            result.failed += 1
            result.errors.append(f"[seq={record.get('seq')}] 日志记录缺少 src/dst")
            continue
        try:
            guard.assert_safe(Path(src))
            guard.assert_safe(Path(dst))
        except GuardError as exc:
            result.failed += 1
            result.errors.append(f"[seq={record.get('seq')}] {exc}")
            continue

        src_path, dst_path = Path(src), Path(dst)
        if not dst_path.is_file():
            result.skipped += 1
            result.errors.append(f"[seq={record.get('seq')}] 目标已不存在，跳过: {dst}")
            continue
        if src_path.exists():
            result.skipped += 1
            result.errors.append(f"[seq={record.get('seq')}] 源位置已被占用，跳过以免覆盖: {src}")
            continue

        try:
            _ensure_parents(src_path.parent, dry_run=False)
            journal.log(new_id_, seq, "rollback", dst, src, "start")
            shutil.move(dst, src)
            journal.log(new_id_, seq, "rollback", dst, src, "done")
            result.rolled_back += 1
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            result.errors.append(f"[seq={record.get('seq')}] 回滚失败: {exc}")

    result.ok = result.failed == 0
    return result
