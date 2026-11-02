"""tkinter 主界面：扫描 → 预览 → 勾选/改判 → 一键采纳高置信 → 执行 → 回滚。

设计约束：
- UI 只做「展示 + 收集决策」，不做任何文件操作；所有写盘都委托 executor。
- 默认 dry-run 勾选；「真正执行」按钮必须二次确认。
- 改判立即写进 PreferenceStore，下次扫描生效。
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from ..constants import (
    APP_NAME,
    APP_VERSION,
    CATEGORIES,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    IMPORTANCE_DIRS,
    IMPORTANCE_ORDER,
)


class OrganizerApp:
    def __init__(self, root_path: str, depth: int = 1) -> None:
        self.root_path = root_path
        self.depth = depth
        self.items: list[Any] = []
        self.proposals: dict[str, Any] = {}
        self.selected: set[str] = set()
        self.store = None
        self._last_journal = ""

        self.win = tk.Tk()
        self.win.title(f"{APP_NAME} v{APP_VERSION}  [DRY-RUN 默认]")
        self.win.geometry("1080x640")
        self.win.minsize(880, 520)

        self._build()
        self._load_store()

    # ------------------------------------------------------------ 构建界面
    def _build(self) -> None:
        top = ttk.Frame(self.win, padding=(10, 8))
        top.pack(fill=tk.X)

        ttk.Label(top, text="目录：").pack(side=tk.LEFT)
        self.var_root = tk.StringVar(value=self.root_path)
        entry = ttk.Entry(top, textvariable=self.var_root, width=58)
        entry.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Label(top, text="层数：").pack(side=tk.LEFT)
        self.var_depth = tk.StringVar(value=str(self.depth))
        ttk.Spinbox(top, from_=1, to=5, width=4, textvariable=self.var_depth).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(top, text="扫描（只读）", command=self.on_scan).pack(side=tk.LEFT)
        ttk.Button(top, text="生成计划", command=self.on_plan).pack(side=tk.LEFT, padx=(6, 0))

        mid = ttk.Frame(self.win, padding=(10, 0))
        mid.pack(fill=tk.BOTH, expand=True)

        cols = ("sel", "name", "ext", "size", "category", "importance", "conf", "target")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=18)
        headings = {
            "sel": "选", "name": "文件名", "ext": "类型", "size": "大小",
            "category": "类别", "importance": "重要度", "conf": "置信度", "target": "目标位置",
        }
        widths = {"sel": 40, "name": 280, "ext": 60, "size": 80,
                  "category": 90, "importance": 80, "conf": 70, "target": 260}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor="w")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<space>", self.on_toggle_row)

        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

        bottom = ttk.Frame(self.win, padding=(10, 8))
        bottom.pack(fill=tk.X)

        ttk.Button(bottom, text="全选高置信", command=self.on_select_high).pack(side=tk.LEFT)
        ttk.Button(bottom, text="全不选", command=self.on_select_none).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(bottom, text="改类别", command=self.on_double_click).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(bottom, text="保存改判", command=self.on_save_prefs).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Separator(bottom, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(bottom, text="预览（dry-run）", command=lambda: self.on_execute(False)).pack(side=tk.LEFT)
        ttk.Button(bottom, text="真正执行…", command=lambda: self.on_execute(True)).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(bottom, text="回滚最近一次", command=self.on_rollback).pack(side=tk.LEFT, padx=(6, 0))

        self.status = tk.StringVar(value="就绪。默认 dry-run，不会改动任何文件。")
        ttk.Label(self.win, textvariable=self.status, relief=tk.SUNKEN, anchor="w").pack(fill=tk.X, side=tk.BOTTOM)

        ttk.Label(
            self.win,
            text="⚠ 系统目录与用户数据目录受硬拦截；云占位文件只列出不触碰。",
            anchor="w", foreground="#a04000",
        ).pack(fill=tk.X, side=tk.BOTTOM, padx=10)

    # ------------------------------------------------------------ 数据
    def _load_store(self) -> None:
        try:
            from ..store import PreferenceStore
            self.store = PreferenceStore()
            self.store.load()
        except Exception as exc:
            self.status.set(f"偏好存储不可用（{exc}），将只使用内置规则。")
            self.store = None

    def _scan(self) -> list[Any]:
        from .. import guard, scanner
        root = guard.assert_readable(self.var_root.get().strip())
        depth = int(self.var_depth.get() or 1)
        return scanner.scan(root, max_depth=depth)

    def _plan(self) -> Any:
        from .. import planner
        items = [i for i in self.items if not i.skipped]
        return planner.build_plan(items, self.var_root.get().strip(), self.store)

    # ------------------------------------------------------------ 事件
    def on_scan(self) -> None:
        try:
            self.items = self._scan()
        except Exception as exc:
            messagebox.showerror("扫描失败", str(exc))
            return
        usable = [i for i in self.items if not i.skipped]
        skipped = len(self.items) - len(usable)
        self.status.set(f"扫描完成：可整理 {len(usable)} 项，跳过 {skipped} 项。点「生成计划」看建议。")
        self._render([(i, None) for i in usable])

    def on_plan(self) -> None:
        if not self.items:
            messagebox.showinfo("提示", "请先扫描。")
            return
        try:
            plan = self._plan()
        except Exception as exc:
            messagebox.showerror("生成计划失败", str(exc))
            return
        self._render_plan(plan)
        high = sum(1 for a in plan.actions
                   if self.proposals.get(a.src) and self.proposals[a.src].confidence >= CONFIDENCE_HIGH)
        self.status.set(
            f"计划 {plan.plan_id}：{len(plan.actions)} 条建议，其中高置信 {high} 条。"
            f" 双击可改类别，空格切换勾选。"
        )

    def _render(self, pairs: list[tuple[Any, Any]]) -> None:
        self.tree.delete(*self.tree.get_children())
        self.selected.clear()
        self.proposals.clear()
        for item, prop in pairs:
            self._insert_row(item, prop, checked=False)

    def _render_plan(self, plan: Any) -> None:
        by_src = {a.src: a for a in plan.actions}
        self.tree.delete(*self.tree.get_children())
        self.selected.clear()
        self.proposals.clear()
        for item in self.items:
            if item.skipped:
                continue
            action = by_src.get(item.path)
            prop = self._proposal_for(item, action)
            checked = prop is not None and prop.confidence >= CONFIDENCE_HIGH
            if checked:
                self.selected.add(item.path)
            self._insert_row(item, prop, checked)

    def _proposal_for(self, item: Any, action: Any) -> Any:
        if action is None:
            return None
        parts = os.path.normpath(action.dst).split(os.sep)
        category = parts[-2] if len(parts) >= 2 else "其他"
        importance = "medium"
        for key, label in IMPORTANCE_DIRS.items():
            if label in parts:
                importance = key
                break
        from ..model import Proposal
        base = self.proposals.get(item.path)
        prop = base if base is not None else Proposal(
            path=item.path, target_dir="/".join(parts[-2:-1]), category=category,
            importance=importance, confidence=0.5, reasons=["来自计划"], rule_id="",
        )
        prop.category = prop.category or category
        prop.importance = prop.importance or importance
        if prop.confidence <= 0:
            prop.confidence = 0.5
        return prop

    def _insert_row(self, item: Any, prop: Any, checked: bool) -> None:
        if prop is not None:
            self.proposals[item.path] = prop
        category = getattr(prop, "category", "其他") if prop else "其他"
        importance = getattr(prop, "importance", "medium") if prop else "medium"
        conf = getattr(prop, "confidence", 0.0) if prop else 0.0
        target = f"{category}/{IMPORTANCE_DIRS.get(importance, '归档')}"
        self.tree.insert(
            "", tk.END,
            iid=item.path,
            values=(
                "☑" if checked else "☐",
                item.name,
                item.ext or "(无)",
                _fmt_size(item.size),
                category,
                IMPORTANCE_DIRS.get(importance, importance),
                f"{conf:.2f}" + (" 高" if conf >= CONFIDENCE_HIGH else (" 中" if conf >= CONFIDENCE_MEDIUM else " 低")),
                target,
            ),
        )

    def _toggle(self, path: str) -> None:
        values = list(self.tree.item(path, "values"))
        if not values:
            return
        if path in self.selected:
            self.selected.discard(path)
            values[0] = "☐"
        else:
            self.selected.add(path)
            values[0] = "☑"
        self.tree.item(path, values=values)

    def on_toggle_row(self, _event: Any = None) -> str:
        sel = self.tree.selection()
        if sel:
            self._toggle(sel[0])
        return "break"

    def on_double_click(self, _event: Any = None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        path = sel[0]
        prop = self.proposals.get(path)
        if prop is None:
            return
        dlg = tk.Toplevel(self.win)
        dlg.title("改判这条建议")
        dlg.transient(self.win)
        dlg.grab_set()
        dlg.geometry("320x200")

        ttk.Label(dlg, text=os.path.basename(path), padding=(10, 8)).pack(anchor="w")

        frm1 = ttk.Frame(dlg, padding=(10, 0))
        frm1.pack(fill=tk.X)
        ttk.Label(frm1, text="类别：", width=8).pack(side=tk.LEFT)
        var_cat = tk.StringVar(value=prop.category)
        ttk.Combobox(frm1, textvariable=var_cat, values=list(CATEGORIES), state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)

        frm2 = ttk.Frame(dlg, padding=(10, 8))
        frm2.pack(fill=tk.X)
        ttk.Label(frm2, text="重要度：", width=8).pack(side=tk.LEFT)
        var_imp = tk.StringVar(value=IMPORTANCE_DIRS.get(prop.importance, "常用"))
        ttk.Combobox(frm2, textvariable=var_imp,
                     values=[IMPORTANCE_DIRS[k] for k in IMPORTANCE_ORDER],
                     state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)

        def confirm() -> None:
            prop.category = var_cat.get()
            prop.importance = next(
                (k for k, v in IMPORTANCE_DIRS.items() if v == var_imp.get()), "medium"
            )
            self._insert_row(self.items[[i.path for i in self.items].index(path)] if path in [i.path for i in self.items] else None, prop, path in self.selected)
            self.status.set(f"已改判：{os.path.basename(path)} → {prop.category}/{IMPORTANCE_DIRS[prop.importance]}（记得点「保存改判」）")
            dlg.destroy()

        ttk.Button(dlg, text="确定", command=confirm).pack(pady=8)
        dlg.wait_window()

    def on_select_high(self) -> None:
        for path, prop in self.proposals.items():
            if prop.confidence >= CONFIDENCE_HIGH:
                self.selected.add(path)
                self._toggle(path) if path not in self.selected else None
        for path in list(self.selected):
            if prop := self.proposals.get(path):
                values = list(self.tree.item(path, "values"))
                if values:
                    values[0] = "☑"
                    self.tree.item(path, values=values)
        self.status.set(f"已选中 {len(self.selected)} 条高置信建议。")

    def on_select_none(self) -> None:
        self.selected.clear()
        for path in self.tree.get_children():
            values = list(self.tree.item(path, "values"))
            if values:
                values[0] = "☐"
                self.tree.item(path, values=values)
        self.status.set("已清空选择。")

    def on_save_prefs(self) -> None:
        if self.store is None:
            messagebox.showwarning("不可用", "偏好存储未初始化。")
            return
        n = 0
        for path, prop in self.proposals.items():
            item = next((i for i in self.items if i.path == path), None)
            if item is None:
                continue
            self.store.remember(item, prop, prop)
            n += 1
        self.store.save()
        self.status.set(f"已保存 {n} 条偏好，下次扫描同类文件会直接沿用。")
        messagebox.showinfo("已保存", f"写入 {n} 条偏好。")

    def on_execute(self, real: bool) -> None:
        if not self.selected:
            messagebox.showinfo("提示", "没有选中任何条目。")
            return
        if real:
            ok = messagebox.askyesno(
                "确认真正执行",
                f"将真实移动 {len(self.selected)} 个文件。\n\n"
                "此操作可通过「回滚最近一次」撤销，但仍建议先预览。\n\ndry-run 记录会写入 journal，执行前请确认目录无误。\n\n继续？",
                icon="warning",
            )
            if not ok:
                return
        plan = self._plan()
        actions = [a for a in plan.actions if a.src in self.selected]
        plan.actions = actions
        from .. import executor
        try:
            result = executor.execute(plan, dry_run=not real)
        except Exception as exc:
            messagebox.showerror("执行失败", str(exc))
            return
        self._last_journal = result.journal_id
        mode = "真正执行" if real else "dry-run"
        msg = (f"[{mode}] applied={result.applied} skipped={result.skipped} "
               f"failed={result.failed} journal={result.journal_id}")
        self.status.set(msg)
        if result.errors:
            messagebox.showwarning("部分失败", "\n".join(result.errors[:10]))
        elif real:
            messagebox.showinfo("完成", f"已移动 {result.applied} 个文件。\n可用「回滚最近一次」撤销。")
        else:
            messagebox.showinfo("预览完成", f"将会移动 {result.applied} 个文件（未实际改动）。")

    def on_rollback(self) -> None:
        from .. import executor
        try:
            if self._last_journal:
                result = executor.rollback(self._last_journal)
            else:
                from .. import journal as jr
                ids = jr.list_journals()
                if not ids:
                    messagebox.showinfo("提示", "没有可回滚的记录。")
                    return
                result = executor.rollback(ids[-1])
        except Exception as exc:
            messagebox.showerror("回滚失败", str(exc))
            return
        self.status.set(f"回滚完成：恢复 {result.rolled_back} 项，失败 {result.failed} 项。")

    def run(self) -> int:
        self.win.mainloop()
        return 0


def _fmt_size(n: int) -> str:
    val = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if val < 1024 or unit == "GB":
            return f"{val:.0f}{unit}" if unit == "B" else f"{val:.1f}{unit}"
        val /= 1024
    return f"{n}B"


def launch(root: str | None = None, depth: int = 1) -> int:
    default_root = root or os.environ.get("USERPROFILE", ".")
    return OrganizerApp(default_root, depth).run()
