"""桌面图标的「一键紧凑排版」引擎。

设计哲学：**只搬图标坐标，绝不碰文件系统**。本模块只发送 ListView 消息，
不调用任何 rename / remove / move —— 文件还是那些文件，只是排整齐了。

分两层，和 iconpos 一样：
- 纯逻辑（sort_icons / group_icons / compute_compact_grid / grid_capacity）：
  不碰句柄，虚拟数据就能单测；
- 执行链路（apply_layout / undo_layout）：所有系统调用都以关键字参数注入，
  测试里换成假件就能跑完整条「备份 → 关自动排列 → 写坐标 → 撤销」。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from . import constants, iconpos

# ---------------------------------------------------------------- 数据契约


@dataclass(frozen=True)
class DesktopIconInfo:
    """桌面上的一个图标（不是文件——文件在磁盘上，这里只有排版需要的信息）。"""

    name: str
    current_x: int
    current_y: int
    is_special: bool  # 此电脑、回收站、网络…桌面上没有真实文件对应
    is_shortcut: bool  # .lnk / .url
    is_directory: bool
    ext: str  # 小写，含点，如 ".docx"
    mtime: float


@dataclass(frozen=True)
class ScreenWorkArea:
    """桌面可用区域 + 网格步长。"""

    left: int
    top: int
    right: int
    bottom: int
    cell_w: int
    cell_h: int

    @property
    def max_rows(self) -> int:
        return max(1, (self.bottom - self.top - 10) // max(1, self.cell_h))

    @property
    def start_x(self) -> int:
        return self.left + MARGIN

    @property
    def start_y(self) -> int:
        return self.top + MARGIN


@dataclass(frozen=True)
class LayoutResult:
    total: int
    moved_count: int
    strategy: str
    undo_available: bool


MARGIN = 12
_SHORTCUT_EXTS = frozenset({".lnk", ".url"})

_SM_CXICONSPACING = 38
_SM_CYICONSPACING = 39
_SPI_GETWORKAREA = 0x0030


# ---------------------------------------------------------------- 策略


def strategies() -> list[dict[str, str]]:
    """给前端下拉框用的策略清单（顺序即展示顺序）。"""
    return [
        {
            "id": "shortcuts_first",
            "name": "快捷方式优先",
            "desc": "系统图标 → 快捷方式 → 普通文件 → 文件夹，各自的都按名称升序",
        },
        {
            "id": "grouped_columns",
            "name": "分区看板",
            "desc": "四组各占新列：系统图标 / 快捷方式 / 文件 / 文件夹，一眼分得清",
        },
        {
            "id": "compact_time",
            "name": "最近活跃优先",
            "desc": "快捷方式照旧在前，普通文件按修改时间从新到旧排",
        },
    ]


def normalize_strategy(strategy_id: str) -> str:
    """未知策略一律回落，别把用户传错的值原样回显成"成功了"。"""
    known = {item["id"] for item in strategies()}
    return strategy_id if strategy_id in known else "shortcuts_first"


def _rank(item: DesktopIconInfo) -> int:
    if item.is_special:
        return 0
    if item.is_shortcut:
        return 1
    if item.is_directory:
        return 3
    return 2


def _name_key(item: DesktopIconInfo) -> tuple[str, str]:
    return (item.name.casefold(), item.name)


def sort_icons(items: Sequence[DesktopIconInfo], strategy: str = "shortcuts_first") -> list[DesktopIconInfo]:
    """按策略排序。未知策略回落到 shortcuts_first，绝不抛异常打断排版。"""
    ordered = list(items)

    if strategy == "compact_time":
        shortcuts_and_special = [i for i in ordered if _rank(i) <= 1]
        files = [i for i in ordered if _rank(i) == 2]
        dirs = [i for i in ordered if _rank(i) == 3]
        shortcuts_and_special.sort(key=_name_key)
        files.sort(key=lambda i: (-float(i.mtime),) + _name_key(i))
        dirs.sort(key=_name_key)
        return shortcuts_and_special + files + dirs

    return sorted(ordered, key=lambda i: (_rank(i),) + _name_key(i))


def group_icons(
    items: Sequence[DesktopIconInfo], strategy: str = "grouped_columns"
) -> list[list[DesktopIconInfo]]:
    """按「系统 / 快捷方式 / 文件 / 文件夹」四组切开；非分区策略只有一组。"""
    ordered = sort_icons(items, strategy)
    if strategy != "grouped_columns":
        return [ordered] if ordered else []
    buckets: list[list[DesktopIconInfo]] = [[], [], [], []]
    for item in ordered:
        buckets[_rank(item)].append(item)
    return [bucket for bucket in buckets if bucket]


def column_break_indices(groups: Sequence[Sequence[DesktopIconInfo]]) -> set[int]:
    """每组第一项在整体序列里的下标，用于强制换列。"""
    breaks: set[int] = set()
    offset = 0
    for index, group in enumerate(groups):
        if index > 0 and offset > 0:
            breaks.add(offset)
        offset += len(group)
    return breaks


def grid_capacity(work_area: ScreenWorkArea) -> int:
    """工作区最多能摆多少个图标。"""
    return columns_available(work_area) * work_area.max_rows


def columns_available(work_area: ScreenWorkArea) -> int:
    span = work_area.right - work_area.start_x
    return max(1, span // max(1, work_area.cell_w))


def compute_compact_grid(
    items: Sequence[DesktopIconInfo],
    work_area: ScreenWorkArea,
    *,
    column_break_indices: set[int] | None = None,
) -> dict[str, tuple[int, int]]:
    """自上而下填满一列再换列（Windows 桌面的经典竖向优先）。

    超出工作区容量的图标**不参与排版**（宁可少排，也不把图标塞到任务栏底下）。
    """
    coords: dict[str, tuple[int, int]] = {}
    cols = columns_available(work_area)
    max_rows = work_area.max_rows
    col = 0
    row = 0

    for idx, item in enumerate(items):
        if column_break_indices and idx in column_break_indices and row > 0:
            col += 1
            row = 0
        if col >= cols:
            break  # 横向已经摆满，剩下的不动（不排到屏幕外）
        coords[item.name] = (
            work_area.start_x + col * work_area.cell_w,
            work_area.start_y + row * work_area.cell_h,
        )
        row += 1
        if row >= max_rows:
            row = 0
            col += 1
    return coords


# ---------------------------------------------------------------- 真实度量


def _user32():  # pragma: no cover - 只有真机路径会走
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.SystemParametersInfoW.argtypes = [
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        wintypes.UINT,
    ]
    user32.SystemParametersInfoW.restype = wintypes.BOOL
    return user32


def measure_work_area() -> ScreenWorkArea:  # pragma: no cover - 真机
    """读真实工作区（避让任务栏）与系统图标间距。取不到就用保守默认值。"""
    user32 = _user32()
    cell_w = int(user32.GetSystemMetrics(_SM_CXICONSPACING)) or iconpos.DEFAULT_CELL_W
    cell_h = int(user32.GetSystemMetrics(_SM_CYICONSPACING)) or iconpos.DEFAULT_CELL_H
    if cell_w <= 0:
        cell_w = iconpos.DEFAULT_CELL_W
    if cell_h <= 0:
        cell_h = iconpos.DEFAULT_CELL_H

    rect = wintypes.RECT()
    ok = user32.SystemParametersInfoW(_SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    if ok:
        return ScreenWorkArea(
            left=int(rect.left),
            top=int(rect.top),
            right=int(rect.right),
            bottom=int(rect.bottom),
            cell_w=cell_w,
            cell_h=cell_h,
        )
    return ScreenWorkArea(
        left=0,
        top=0,
        right=int(user32.GetSystemMetrics(0)) or 1920,
        bottom=int(user32.GetSystemMetrics(1)) or 1080,
        cell_w=cell_w,
        cell_h=cell_h,
    )


def collect_icons() -> list[DesktopIconInfo]:  # pragma: no cover - 真机
    """读出桌面上每个图标并判定身份（只读文件元数据，绝不读内容）。"""
    root = iconpos.desktop_root()
    out: list[DesktopIconInfo] = []
    for name, x, y in iconpos.iter_items():
        path = (root / name) if root else None
        exists = bool(path and path.exists())
        is_dir = bool(path and path.is_dir())
        ext = ""
        try:
            ext = Path(name).suffix.lower()
        except ValueError:
            ext = ""
        mtime = 0.0
        if exists and path is not None:
            try:
                mtime = float(path.stat().st_mtime)
            except OSError:
                mtime = 0.0
        out.append(
            DesktopIconInfo(
                name=name,
                current_x=int(x),
                current_y=int(y),
                is_special=not exists,
                is_shortcut=ext in _SHORTCUT_EXTS,
                is_directory=is_dir,
                ext=ext,
                mtime=mtime,
            )
        )
    return out


# ---------------------------------------------------------------- 执行与撤销


def apply_layout(
    strategy_id: str = "shortcuts_first",
    *,
    collect: Callable[[], list[DesktopIconInfo]] | None = None,
    measure: Callable[[], ScreenWorkArea] | None = None,
    snapshot: Callable[[], dict] | None = None,
    save: Callable[[dict, Path], Any] | None = None,
    get_autoarrange: Callable[[], bool] | None = None,
    set_autoarrange: Callable[[bool], Any] | None = None,
    make_writer: Callable[[], Callable[[str, int, int], Any]] | None = None,
    undo_path: str | Path | None = None,
) -> dict:
    """执行一次排版。顺序是死的：先备份、再关自动排列、最后写坐标。"""
    strategy_id = normalize_strategy(strategy_id)
    collect = collect or collect_icons
    measure = measure or measure_work_area
    snapshot = snapshot or (lambda: iconpos.snapshot_live())
    save = save or _save_undo
    get_autoarrange = get_autoarrange or iconpos.get_autoarrange
    set_autoarrange = set_autoarrange or iconpos.set_autoarrange
    make_writer = make_writer or iconpos.make_position_writer
    undo_path = Path(undo_path) if undo_path is not None else default_undo_path()

    errors: list[str] = []

    try:
        items = list(collect())
    except Exception as exc:  # noqa: BLE001
        return _fail(strategy_id, f"读取桌面图标失败：{exc}")

    if not items:
        return {
            "ok": True,
            "total": 0,
            "moved": 0,
            "skipped_overflow": 0,
            "strategy": strategy_id,
            "undo_available": False,
            "errors": [],
        }

    ordered = sort_icons(items, strategy_id)
    groups = group_icons(items, strategy_id)
    breaks = column_break_indices(groups)

    try:
        work_area = measure()
    except Exception as exc:  # noqa: BLE001
        work_area = ScreenWorkArea(0, 0, 1920, 1080, iconpos.DEFAULT_CELL_W, iconpos.DEFAULT_CELL_H)
        errors.append(f"读取工作区失败，改用默认分辨率：{exc}")

    coords = compute_compact_grid(ordered, work_area, column_break_indices=breaks)
    overflow = len(ordered) - len(coords)

    # ---- 红线：没成功保存撤销快照，绝不动坐标 ----
    try:
        payload = snapshot()
        save(payload, undo_path)
    except Exception as exc:  # noqa: BLE001
        return _fail(strategy_id, f"无法保存撤销快照，已放弃排版（未改动任何图标）：{exc}")

    try:
        set_autoarrange(False)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"关闭自动排列失败：{exc}")

    moved = 0
    try:
        writer = make_writer()
    except Exception as exc:  # noqa: BLE001
        return _fail(strategy_id, f"无法连接桌面图标控件：{exc}")

    for name, (x, y) in coords.items():
        try:
            writer(name, x, y)
            moved += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")

    if overflow > 0:
        errors.append(f"工作区放不下全部图标，{overflow} 个未移动（不会排到屏幕外）")

    return {
        "ok": moved > 0,
        "total": len(items),
        "moved": moved,
        "skipped_overflow": overflow,
        "strategy": strategy_id,
        "undo_available": True,
        "errors": errors,
    }


def undo_layout(
    *,
    undo_path: str | Path | None = None,
    write_position: Callable[[str, int, int], Any] | None = None,
    get_autoarrange: Callable[[], bool] | None = None,
    set_autoarrange: Callable[[bool], Any] | None = None,
    read_positions: Callable[[], dict[str, tuple[int, int]]] | None = None,
    make_writer: Callable[[], Callable[[str, int, int], Any]] | None = None,
    sleep: Callable[[float], Any] | None = None,
) -> dict:
    """撤销上一次排版：把坐标写回备份时的样子，并回读校验。"""
    path = Path(undo_path) if undo_path is not None else default_undo_path()
    snapshot = iconpos.load_snapshot(path)
    if snapshot is None:
        return {"ok": False, "restored": 0, "error": "找不到可撤销的排版记录（layout_undo.json 不存在或已损坏）"}

    writer = write_position
    if writer is None:
        writer = make_writer() if make_writer is not None else iconpos.make_position_writer()

    reader = read_positions if read_positions is not None else iconpos.read_positions_live
    try:
        current = list(reader().keys())
    except Exception:  # noqa: BLE001
        current = []

    result = iconpos.restore_positions(
        snapshot,
        current_names=current,
        write_position=writer,
        get_autoarrange=get_autoarrange or iconpos.get_autoarrange,
        set_autoarrange=set_autoarrange or iconpos.set_autoarrange,
        read_positions=reader,
        make_writer=make_writer or iconpos.make_position_writer,
        sleep=sleep or time.sleep,
    )
    return {
        "ok": bool(result.get("restored")) and result.get("verified") is not False,
        "restored": int(result.get("restored") or 0),
        "verified": result.get("verified"),
        "errors": list(result.get("errors") or []),
    }


def default_undo_path() -> Path:
    return Path(constants.DATA_DIR) / "layout_undo.json"


def _save_undo(payload: dict, path: Path) -> Path:  # pragma: no cover - 真机/临时文件
    """落盘撤销快照。只写我们自己的 data 目录，不碰用户任何文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(__import__("json").dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    if not path.exists():
        raise OSError(f"撤销快照写入后不存在: {path}")
    return path


def _fail(strategy_id: str, message: str) -> dict:
    return {
        "ok": False,
        "total": 0,
        "moved": 0,
        "skipped_overflow": 0,
        "strategy": strategy_id,
        "undo_available": False,
        "errors": [message],
    }
