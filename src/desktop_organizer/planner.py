"""计划生成：把扫描结果 + 分类建议翻译成可执行的移动动作清单。

纯计算，绝不读写文件系统；真正的移动由 executor 在 guard 与 dry-run 约束下执行。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING

from .constants import CONFIDENCE_MEDIUM, IMPORTANCE_DIRS
from .model import FileItem, Plan, PlanAction, Proposal, new_id

if TYPE_CHECKING:  # 避免运行期循环导入
    from .store import PreferenceStore

LOW_CONFIDENCE_CATEGORY = "其他"
LOW_CONFIDENCE_IMPORTANCE = "low"
DEFAULT_KIND = "move"


def _normalize(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _same_dir(left: str, right: str) -> bool:
    return _normalize(left) == _normalize(right)


def _reason(proposal: Proposal, downgraded: bool) -> str:
    parts = list(proposal.reasons) or ["无明确理由"]
    if proposal.rule_id:
        parts.append(f"规则 {proposal.rule_id}")
    if downgraded:
        parts.append(f"置信度 {proposal.confidence:.2f} 低于阈值，暂不自动归类")
    return "；".join(parts)


def build_plan(items: list[FileItem], root: str, store: "PreferenceStore | None" = None) -> Plan:
    """生成移动计划。已在目标目录的文件不产生动作。"""
    from .classify import classify  # 局部导入：planner <-> classify 不构成循环

    plan = Plan(
        plan_id=new_id("plan"),
        root=root,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    low_confidence = 0

    for item in items:
        if item.skipped:
            continue

        proposal = classify(item, store)
        category, importance, downgraded = proposal.category, proposal.importance, False

        if proposal.confidence < CONFIDENCE_MEDIUM:
            category, importance, downgraded = LOW_CONFIDENCE_CATEGORY, LOW_CONFIDENCE_IMPORTANCE, True
            low_confidence += 1

        importance_dir = IMPORTANCE_DIRS.get(importance, IMPORTANCE_DIRS["low"])
        target_dir = os.path.join(root, category, importance_dir)

        src_dir = os.path.dirname(os.path.abspath(item.path))
        if _same_dir(src_dir, target_dir):
            continue

        plan.actions.append(
            PlanAction(
                action_id=new_id("act"),
                src=item.path,
                dst=os.path.join(target_dir, item.name),
                kind=DEFAULT_KIND,
                reason=_reason(proposal, downgraded),
            )
        )

    if low_confidence:
        plan.warnings.append(f"{low_confidence} 个文件置信度低，建议人工确认")
    return plan
