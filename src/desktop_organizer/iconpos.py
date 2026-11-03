"""桌面图标像素坐标的快照与还原。

背景：桌面开着「自动排列图标」时，图标位置不是数据、而是每次按排序键现算的，
注册表里连一个 ItemPos 都没有——那时候任何"记下位置再写回"都不可能成立。
关掉自动排列后，位置由 Explorer 存成每项坐标，这时快照/写回才真正有意义。

本模块分两层：
- 纯逻辑（cell_of / build_snapshot / plan_restore / diff_positions / restore_positions /
  save_snapshot / load_snapshot）：不碰系统，全部可单测；
- Win32 适配（iter_items / set_item_position / get_autoarrange / set_autoarrange）：
  只读桌面 SysListView32，必要时写入坐标，绝不改注册表。
"""

from __future__ import annotations

import ctypes
import json
import os
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

# ---------------------------------------------------------------- 常量

LVM_GETITEMCOUNT = 0x1004
LVM_GETITEMPOSITION = 0x1010
LVM_SETITEMPOSITION = 0x100F
LVM_GETITEMTEXTW = 0x1073
LVS_AUTOARRANGE = 0x0100
GWL_STYLE = -16

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04

DEFAULT_CELL_W = 75
DEFAULT_CELL_H = 104


class _LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", wintypes.UINT),
        ("iItem", ctypes.c_int),
        ("iSubItem", ctypes.c_int),
        ("state", wintypes.UINT),
        ("stateMask", wintypes.UINT),
        ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("lParam", ctypes.c_ssize_t),
        ("iIndent", ctypes.c_int),
        ("iGroupId", ctypes.c_int),
        ("cColumns", wintypes.UINT),
        ("puColumns", ctypes.c_void_p),
    ]


# ---------------------------------------------------------------- 纯逻辑


