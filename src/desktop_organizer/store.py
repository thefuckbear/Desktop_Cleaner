"""偏好库：记录用户改判，沉淀为下次可直接复用的选择。

文件位置：<项目根>/data/preferences.json（可用构造参数覆盖，测试走 sandbox）。
结构：
    {"version": 1,
     "ext_overrides": {".png": {"category": "文档", "importance": "high", "count": 2}},
     "name_overrides": {"我的笔记": {...}},
     "rules": [...],          # 用户自定义规则（覆盖内置规则）
     "stats": {...}}

纪律：原子写（.tmp + os.replace）；损坏文件备份为 .bak 后从空开始，绝不崩。
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import IMPORTANCE_DIRS, PROJECT_ROOT
from .model import FileItem, Proposal

STORE_VERSION = 1
DEFAULT_PATH = PROJECT_ROOT / "data" / "preferences.json"

STRONG_COUNT = 2
STRONG_CONFIDENCE = 0.95
WEAK_CONFIDENCE = 0.90


def _empty() -> dict[str, Any]:
    return {
        "version": STORE_VERSION,
        "ext_overrides": {},
        "name_overrides": {},
        "rules": [],
        "stats": {},
    }


class PreferenceStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self._data: dict[str, Any] = _empty()
        self.load()

    # ---------- 读写 ----------

    def load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._data = _empty()
            return
        except OSError:
            self._data = _empty()
            return

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self._quarantine()
            self._data = _empty()
            return

        if not isinstance(data, dict) or not data.get("version"):
            self._quarantine()
            self._data = _empty()
            return

        self._data = _empty()
        for key in ("ext_overrides", "name_overrides", "stats"):
            value = data.get(key)
            if isinstance(value, dict):
                self._data[key] = value
        rules = data.get("rules")
        if isinstance(rules, list):
            self._data["rules"] = [r for r in rules if isinstance(r, dict)]

    def save(self) -> None:
        """原子写：先写 .tmp，再 os.replace；中途崩溃不会留下半截 JSON。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)

    def _quarantine(self) -> None:
        backup = self.path.with_name(self.path.name + ".bak")
        try:
            shutil.copyfile(self.path, backup)
            # copyfile 而不是 move：保留原文件便于事后人工抢救
        except OSError:
            pass

    # ---------- 改判学习 ----------

    def remember(self, item: FileItem, proposal: Proposal | None, user_choice: Proposal) -> None:
        """记录一次用户选择。同一扩展名/文件名累加 count，>=2 视为强偏好。"""
        kind, key = _key(item)
        bucket_name = "ext_overrides" if kind == "ext" else "name_overrides"
        bucket = self._data.setdefault(bucket_name, {})
        entry = bucket.get(key) or {}
        entry["category"] = user_choice.category
        entry["importance"] = user_choice.importance or "medium"
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        bucket[key] = entry

        stats = self._data.setdefault("stats", {})
        stats["remembered"] = int(stats.get("remembered", 0)) + 1
        stats["last_updated"] = entry["updated_at"]
        self.save()

    def lookup(self, item: FileItem) -> Proposal | None:
        """查历史偏好。名字精确命中优先于扩展名（扩展名只能证明弱相似）。"""
        entry = self._data.get("name_overrides", {}).get(item.name.lower())
        rule_id = f"pref-name-{item.name.lower()}" if entry else ""
        if entry is None and item.ext:
            entry = self._data.get("ext_overrides", {}).get(item.ext.lower())
            rule_id = f"pref-ext-{item.ext.lower()}" if entry else ""
        if not entry:
            return None
        return _proposal_from_entry(item, entry, rule_id)

    def export_rules(self) -> list[dict[str, Any]]:
        """把强偏好导出成规则（同时返回用户自定义规则），供 rules 引擎加载。"""
        rules: list[dict[str, Any]] = [dict(r) for r in self._data.get("rules", [])]

        for key, entry in sorted(self._data.get("ext_overrides", {}).items()):
            if int(entry.get("count", 0)) < STRONG_COUNT:
                continue
            rules.append(_rule_from_entry(f"pref-ext-{key}", {"ext_in": [key]}, entry))

        for key, entry in sorted(self._data.get("name_overrides", {}).items()):
            if int(entry.get("count", 0)) < STRONG_COUNT:
                continue
            rules.append(_rule_from_entry(f"pref-name-{key}", {"name_contains": [key]}, entry))

        return rules


def _key(item: FileItem) -> tuple[str, str]:
    if item.ext:
        return "ext", item.ext.lower()
    return "name", item.name.lower()


def _proposal_from_entry(item: FileItem, entry: dict[str, Any], rule_id: str) -> Proposal:
    category = str(entry.get("category") or "其他")
    importance = str(entry.get("importance") or "medium")
    if importance not in IMPORTANCE_DIRS:
        importance = "medium"
    count = int(entry.get("count", 1))
    confidence = STRONG_CONFIDENCE if count >= STRONG_COUNT else WEAK_CONFIDENCE
    return Proposal(
        path=item.path,
        target_dir=f"{category}/{IMPORTANCE_DIRS[importance]}",
        category=category,
        importance=importance,
        confidence=confidence,
        reasons=[f"沿用你的历史选择（{category}/{IMPORTANCE_DIRS[importance]}，已记录 {count} 次）"],
        rule_id=rule_id,
    )


def _rule_from_entry(rule_id: str, matcher: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    importance = str(entry.get("importance") or "medium")
    return {
        "id": rule_id,
        "matcher": matcher,
        "target_category": str(entry.get("category") or "其他"),
        "importance": importance,
        "confidence": STRONG_CONFIDENCE,
        "priority": 100,
        "description": f"由改判学习沉淀（{entry.get('count')} 次）",
    }
