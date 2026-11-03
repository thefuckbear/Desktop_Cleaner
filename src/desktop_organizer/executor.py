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

from . import guard, iconpos, journal, shellrefresh
from .model import ExecResult, GuardError, Plan, PlanAction

_VALID_KINDS = frozenset({"move"})
_MAX_SUFFIX = 999


def _icons_dir() -> Path:
    """图标快照放在日志目录下，跟着 journal 一起被 Git 忽略。"""
    return journal.journal_dir() / "icons"


def _snapshot_path(journal_id: str) -> Path:
    return _icons_dir() / f"{journal_id}.json"


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


def _ensure_parents(dst_dir: Path, *, dry_run: bool, allow_user_dirs: bool | None = None) -> None:
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
        guard.assert_safe(item, allow_user_dirs=allow_user_dirs)   # 每一级都过守卫
        if not dry_run:
            item.mkdir(exist_ok=True)


class _JournalRef:
    """惰性日志句柄：真要写第一条记录时才创建文件。

    直接调用 ``journal.new_journal()`` 会在循环之前就落一个空文件，
    一旦所有动作都被守卫拦下，磁盘上就只剩一个 0 字节的脏日志。
    """

    __slots__ = ("root", "id")

    def __init__(self, root: str) -> None:
        self.root = root
        self.id = ""

    def ensure(self) -> str:
        if not self.id:
            self.id = journal.new_journal(self.root)
        return self.id


_FILE_WRITE_ATTRIBUTES = 0x0100
_FILE_SHARE_ALL = 0x00000007
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000


