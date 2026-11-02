"""规则引擎：把"什么文件放到哪里"变成可序列化、可解释的规则。

设计取舍（详见 docs/decisions-ai.md）：
- 规则只做"条件 -> 类别/重要度"，不做自由文本推理，保证离线、可复现、可审计。
- matcher 是若干简单条件的交集（AND），刻意不支持嵌套/脚本，避免规则本身成为攻击面。
- 优先级降序取第一条命中；用户规则同 id 覆盖内置规则，新 id 追加。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .model import FileItem

MATCHER_KEYS = ("ext_in", "name_contains", "size_gt", "age_days_lt")


@dataclass(frozen=True)
class Rule:
    """一条放置规则。matcher 内所有条件必须同时成立（AND）。"""

    id: str
    matcher: dict[str, Any]
    target_category: str
    importance: str = "medium"
    confidence: float = 0.80
    priority: int = 0
    description: str = ""
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def matches(self, item: FileItem, now: float | None = None) -> bool:
        matcher = self.matcher or {}
        if not matcher:
            return False
        if not set(matcher) <= set(MATCHER_KEYS):
            return False

        if "ext_in" in matcher:
            exts = {str(e).lower() for e in matcher["ext_in"]}
            if (item.ext or "").lower() not in exts:
                return False

        if "name_contains" in matcher:
            name = item.name.lower()
            needles = [str(n).lower() for n in matcher["name_contains"]]
            if not any(n and n in name for n in needles):
                return False

        if "size_gt" in matcher:
            if item.size <= int(matcher["size_gt"]):
                return False

        if "age_days_lt" in matcher:
            age = age_days(item, now)
            if age is None or age >= float(matcher["age_days_lt"]):
                return False

        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "matcher": dict(self.matcher),
            "target_category": self.target_category,
            "importance": self.importance,
            "confidence": self.confidence,
            "priority": self.priority,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rule":
        matcher = data.get("matcher") or {}
        if set(matcher) - set(MATCHER_KEYS):
            raise ValueError(f"规则 {data.get('id')} 含不支持的匹配条件: {sorted(set(matcher) - set(MATCHER_KEYS))}")
        return cls(
            id=str(data["id"]),
            matcher={k: (list(v) if isinstance(v, (list, tuple)) else v) for k, v in matcher.items()},
            target_category=str(data.get("target_category", "其他")),
            importance=str(data.get("importance", "medium")),
            confidence=float(data.get("confidence", 0.80)),
            priority=int(data.get("priority", 0)),
            description=str(data.get("description", "")),
        )


def age_days(item: FileItem, now: float | None = None) -> float | None:
    """文件年龄（天）。mtime 未知（<=0）返回 None，绝不猜。"""
    if not item.mtime or item.mtime <= 0:
        return None
    return max(0.0, ((now if now is not None else time.time()) - item.mtime) / 86400.0)


# 内置规则：只覆盖"通用扩展名分类会失手"的场景，避免与 classify 的扩展名映射重复。
DEFAULT_RULES: list[Rule] = [
    Rule(
        id="rule-screenshot",
        matcher={"name_contains": ["截图", "screenshot", "screen shot", "屏幕快照"]},
        target_category="图片",
        importance="high",
        confidence=0.85,
        priority=90,
        description="截图类文件名，视为近期需要的高价值图片",
    ),
    Rule(
        id="rule-installer",
        matcher={"ext_in": [".exe", ".msi", ".msix", ".appx"], "name_contains": ["setup", "install", "安装"]},
        target_category="安装包",
        importance="low",
        confidence=0.85,
        priority=80,
        description="安装程序的命名特征，装完即可归档",
    ),
    Rule(
        id="rule-fresh-archive",
        matcher={"ext_in": [".zip", ".7z", ".rar"], "age_days_lt": 3},
        target_category="压缩包",
        importance="medium",
        confidence=0.80,
        priority=60,
        description="三天内仍在动的压缩包，先放常用区",
    ),
]


def rules_to_dicts(rules: list[Rule]) -> list[dict[str, Any]]:
    return [r.to_dict() for r in rules]


def rules_from_dicts(rows: list[dict[str, Any]]) -> list[Rule]:
    return [Rule.from_dict(r) for r in rows]


def merge_rules(base: list[Rule], overrides: list[Rule]) -> list[Rule]:
    """同 id 覆盖（保持原位置），新 id 追加到末尾。"""
    merged: dict[str, Rule] = {r.id: r for r in base}
    for rule in overrides:
        merged[rule.id] = rule
    return list(merged.values())


def load_rules(store: object | None = None) -> list[Rule]:
    """内置规则 + 用户规则（含偏好沉淀出的规则）。store 只需提供 export_rules()。"""
    if store is None:
        return list(DEFAULT_RULES)
    try:
        rows = store.export_rules()
    except Exception:  # 偏好库坏掉不能拖垮分类
        return list(DEFAULT_RULES)
    user_rules: list[Rule] = []
    for row in rows:
        try:
            user_rules.append(Rule.from_dict(row))
        except (KeyError, TypeError, ValueError):
            continue
    return merge_rules(DEFAULT_RULES, user_rules)


def match(item: FileItem, rules: list[Rule] | None = None, now: float | None = None) -> Rule | None:
    """按 priority 降序取第一条命中；同优先级按 id 稳定排序，保证可复现。"""
    pool = list(rules) if rules is not None else list(DEFAULT_RULES)
    pool.sort(key=lambda r: (-r.priority, r.id))
    for rule in pool:
        if rule.matches(item, now):
            return rule
    return None
