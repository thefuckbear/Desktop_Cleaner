"""pywebview 桥接层：前端（HTML/JS）唯一能触达核心的入口。

设计纪律：
- 只暴露必要方法，返回的全部是 **JSON 安全的 dict**（pywebview 用 JSON 传输）。
- `apply()` 默认 `dry_run=True`：JS 侧必须显式传 False 才真正移动文件。
- 任何写盘动作前，核心模块（executor/guard）已有硬拦截；本层不重复造闸门，也不放宽。
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any, Callable

from . import ai_assistant, executor, journal, planner, scanner, settings
from .model import FileItem, Plan, PlanAction, Proposal
from .progress import ProgressEvent
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
        settings_path: str | Path | None = None,
    ) -> None:
        self.root = str(root) if root else os.path.expanduser("~\\Desktop")
        self.depth = max(0, int(depth))
        self.store = PreferenceStore(store_path)
        self._settings_path = settings_path
        self._items: list[FileItem] = []
        self._plan: Plan | None = None
        self._last_journal = ""
        self._window: Any = None
        self._progress: dict[str, Any] = ProgressEvent.create("scan", 0, 0).to_dict()

    # ---------- 进度推流 ----------

    def set_window(self, window: Any) -> None:
        """由 gui_web 在 create_window 之后注入，用于把进度推给前端。"""
        self._window = window

    def notify_progress(
        self,
        stage: str,
        current: int,
        total: int,
        current_item: str = "",
        message: str = "",
    ) -> None:
        """推一条进度给前端。窗口没了、JS 报错都只当没发生。"""
        try:
            event = ProgressEvent.create(
                stage, current, total, current_item=current_item, message=message
            )
        except ValueError:
            return  # 未知阶段：宁可丢一条进度，也不能打断整理
        self._progress = event.to_dict()
        if self._window is None:
            return
        try:
            script = (
                "window.onProgress && window.onProgress("
                + json.dumps(event.to_dict(), ensure_ascii=False)
                + ")"
            )
            self._window.evaluate_js(script)
        except Exception:  # noqa: BLE001 - 推流失败不得影响业务
            pass

    def progress(self) -> dict[str, Any]:
        """最后一条进度快照：界面初次加载或重连时用来回填。"""
        return dict(self._progress)

    def _progress_cb(self, stage: str) -> Callable[[int, int, str], None] | None:
        """只在有窗口时才返回回调：CLI/单测没必要为此多传一个参数。"""
        if self._window is None:
            return None

        def _report(done: int, total: int, label: str = "") -> None:
            self.notify_progress(stage, done, total, current_item=label)

        return _report

    def _with_progress(
        self, stage: str, kwargs: dict[str, Any], *, key: str = "progress_cb"
    ) -> dict[str, Any]:
        """把回调塞进调用参数——没有窗口就什么都不加。

        scanner 用的参数名是 on_progress，executor 用 progress_cb，所以名字要能指定。
        """
        cb = self._progress_cb(stage)
        if cb is not None:
            kwargs[key] = cb
        return kwargs

    # ---------- 设置（写盘许可）----------

    def settings(self) -> dict[str, Any]:
        """给前端读当前设置。目前只有"是否允许写用户目录"。"""
        return settings.as_dict(self._settings_path)

    def set_allow_user_dirs(self, value: bool) -> dict[str, Any]:
        """用户在界面上亲手打开/关闭写盘许可，立即落盘，下次启动仍生效。"""
        settings.set_allow_user_dirs(value is True, path=self._settings_path)
        return self.settings()

    # ---------- 只读 ----------

    def scan(self) -> dict[str, Any]:
        """只读扫描。路径守卫在 scanner 内部（assert_readable）先跑。"""
        items = scanner.scan(
            self.root,
            **self._with_progress("scan", {"max_depth": self.depth}, key="on_progress"),
        )
        self._items = items
        self._plan = None
        self.notify_progress("scan", len(items), max(len(items), 1), message="扫描完成")
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
        """单文件当前的目标行（用户改判/改去向之后刷新界面用）。

        有当前计划时以计划为准：用户手动改过的去向必须原样返回，不能
        被重新分类盖掉。
        """
        item = self._find(path)
        if item is None:
            return None
        action: PlanAction | None = None
        if self._plan is not None:
            want = os.path.normcase(os.path.abspath(path))
            for candidate in self._plan.actions:
                if os.path.normcase(os.path.abspath(candidate.src)) == want:
                    action = candidate
                    break
        if action is not None:
            return _row(item, self._proposal_of(item, action), action.action_id)
        from .classify import classify

        return _row(item, classify(item, self.store), "")


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
        result = executor.execute(
            plan,
            dry_run=dry_run,
            allow_user_dirs=self._permitted(),
            **self._with_progress("apply", {}),
        )
        payload = result.to_dict()
        payload["dry_run"] = bool(dry_run)
        if result.journal_id:
            self._last_journal = result.journal_id
        return payload

    def rollback(self, journal_id: str = "", restore_icons: bool = True) -> dict[str, Any]:
        """回滚。不传则回滚最近一次成功执行。"""
        target = journal_id or self._last_journal
        if not target:
            ids = journal.list_journals()
            target = ids[-1] if ids else ""
        if not target:
            return {"ok": False, "rolled_back": 0, "errors": ["没有可回滚的执行记录"]}
        return executor.rollback(
            target,
            allow_user_dirs=self._permitted(),
            restore_icons=restore_icons,
            **self._with_progress("rollback", {}),
        ).to_dict()

    def _permitted(self) -> bool:
        """每次写盘前现读设置，不缓存：用户刚关掉开关就得立刻生效。"""
        return settings.allow_user_dirs(self._settings_path)

    # ---------- AI 顾问 ----------

    def ai_settings(self) -> dict[str, Any]:
        """前端读 AI 配置。api_key 一律打码，只回 has_key。"""
        return settings.ai_config_dict(self._settings_path)

    def save_ai_settings(
        self,
        provider: str,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        custom_folders: list[str] | None = None,
    ) -> dict[str, Any]:
        """保存 AI 配置。

        ``api_key`` 传空串表示"保持原来的 key 不变"——界面只显示打码值，
        用户没重填就不该把 key 清掉。
        """
        current = settings.ai_config(self._settings_path)
        cfg = ai_assistant.AIConfig(
            provider=provider if provider in ai_assistant.PROVIDERS else "off",  # type: ignore[arg-type]
            api_key=api_key or current.api_key,
            base_url=base_url or current.base_url,
            model=model or current.model,
            custom_folders=list(
                custom_folders if custom_folders is not None else current.custom_folders
            ),
        )
        settings.set_ai_config(cfg, self._settings_path)
        return self.ai_settings()

    def ai_suggest(self, transport: ai_assistant.Transport | None = None) -> dict[str, Any]:
        """让 AI（或本地规则）为当前扫描结果给出建议。

        必须在 scan/plan 之后调用：没有文件就没什么可建议的。
        """
        items = [i for i in self._items if not i.skipped_reason]
        if not items:
            return {
                "total": 0,
                "degraded": True,
                "reason": "还没有扫描到文件，请先扫描",
                "suggestions": [],
            }
        self.notify_progress("ai_analyzing", 0, len(items), message="正在分析文件元数据")
        cfg = settings.ai_config(self._settings_path)
        suggestions, degraded, reason = ai_assistant.analyze(
            items, cfg, store=self.store, transport=transport
        )
        self.notify_progress(
            "ai_analyzing",
            len(suggestions),
            max(len(suggestions), 1),
            message="分析完成" if not degraded else reason,
        )
        return {
            "total": len(suggestions),
            "degraded": bool(degraded),
            "reason": reason,
            "suggestions": [
                {
                    "path": s.path,
                    "name": os.path.basename(s.path),
                    "target_dir": s.target_dir,
                    "category": s.category,
                    "confidence": round(float(s.confidence), 2),
                    "reason": s.reason,
                }
                for s in suggestions
            ],
        }

    def apply_suggestions(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """一键采纳：把建议里的去向写进当前计划（不移动任何文件）。"""
        plan = self._plan
        if plan is None:
            return {"ok": False, "error": "请先生成整理计划再采纳建议", "updated": 0}

        groups: dict[str, list[str]] = {}
        # 计划里没有的路径直接忽略：AI 可能建议了扫描后已消失的文件，
        # 这种"过期建议"不该让整批采纳失败。
        known = {os.path.normcase(os.path.abspath(a.src)) for a in plan.actions}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or "")
            target = str(row.get("target_dir") or "")
            if not path or not target:
                continue
            if os.path.normcase(os.path.abspath(path)) not in known:
                continue
            groups.setdefault(target, []).append(path)

        updated = 0
        for target, paths in groups.items():
            res = self._apply_target(paths, target)
            if not res.get("ok"):
                return {"ok": False, "error": res.get("error", "改去向失败"), "updated": updated}
            updated += int(res.get("updated") or 0)
        return {"ok": True, "error": "", "updated": updated, "plan": self._plan_payload(self._plan)}

    # ---------- 自由去向 ----------

    def set_target_dir(self, path: str, target_dir: str) -> dict[str, Any]:
        """把单个文件改到用户自命名的子目录。"""
        return self._apply_target([path], target_dir)

    def set_target_dir_bulk(self, paths: list[str], target_dir: str) -> dict[str, Any]:
        """批量改去向（配合界面的多选）。"""
        return self._apply_target(list(paths or []), target_dir)

    def _apply_target(self, paths: list[str], target_dir: str) -> dict[str, Any]:
        from . import guard, targetdir

        ok, value = targetdir.validate(target_dir, self.root)
        if not ok:
            return {"ok": False, "error": value, "updated": 0}

        plan = self._plan
        if plan is None:
            return {"ok": False, "error": "请先生成整理计划再改去向", "updated": 0}

        wanted = {os.path.normcase(os.path.abspath(p)) for p in paths}
        if not wanted:
            return {"ok": False, "error": "没有选中任何文件", "updated": 0}

        dst_dir = os.path.join(self.root, value)
        try:
            # 先在 guard 处把目标目录验一遍：宁可整批拒绝，也不要改了一半。
            guard.assert_safe(dst_dir, allow_user_dirs=self._permitted())
        except guard.GuardError as exc:
            return {"ok": False, "error": str(exc), "updated": 0}

        updated = 0
        new_actions = []
        for action in plan.actions:
            if os.path.normcase(os.path.abspath(action.src)) in wanted:
                new_actions.append(
                    dataclasses.replace(
                        action, dst=os.path.join(dst_dir, os.path.basename(action.src))
                    )
                )
                updated += 1
            else:
                new_actions.append(action)

        if not updated:
            return {"ok": False, "error": "选中的文件不在当前计划里", "updated": 0}

        self._plan = dataclasses.replace(plan, actions=new_actions)
        # 计划变了，前端要能立刻看到新的目标路径；顺便保持 _items 与计划的对应关系。
        return {
            "ok": True,
            "error": "",
            "updated": updated,
            "target_dir": value,
            "plan": self._plan_payload(self._plan),
        }

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