def _set_birthtime_win(path: Path, birthtime_ns: int) -> bool:
    """用 Win32 ``SetFileTime`` 把创建时间写回去。

    ``os.utime`` 只能改 mtime/atime，改不了创建时间；而桌面若按「创建日期」
    排序，创建时间就是排序键。跨卷复制会把创建时间刷成"复制那一刻"，
    所以回滚时必须单独修它。失败返回 False，绝不抛异常。
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        kernel32.SetFileTime.argtypes = [
            wintypes.HANDLE, wintypes.LPVOID, wintypes.LPVOID, wintypes.LPVOID,
        ]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = kernel32.CreateFileW(
            str(path),
            _FILE_WRITE_ATTRIBUTES,
            _FILE_SHARE_ALL,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if handle == wintypes.HANDLE(-1).value or handle is None:
            return False
        try:
            # FILETIME = 自 1601-01-01 起的 100ns 数。Unix ns 起点是 1970-01-01，
            # 两者相差 11644473600 秒。
            ticks = birthtime_ns // 100 + 116_444_736_000_000_000
            ft = wintypes.FILETIME(ticks & 0xFFFFFFFF, ticks >> 32)
            return bool(kernel32.SetFileTime(handle, ctypes.byref(ft), None, None))
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001 - 平台差异/权限不足都不该打断回滚
        return False


def _restore_stamp(path: Path, record: dict) -> None:
    """按日志里的原始时间戳复原文件。

    桌面开启「自动排列」时，图标顺序是排序键的纯函数（默认按名称）。
    若用户改成按「修改日期」或「创建日期」排序，时间戳就是排序键 ——
    回滚不动它们，图标就会跟整理前不一致。复原失败不致命，静默放过。
    """
    mtime_ns, atime_ns = record.get("mtime_ns"), record.get("atime_ns")
    if isinstance(mtime_ns, int) and isinstance(atime_ns, int):
        try:
            os.utime(path, ns=(atime_ns, mtime_ns))
        except OSError:
            pass
    birthtime_ns = record.get("birthtime_ns")
    if isinstance(birthtime_ns, int):
        _set_birthtime_win(path, birthtime_ns)


def _prune_empty_dirs(path: Path, *, allow_user_dirs: bool | None = None) -> None:
    """回滚后清掉因本次移动而变空的目录链；遇到非空目录或活不过守卫就停。

    **绝不删除用户数据目录本体**（桌面/文档/下载…）：整理把桌面搬空后
    回滚时若无条件 rmdir，会把用户的 Desktop 目录本身删掉。
    """
    protected = {guard._norm(p) for p in guard._user_data_dirs()}
    node = path
    while node != node.parent:  # 到盘符根为止，绝不越界
        if guard._norm(node) in protected:
            return
        try:
            if any(node.iterdir()):
                return
        except OSError:
            return
        try:
            guard.assert_safe(node, allow_user_dirs=allow_user_dirs)
            node.rmdir()
        except (GuardError, OSError):
            return
        node = node.parent


def _apply_one(
    action: PlanAction,
    *,
    dry_run: bool,
    jref: _JournalRef,
    seq: int,
    allow_user_dirs: bool | None = None,
) -> str:
    """执行单条动作。返回空字符串表示成功，否则返回错误描述。"""
    if action.kind not in _VALID_KINDS:
        return f"[{action.action_id}] 不支持的动作类型: {action.kind!r}（只允许 move）"

    src = Path(action.src)
    dst = Path(action.dst)

    try:
        guard.assert_safe(src, allow_user_dirs=allow_user_dirs)
        guard.assert_safe(dst, allow_user_dirs=allow_user_dirs)
    except GuardError as exc:
        return f"[{action.action_id}] {exc}"

    if not src.is_file():
        return f"[{action.action_id}] 源文件不存在或不是普通文件: {src}"

    try:
        _ensure_parents(dst.parent, dry_run=dry_run, allow_user_dirs=allow_user_dirs)
    except GuardError as exc:
        return f"[{action.action_id}] {exc}"
    except OSError as exc:
        return f"[{action.action_id}] 创建目标目录失败: {exc}"

    final_dst = dst
    try:
        if not dry_run:
            final_dst = _unique_dst(dst)
            guard.assert_safe(final_dst, allow_user_dirs=allow_user_dirs)
    except GuardError as exc:
        return f"[{action.action_id}] {exc}"
    except OSError as exc:
        return f"[{action.action_id}] {exc}"

    if dry_run:
        return ""

    jid = jref.ensure()
    try:
        # 动盘前先记下原始时间戳：桌面按"修改日期"排序时，时间戳就是排序键。
        # 跨卷移动会走 copy2，mtime/atime 虽保留，但回滚同样要复原，所以一律记录。
        st = src.stat()
        st = src.stat()
        stamp = {"mtime_ns": st.st_mtime_ns, "atime_ns": st.st_atime_ns, "size": st.st_size}
        birthtime_ns = getattr(st, "st_birthtime_ns", None)
        if isinstance(birthtime_ns, int):
            stamp["birthtime_ns"] = birthtime_ns
        journal.log(jid, seq, "move", str(src), str(final_dst), "start", extra=stamp)
        shutil.move(str(src), str(final_dst))
        journal.log(jid, seq, "move", str(src), str(final_dst), "done", extra=stamp)
    except Exception as exc:  # noqa: BLE001 - 单条失败不能中断整批
        try:
            journal.log(jid, seq, "move", str(src), str(final_dst), "failed", error=str(exc))
        except Exception:  # 日志写不进去也不能连带炸掉
            pass
        return f"[{action.action_id}] 移动失败: {exc}"
    return ""


def execute(
    plan: Plan,
    dry_run: bool = True,
    *,
    allow_user_dirs: bool | None = None,
    capture_icons: bool | None = None,
) -> ExecResult:
    """执行计划。``dry_run`` 默认 True，只有显式传 False 才会真正动盘。

    ``allow_user_dirs`` 是用户级写盘许可（默认 None = 走 constants 的 False）。
    它由 bridge 从 settings.json 读出来传进来 —— 用户不点头，桌面文件一条都不动。

    ``capture_icons``：是否在动盘前给桌面图标拍坐标快照。
    None = 自动（只有整理的就是桌面本身时才拍）；True/False = 强制开/关。
    拍快照要跨进程读 Explorer 的 ListView，对非桌面目录毫无意义且很慢。
    """
    result = ExecResult()
    if not plan.actions:
        result.ok = True
        return result

    jref = _JournalRef(plan.root)

    want_snapshot = (
        iconpos.is_desktop_path(plan.root) if capture_icons is None else bool(capture_icons)
    )

    # 动任何文件之前先给桌面拍一张"图标坐标快照"。
    # 之所以先读进内存、等 jid 出来再落盘：jid 是懒创建的，全被守卫拒绝时不该留空文件。
    snapshot: dict | None = None
    if not dry_run and want_snapshot:
        try:
            snapshot = iconpos.snapshot_live()
        except Exception as exc:  # noqa: BLE001 - 快照失败不该阻止整理
            result.errors.append(f"图标位置快照失败（不影响文件移动）：{exc}")

    for seq, action in enumerate(plan.actions, start=1):
        error = _apply_one(
            action, dry_run=dry_run, jref=jref, seq=seq, allow_user_dirs=allow_user_dirs
        )
        if error:
            result.failed += 1
            result.errors.append(error)
        else:
            result.applied += 1

    result.journal_id = jref.id
    if snapshot is not None and result.journal_id:
        try:
            iconpos.save_snapshot(snapshot, _snapshot_path(result.journal_id))
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"图标位置快照保存失败（不影响文件移动）：{exc}")
    result.ok = result.failed == 0
    _explain_blanket_rejection(plan, result, allow_user_dirs=allow_user_dirs)
    return result


def _explain_blanket_rejection(
    plan: Plan, result: ExecResult, *, allow_user_dirs: bool | None = None
) -> None:
    """一条都没动且全被守卫拦下时，补一句人话，别让用户只看到一屏报错。"""
    if result.applied or result.failed != len(plan.actions):
        return
    verdicts = [guard.check_path(a.dst, allow_user_dirs=allow_user_dirs) for a in plan.actions]
    blocked = [v for v in verdicts if not v.allowed]
    if len(blocked) != len(verdicts):
        return
    if blocked[0].tier == "userdir":
        result.errors.append(
            f"没有执行任何移动：全部 {len(plan.actions)} 条目标都在用户目录里，"
            "而写盘白名单当前不含用户目录（桌面/文档/下载…）。"
            "如果确实要整理这些目录，请先在界面右上角打开「允许写入用户目录」开关，再点一次执行。"
        )
        return
    result.errors.append(
        f"没有执行任何移动：全部 {len(plan.actions)} 条目标都被安全守卫拒绝（{blocked[0].reason}）。"
        "系统目录与磁盘根目录永久禁止写入，任何白名单开关都不会放行它们。"
    )


def _rollback_targets(records: list[dict]) -> list[dict]:
    """挑出需要复原的记录：已完成的 move，以及"有 start 没 done"的疑似已执行。"""
    done = [r for r in records if r.get("op") == "move" and r.get("status") == "done"]
    done_seqs = {r.get("seq") for r in done}
    started = [
        r for r in records
        if r.get("op") == "move" and r.get("status") == "start" and r.get("seq") not in done_seqs
    ]
    return done + started


def _restore_icons(journal_id: str, result: ExecResult) -> None:
    """回滚之后把图标坐标写回去。

    只有在整理时成功拍过快照才做；拍照失败说明当时也拿不到坐标，
    这时硬写回去反而会把用户当前的布局改乱。
    """
    snapshot = iconpos.load_snapshot(_snapshot_path(journal_id))
    if not snapshot:
        return
    try:
        current_names = [name for name, _x, _y in iconpos.iter_items()]
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"读取当前桌面图标失败，跳过位置复原：{exc}")
        return

    info = iconpos.restore_positions(
        snapshot,
        current_names=current_names,
        write_position=iconpos.make_position_writer(),
        get_autoarrange=iconpos.get_autoarrange,
        set_autoarrange=iconpos.set_autoarrange,
    )
    result.icons = info
    for err in info.get("errors") or []:
        result.errors.append(f"图标位置：{err}")


def rollback(
    journal_id: str,
    *,
    allow_user_dirs: bool | None = None,
    restore_icons: bool = True,
) -> ExecResult:
    """按日志倒序把文件移回原处。源位置已被占用时跳过，绝不覆盖。

    回滚同样是写盘，因此和 execute 一样需要写盘许可。
    ``restore_icons=False`` 时只还原文件、不碰图标位置。
    """
    result = ExecResult()
    records = journal.load(journal_id)
    targets = _rollback_targets(records)
    if not targets:
        result.ok = True
        return result

    new_id_ = journal.new_journal("")
    result.journal_id = new_id_
    restored_srcs: list[str] = []
    roots: set[str] = set()

    for seq, record in enumerate(reversed(targets), start=1):
        src = str(record.get("src", ""))
        dst = str(record.get("dst", ""))
        if not src or not dst:
            result.failed += 1
            result.errors.append(f"[seq={record.get('seq')}] 日志记录缺少 src/dst")
            continue
        try:
            guard.assert_safe(Path(src), allow_user_dirs=allow_user_dirs)
            guard.assert_safe(Path(dst), allow_user_dirs=allow_user_dirs)
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
            _ensure_parents(src_path.parent, dry_run=False, allow_user_dirs=allow_user_dirs)
            journal.log(new_id_, seq, "rollback", dst, src, "start")
            shutil.move(dst, src)
            _restore_stamp(src_path, record)
            journal.log(new_id_, seq, "rollback", dst, src, "done")
            result.rolled_back += 1
            restored_srcs.append(str(src_path))
            roots.add(str(src_path.parent))
            # 回滚后把因本次移动而变空的目录链清掉，别在桌面留一堆空壳
            _prune_empty_dirs(dst_path.parent, allow_user_dirs=allow_user_dirs)
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            result.errors.append(f"[seq={record.get('seq')}] 回滚失败: {exc}")

    # 让 Explorer 重新枚举：桌面图标位置是排序键的函数，但 shell 会缓存槽位，
    # 不主动通知时可能停在旧位置，用户看到的就是「回滚了但没回原处」。
    if restored_srcs:
        for root in sorted(roots):
            shellrefresh.notify_after_rollback(root, restored_srcs)

    # 最后一步：把每个图标摆回整理前的像素坐标（关掉自动排列后位置才是可写的数据）。
    if restore_icons and result.rolled_back:
        _restore_icons(journal_id, result)

    result.ok = result.failed == 0
    return result
