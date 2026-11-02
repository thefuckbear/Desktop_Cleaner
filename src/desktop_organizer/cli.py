"""命令行入口。

设计原则：
- 默认 dry-run，任何真实写盘都要「两个开关同时打开」+ 交互确认。
- 扫描是只读操作，走 guard.check_read_path（允许用户目录，拒绝系统目录）。
- 执行是写操作，走 executor 内部逐条 assert_safe。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .constants import (
    APP_NAME,
    APP_VERSION,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    DEFAULT_DRY_RUN,
    IMPORTANCE_DIRS,
)
from . import guard
from .model import GuardError


def _fmt_size(n: int) -> str:
    units = ("B", "KB", "MB", "GB")
    val = float(n)
    for unit in units:
        if val < 1024 or unit == units[-1]:
            return f"{val:.0f}{unit}" if unit == "B" else f"{val:.1f}{unit}"
        val /= 1024
    return f"{n}B"


def _short(path: str, limit: int = 46) -> str:
    if len(path) <= limit:
        return path
    return "..." + path[-(limit - 3):]


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    line = "+".join("-" * (w + 2) for w in widths)
    print("+" + line + "+")
    print("| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |")
    print("+" + line + "+")
    for row in rows:
        print("| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)) + " |")
    print("+" + line + "+")


def _load_scanner():
    from . import scanner
    return scanner


def _load_planner():
    from . import planner
    return planner


def _load_executor():
    from . import executor
    return executor


def _load_store():
    from .store import PreferenceStore
    return PreferenceStore()


def _resolve_root(raw: str) -> str:
    resolved = guard.assert_readable(raw)
    return resolved


# ---------------------------------------------------------------- 子命令


def cmd_scan(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    items = _load_scanner().scan(root, max_depth=args.depth)

    skipped = [i for i in items if i.skipped]
    usable = [i for i in items if not i.skipped]

    if args.json:
        print(json.dumps({
            "root": root,
            "total": len(items),
            "usable": len(usable),
            "skipped": len(skipped),
            "items": [i.to_dict() for i in items],
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"根目录: {root}")
    print(f"共 {len(items)} 项，可整理 {len(usable)} 项，跳过 {len(skipped)} 项")
    if usable:
        print()
        _print_table(
            ["文件", "类别提示", "大小", "只读", "云占位"],
            [[_short(i.name), i.ext or "(无)", _fmt_size(i.size),
              "是" if i.readonly else "", "是" if i.cloud_placeholder else ""]
             for i in usable],
        )
    if skipped:
        print(f"\n已跳过 {len(skipped)} 项：")
        for i in skipped[:args.limit]:
            print(f"  - {_short(i.name, 60)}  ({i.skipped_reason})")
        if len(skipped) > args.limit:
            print(f"  ... 其余 {len(skipped) - args.limit} 项省略")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    items = _load_scanner().scan(root, max_depth=args.depth)
    store = _load_store()
    try:
        store.load()
    except Exception:  # 偏好文件损坏不应阻断扫描
        pass

    plan = _load_planner().build_plan(items, root, store)

    if args.json:
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"计划 {plan.plan_id} | 根目录 {root}")
        print(f"共 {len(plan.actions)} 条移动建议（dry-run，未动任何文件）")
        if plan.actions:
            rows = []
            for a in plan.actions:
                rel_dst = os.path.relpath(a.dst, root)
                rows.append([_short(os.path.basename(a.src), 34), _short(rel_dst, 46)])
            _print_table(["文件", "建议移动到"], rows)
        if plan.warnings:
            print("\n提示：")
            for w in plan.warnings:
                print(f"  ! {w}")

    if args.save:
        path = args.save
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(plan.to_dict(), fh, ensure_ascii=False, indent=2)
        print(f"\n计划已保存到 {path}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    if args.plan_file:
        with open(args.plan_file, encoding="utf-8") as fh:
            raw = json.load(fh)
        from .model import Plan, PlanAction
        plan = Plan(
            plan_id=raw["plan_id"], root=raw["root"], created_at=raw["created_at"],
            actions=[PlanAction(**a) for a in raw.get("actions", [])],
            warnings=raw.get("warnings", []),
        )
    else:
        root = _resolve_root(args.root)
        items = _load_scanner().scan(root, max_depth=args.depth)
        store = _load_store()
        try:
            store.load()
        except Exception:
            pass
        plan = _load_planner().build_plan(items, root, store)

    dry_run = True
    if args.no_dry_run and args.yes:
        dry_run = False
    elif args.no_dry_run and not args.yes:
        print("拒绝执行：--no-dry-run 必须同时给出 --yes（防止误操作）。", file=sys.stderr)
        return 4

    result = _load_executor().execute(plan, dry_run=dry_run)
    _print_result(result, dry_run=dry_run)
    return 0 if result.ok or dry_run else 1


def _print_result(result: Any, *, dry_run: bool) -> None:
    mode = "DRY-RUN（未改动任何文件）" if dry_run else "已执行"
    print(f"\n[{mode}]")
    print(f"  applied={result.applied}  skipped={result.skipped}  failed={result.failed}")
    if result.journal_id:
        print(f"  journal={result.journal_id}")
    if result.errors:
        print("  错误：")
        for e in result.errors[:20]:
            print(f"    - {e}")
        if len(result.errors) > 20:
            print(f"    ... 其余 {len(result.errors) - 20} 条省略")


def cmd_rollback(args: argparse.Namespace) -> int:
    executor = _load_executor()
    journal_id = args.journal
    if not journal_id:
        from . import journal
        ids = journal.list_journals()
        if not ids:
            print("没有可回滚的 journal。", file=sys.stderr)
            return 3
        journal_id = ids[-1]
        print(f"未指定 --journal，使用最近一次：{journal_id}")

    result = executor.rollback(journal_id)
    print(f"\n[回滚 {journal_id}]")
    print(f"  已恢复={result.rolled_back}  skipped={result.skipped}  failed={result.failed}")
    for e in result.errors[:20]:
        print(f"  - {e}")
    return 0 if result.failed == 0 else 1


def cmd_journals(args: argparse.Namespace) -> int:
    from . import journal as jr
    ids = jr.list_journals()
    if not ids:
        print("（无）")
        return 0
    for jid in ids[-args.limit:]:
        try:
            records = jr.load(jid)
        except Exception:
            records = []
        done = sum(1 for r in records if r.get("status") == "done")
        started = sum(1 for r in records if r.get("status") == "start")
        print(f"{jid}  记录={len(records)} 已完成={done}  未完成={started - done}")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from .ui.app import launch
    return launch(root=args.root, depth=args.depth)


# ---------------------------------------------------------------- 参数解析


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="desktop-organizer",
        description=f"{APP_NAME} —— 桌面文件整理工具（默认 dry-run，绝不删文件）",
    )
    p.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--root", default=os.environ.get("USERPROFILE", ".") )
        sp.add_argument("--depth", type=int, default=1, help="递归层数，默认 1（只看第一层）")
        sp.add_argument("--json", action="store_true", help="以 JSON 输出便于脚本消费")

    sp = sub.add_parser("scan", help="只读扫描，列出文件与跳过原因")
    add_common(sp)
    sp.add_argument("--limit", type=int, default=20, help="跳过项展示上限")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("plan", help="生成整理计划预览（不动文件）")
    add_common(sp)
    sp.add_argument("--save", default="", help="把计划保存为 JSON 文件")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("apply", help="执行计划（默认 dry-run）")
    add_common(sp)
    sp.add_argument("--plan-file", default="", help="从 plan 保存的 JSON 执行")
    sp.add_argument("--no-dry-run", action="store_true", help="真正写盘（必须同时给 --yes）")
    sp.add_argument("--yes", action="store_true", help="确认执行")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("rollback", help="回滚一次执行")
    sp.add_argument("--journal", default="", help="journal id，缺省用最近一次")
    sp.set_defaults(func=cmd_rollback)

    sp = sub.add_parser("journals", help="列出历史执行日志")
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_journals)

    sp = sub.add_parser("gui", help="启动图形界面")
    sp.add_argument("--root", default=os.environ.get("USERPROFILE", "."))
    sp.add_argument("--depth", type=int, default=1)
    sp.set_defaults(func=cmd_gui)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except GuardError as exc:
        print(f"安全守卫拒绝：{exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
