"""pywebview 桥接层：前端（HTML/JS）唯一能触达核心的入口。

设计纪律：
- 只暴露必要方法，返回的全部是 **JSON 安全的 dict**（pywebview 用 JSON 传输）。
- `apply()` 默认 `dry_run=True`：JS 侧必须显式传 False 才真正移动文件。
- 任何写盘动作前，核心模块（executor/guard）已有硬拦截；本层不重复造闸门，也不放宽。
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any

from . import executor, journal, planner, scanner
from .model import FileItem, Plan, PlanAction, Proposal
from .store import PreferenceStore


def _row(item: FileItem, proposal: Proposal | None, action_id: str) -> dict[str, Any]:
    """一行 = 文件事实 + 建议 + 可执行动作 id。前端表格直接吃这个结构。"""
    return {
        "path": item.path,
        "name": item.name,
        "ext": item.ext,
        "size": item.size,
        "mtime": item.mtime,
        "is_dir": item.is_dir,
        "readonly": item.readonly,
        "cloud_placeholder": item.cloud_placeholder,
        "skipped_reason": item.skipped_reason,
        "category": proposal.category if proposal else "其他",
        "importance": proposal.importance if proposal else "low",
        "confidence": round(proposal.confidence, 2) if proposal else 0.0,
        "target_dir": proposal.target_dir if proposal else "",
        "reasons": list(proposal.reasons) if proposal else [],
        "action_id": action_id,
    }


class Bridge:
    def __init__(
        self,
        root: str | None = None,
        depth: int = 1,
        store_path: str | Path | None = None,
    ) -> None:
        self.root = str(root) if root else os.path.expanduser("~\\Desktop")
        self.depth = max(0, int(depth))
        self.store = PreferenceStore(store_path)
        self._items: list[FileItem] = []
        self._plan: Plan | None = None
        self._last_journal = ""

    # ---------- 只读 ----------

    def scan(self) -> dict[str, Any]:
        """只读扫描。路径守卫在 scanner 内部（assert_readable）先跑。"""
        items = scanner.scan(self.root, max_depth=self.depth)
        self._items = items
        self._plan = None
        return {
            "root": self.root,
            "total": len(items),
            "rows": [_row(i, None, "") for i in items],
        }

    def plan(self) -> dict[str, Any]:
        """生成计划：扫描 + 分类建议 + 目标路径。不写盘。"""
        if not self._items:
            self.scan()
        plan = planner.build_plan(self._items, self.root, self.store)
        self._plan = plan
        return self._plan_payload(plan)

    def plan_for(self, path: str) -> dict[str, Any] | None:
        """单文件重新出建议（用户改判后刷新界面用）。"""
        from .classify import classify

        item = self._find(path)
        if item is None:
            return None
        proposal = classify(item, self.store)
        return _row(item, proposal, "")

    # ---------- 写盘（默认 dry-run）----------

    def apply(
        self,
        action_ids: list[str] | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """执行计划。action_ids 为空表示全部；dry_run=True 只算不动。"""
        plan = self._plan or planner.build_plan(self._items or self.scan()["rows"], self.root, self.store)
        if action_ids:
            wanted = set(action_ids)
            plan = dataclasses.replace(
                plan,
                actions=[a for a in plan.actions if a.action_id in wanted],
            )
        result = executor.execute(plan, dry_run=dry_run)
        payload = result.to_dict()
        payload["dry_run"] = bool(dry_run)
        if result.journal_id:
            self._last_journal = result.journal_id
        return payload

    def rollback(self, journal_id: str = "") -> dict[str, Any]:
        """回滚。不传则回滚最近一次成功执行。"""
        target = journal_id or self._last_journal
        if not target:
            ids = journal.list_journals()
            target = ids[-1] if ids else ""
        if not target:
            return {"ok": False, "rolled_back": 0, "errors": ["没有可回滚的执行记录"]}
        return executor.rollback(target).to_dict()

    def journals(self) -> dict[str, Any]:
        ids = journal.list_journals()
        return {"total": len(ids), "ids": ids, "last": self._last_journal}

    # ---------- 改判学习 ----------

    def remember(
        self,
        path: str,
        category: str,
        importance: str = "medium",
        target_dir: str = "",
    ) -> dict[str, Any]:
        """记住用户这一次的选择，下次同类文件直接沿用。"""
        item = self._find(path)
        if item is None:
            return {"saved": False, "error": "文件不在上次扫描结果中，请先刷新"}
        from .constants import IMPORTANCE_DIRS

        rel = target_dir or f"{category}/{IMPORTANCE_DIRS.get(importance, IMPORTANCE_DIRS['medium'])}"
        choice = Proposal(
            path=item.path,
            target_dir=rel,
            category=category,
            importance=importance,
            confidence=1.0,
            reasons=["用户改判"],
        )
        self.store.remember(item, None, choice)
        self._plan = None  # 偏好变了，旧计划作废
        return {"saved": True, "category": category, "importance": importance, "target_dir": rel}

    # ---------- 内部 ----------

    def _find(self, path: str) -> FileItem | None:
        want = os.path.normcase(os.path.abspath(path))
        for item in self._items:
            if os.path.normcase(os.path.abspath(item.path)) == want:
                return item
        # 允许对尚未扫描的文件改判
        if os.path.isfile(path):
            found = scanner.scan(os.path.dirname(path) or ".", max_depth=1)
            for item in found:
                if os.path.normcase(os.path.abspath(item.path)) == want:
                    self._items.append(item)
                    return item
        return None

    def _plan_payload(self, plan: Plan) -> dict[str, Any]:
        by_src = {os.path.normcase(a.src): a for a in plan.actions}
        rows: list[dict[str, Any]] = []
        for item in self._items:
            action: PlanAction | None = by_src.get(os.path.normcase(item.path))
            if item.skipped and action is None:
                rows.append(_row(item, None, ""))
                continue
            proposal = self._proposal_of(item, action)
            rows.append(_row(item, proposal, action.action_id if action else ""))
        return {
            "plan_id": plan.plan_id,
            "root": plan.root,
            "created_at": plan.created_at,
            "warnings": list(plan.warnings),
            "total": len(plan.actions),
            "rows": rows,
        }

    def _proposal_of(self, item: FileItem, action: PlanAction | None) -> Proposal:
        from .classify import classify

        proposal = classify(item, self.store)
        if action is not None:
            # 目标目录以计划为准（低置信度会被降级到 其他/归档）
            rel = os.path.relpath(os.path.dirname(action.dst), self.root)
            proposal.target_dir = rel.replace(os.sep, "/")
        return proposal