def cell_of(x: int, y: int, cell_w: int = DEFAULT_CELL_W, cell_h: int = DEFAULT_CELL_H) -> tuple[int, int]:
    """像素坐标 -> (列, 行)。"""
    return (int(x) // max(1, int(cell_w)), int(y) // max(1, int(cell_h)))


def build_snapshot(
    entries: Iterable[tuple[str, int, int]],
    *,
    cell_w: int = DEFAULT_CELL_W,
    cell_h: int = DEFAULT_CELL_H,
) -> dict:
    """把 (名字, x, y) 列表整理成可直接落盘的快照。

    同名项只保留第一次出现（桌面允许同名不同路径的极端情况，映射按名字做，
    重复只会让写回不确定，所以保留首个）。
    """
    items: dict[str, dict[str, int]] = {}
    for name, x, y in entries:
        if not name or name in items:
            continue
        col, row = cell_of(x, y, cell_w, cell_h)
        items[name] = {"x": int(x), "y": int(y), "col": col, "row": row}
    return {
        "version": 1,
        "grid": {"cell_w": int(cell_w), "cell_h": int(cell_h)},
        "items": items,
        "count": len(items),
    }


def plan_restore(snapshot: dict, current_names: Sequence[str]) -> list[dict]:
    """算「哪些名字能写回」——快照里存在、当前桌面也还在的项。"""
    alive = set(current_names)
    items: dict = snapshot.get("items") or {}
    out: list[dict] = []
    for name, pos in items.items():
        if name in alive:
            out.append({"name": name, "x": int(pos["x"]), "y": int(pos["y"])})
    return out


def diff_positions(before: dict, after: dict) -> dict:
    """对比两张快照：哪些挪了、哪些没了、哪些是新出现的。"""
    b: dict = before.get("items") or {}
    a: dict = after.get("items") or {}
    moved = [
        {
            "name": name,
            "from": [b[name]["x"], b[name]["y"]],
            "to": [a[name]["x"], a[name]["y"]],
        }
        for name in b
        if name in a and (b[name]["x"] != a[name]["x"] or b[name]["y"] != a[name]["y"])
    ]
    missing = [name for name in b if name not in a]
    extra = [name for name in a if name not in b]
    return {
        "same": not moved and not missing and not extra,
        "moved": moved,
        "missing": missing,
        "extra": extra,
    }


def restore_positions(
    snapshot: dict,
    *,
    current_names: Sequence[str],
    write_position: Callable[[str, int, int], Any],
    get_autoarrange: Callable[[], bool],
    set_autoarrange: Callable[[bool], Any],
    read_positions: Callable[[], dict[str, tuple[int, int]]] | None = None,
    make_writer: Callable[[], Callable[[str, int, int], Any]] | None = None,
    sleep: Callable[[float], Any] | None = None,
    attempts: int = 10,
    delay: float = 0.15,
) -> dict:
    """按快照写回坐标，然后**回读确认**，没压住就重试。

    自动排列开着时位置会被 ListView 自己接管，写入等于白写，所以先关掉它。
    关掉后**不再自动打开**：一旦重新打开，Explorer 立刻按排序重排，刚写回去的
    位置全都会再次丢掉——这正是用户抱怨「回滚了还是没回原位」的根因。

    为什么必须回读：文件刚被移回桌面时 Explorer 会异步把新条目插进 ListView，
    ``LVM_SETITEMPOSITION`` 写下的坐标可能被这波重排覆盖。只邮一次写成功就宣称
    复原，会得到「少数几个图标跑到别处」这种结果（用户实测过）。因此这里写成
    「写 → 读 → 不一致就再写」的收敛循环，收敛不了就如实报错。
    """
    wants = plan_restore(snapshot, current_names)
    autoarrange_was_on = False
    errors: list[str] = []

    try:
        autoarrange_was_on = bool(get_autoarrange())
    except Exception as exc:  # 读不到就当它开着，宁可多关一次
        errors.append(f"读取自动排列状态失败：{exc}")
        autoarrange_was_on = True

    if autoarrange_was_on:
        try:
            set_autoarrange(False)
        except Exception as exc:
            errors.append(f"关闭自动排列失败：{exc}")

    restored = 0
    skipped = 0
    attempts_used = 1
    verified: bool | None = None
    mismatched: list[str] = []

    if not wants:
        return {
            "restored": 0,
            "skipped": 0,
            "autoarrange_was_on": autoarrange_was_on,
            "errors": errors,
            "planned": 0,
            "verified": True if read_positions else None,
            "mismatched": [],
            "attempts_used": 0,
        }

    def write_all(items: Sequence[dict], writer: Callable[[str, int, int], Any]) -> None:
        nonlocal restored, skipped
        for item in items:
            try:
                writer(item["name"], item["x"], item["y"])
                restored += 1
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                errors.append(f"{item['name']}: {exc}")

    write_all(wants, write_position)

    absent: list[str] = []
    actual: dict[str, tuple[int, int]] = {}
    target: dict[str, tuple[int, int]] = {}
    if read_positions is not None:
        pause = sleep or time.sleep
        snapshot_items: dict = snapshot.get("items") or {}
        target = {item["name"]: (item["x"], item["y"]) for item in wants}
        # 快照里所有名字都进目标集：刚被移回桌面的文件，Explorer 可能还没来得及把它
        # 插进 ListView（current_names 里没有）。一旦它迟到出现，也必须被写回，
        # 否则会被静默跳过——用户看到的就是「有几个文件跑到别处去了」。
        for name, pos in snapshot_items.items():
            target.setdefault(name, (int(pos["x"]), int(pos["y"])))

        for attempt in range(1, max(1, attempts) + 1):
            attempts_used = attempt
            try:
                actual = read_positions()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"回读图标坐标失败：{exc}")
                verified = None
                break
            wrong = [
                name
                for name, want in target.items()
                if name in actual and tuple(actual[name]) != want
            ]
            pending = [name for name in target if name not in actual]
            mismatched = wrong
            verified = not wrong
            if not wrong and not pending:
                break
            if attempt < attempts:
                pause(delay)
                fix = wrong + [name for name in pending if name in actual]
                if fix:
                    # 每次重试重建 writer：Explorer 可能已经插入了新条目，旧索引会错位
                    retry_writer = make_writer() if make_writer is not None else write_position
                    restored = 0
                    skipped = 0
                    write_all(
                        [
                            {"name": n, "x": target[n][0], "y": target[n][1]}
                            for n in fix
                        ],
                        retry_writer,
                    )
        absent = [name for name in target if name not in actual]
        if absent:
            errors.append(
                f"{len(absent)} 个图标尚未出现在桌面上（可能已不在桌面）：{'、'.join(absent[:5])}"
            )
        if verified is False and mismatched:
            errors.append(
                f"图标位置重试 {attempts_used} 次仍未就位：{'、'.join(mismatched[:8])}"
            )

    return {
        # 用户问的是「回去几个」，所以 restored 报本次写回的图标总数，
        # 而不是最后一次重试只修了几个——重试把计数清零过，直接用会得到 17/249 这种假数字。
        "restored": len(target) if target else restored,
        "skipped": skipped,
        "autoarrange_was_on": autoarrange_was_on,
        "errors": errors,
        "planned": len(wants),
        "verified": verified,
        "mismatched": mismatched,
        "absent": absent,
        "attempts_used": attempts_used,
    }


def save_snapshot(snapshot: dict, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, target)
    return target


def load_snapshot(path: str | Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        return None
    return data


# ---------------------------------------------------------------- Win32 适配

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.SendMessageW.restype = ctypes.c_ssize_t
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongW.restype = wintypes.LONG
_user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
_user32.SetWindowLongW.restype = wintypes.LONG
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


def desktop_listview() -> int:
    """返回桌面 SysListView32 的句柄；找不到返回 0。"""
    progman = _user32.FindWindowW("Progman", None)
    defview = _user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None) if progman else 0
    if not defview:
        hits: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _lp):  # pragma: no cover - 只在 Progman 不是宿主时走
            dv = _user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None)
            if dv:
                hits.append(dv)
            return True

        _user32.EnumWindows(_cb, 0)
        defview = hits[0] if hits else 0
    if not defview:
        return 0
    return int(_user32.FindWindowExW(defview, None, "SysListView32", None) or 0)


def iter_items() -> list[tuple[str, int, int]]:
    """读出桌面上每个图标的 (名字, x, y)。只读。"""
    lv = desktop_listview()
    if not lv:
        return []

    count = int(_user32.SendMessageW(lv, LVM_GETITEMCOUNT, 0, 0))
    if count <= 0:
        return []

    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(lv, ctypes.byref(pid))
    access = PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_QUERY_INFORMATION
    hproc = _kernel32.OpenProcess(access, False, pid.value)
    if not hproc:
        return []

    pt_addr = 0
    item_addr = 0
    try:
        pt_addr = _kernel32.VirtualAllocEx(hproc, None, 64, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        size = ctypes.sizeof(_LVITEMW)
        item_addr = _kernel32.VirtualAllocEx(hproc, None, size + 1024, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not pt_addr or not item_addr:
            return []
        text_addr = item_addr + size
        rows: list[tuple[str, int, int]] = []
        for i in range(count):
            _user32.SendMessageW(lv, LVM_GETITEMPOSITION, i, pt_addr)
            pt = wintypes.POINT()
            _kernel32.ReadProcessMemory(hproc, ctypes.c_void_p(pt_addr), ctypes.byref(pt), 8, None)

            item = _LVITEMW()
            item.mask = 0x0001  # LVIF_TEXT
            item.iItem = i
            item.iSubItem = 0
            item.pszText = ctypes.c_void_p(text_addr)
            item.cchTextMax = 260
            _kernel32.WriteProcessMemory(hproc, ctypes.c_void_p(item_addr), ctypes.byref(item), size, None)
            _user32.SendMessageW(lv, LVM_GETITEMTEXTW, i, item_addr)
            buf = ctypes.create_unicode_buffer(260)
            _kernel32.ReadProcessMemory(hproc, ctypes.c_void_p(text_addr), buf, 520, None)
            rows.append((buf.value, int(pt.x), int(pt.y)))
        return rows
    finally:
        if pt_addr:
            _kernel32.VirtualFreeEx(hproc, ctypes.c_void_p(pt_addr), 0, MEM_RELEASE)
        if item_addr:
            _kernel32.VirtualFreeEx(hproc, ctypes.c_void_p(item_addr), 0, MEM_RELEASE)
        _kernel32.CloseHandle(hproc)


def read_positions_live() -> dict[str, tuple[int, int]]:
    """当前每个图标的坐标，给「写回后回读校验」用。"""
    return {name: (x, y) for name, x, y in iter_items()}


def get_autoarrange() -> bool:
    """桌面当前是否开着「自动排列图标」（读的是控件样式位，不是注册表）。"""
    lv = desktop_listview()
    if not lv:        return False
    style = int(_user32.GetWindowLongW(lv, GWL_STYLE)) & 0xFFFFFFFF
    return bool(style & LVS_AUTOARRANGE)


def set_autoarrange(enabled: bool) -> bool:
    """运行时切换自动排列样式位（不写注册表）。

    只影响当前 Explorer 会话的桌面控件；用户在「查看」菜单里改的持久设置
    由 Windows 自己管，我们不碰。
    """
    lv = desktop_listview()
    if not lv:
        return False
    style = int(_user32.GetWindowLongW(lv, GWL_STYLE)) & 0xFFFFFFFF
    new_style = (style | LVS_AUTOARRANGE) if enabled else (style & ~LVS_AUTOARRANGE)
    _user32.SetWindowLongW(lv, GWL_STYLE, new_style)
    return get_autoarrange() == bool(enabled)


def set_item_position(name: str, x: int, y: int) -> bool:
    """把名为 name 的图标挪到 (x, y)。自动排列开着时无效。"""
    return make_position_writer()(name, x, y)


def make_position_writer() -> Callable[[str, int, int], bool]:
    """返回一个批量写坐标的函数：图标索引只枚举一次。

    单个 `set_item_position` 每次都从头枚举全部图标，249 个图标就是 6 万次跨进程
    读——慢到肉眼可见。回滚时用本函数返回的 writer，枚举只发生一次。
    """
    index_cache: dict[str, int] = {}
    listview_cache: list[int] = []

    def write(name: str, x: int, y: int) -> bool:
        lv = listview_cache[0] if listview_cache else desktop_listview()
        if not lv:
            raise OSError("找不到桌面图标控件")
        if not listview_cache:
            listview_cache.append(lv)
        if not index_cache:
            for i, (item_name, _x, _y) in enumerate(iter_items()):
                index_cache.setdefault(item_name, i)
        index = index_cache.get(name)
        if index is None:
            raise OSError(f"桌面上找不到图标: {name}")
        lparam = (int(y) << 16) | (int(x) & 0xFFFF)
        _user32.SendMessageW(lv, LVM_SETITEMPOSITION, index, lparam)
        return True

    return write


def snapshot_live(*, cell_w: int = DEFAULT_CELL_W, cell_h: int = DEFAULT_CELL_H) -> dict:
    """对真实桌面拍一张坐标快照（只读）。"""
    return build_snapshot(iter_items(), cell_w=cell_w, cell_h=cell_h)


def desktop_root() -> Path | None:
    """当前用户的桌面目录（处理 OneDrive 重定向）。拿不到返回 None。"""
    CSIDL_DESKTOPDIRECTORY = 0x0010
    buf = ctypes.create_unicode_buffer(260)
    try:
        _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        # SHGFP_TYPE_CURRENT = 0
        hr = _shell32.SHGetFolderPathW(None, CSIDL_DESKTOPDIRECTORY, None, 0, buf)
        if hr == 0 and buf.value:
            return Path(buf.value)
    except Exception:  # pragma: no cover - 非 Windows / 调用失败时退到默认路径
        pass
    home = Path.home() / "Desktop"
    return home if home.exists() else None


def is_desktop_path(path: str | Path) -> bool:
    """这个路径是不是（等于）当前用户的桌面目录。"""
    root = desktop_root()
    if root is None:
        return False
    try:
        return os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(
            os.path.abspath(str(root))
        )
    except (OSError, ValueError):
        return False
