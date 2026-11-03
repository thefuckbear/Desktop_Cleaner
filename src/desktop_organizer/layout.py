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
import os
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
    is_system: bool = False  # 系统命名空间图标（此电脑 / 回收站 / 网络 / 用户目录）


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


# ---------------------------------------------------------------- 组合排序键
#
# 单一策略不够用：用户想要的常常是「系统图标在最前 + 快捷方式次之 + 按类别分组」
# 这种叠加。所以策略拆成可多选的**排序键**，按用户勾选顺序依次作用，
# 前面的键优先、后面的键只在前面的键打平时起作用（稳定多趟排序）。

_SORT_KEYS: tuple[dict[str, str], ...] = (
    {
        "id": "system_first",
        "name": "系统图标优先",
        "desc": "此电脑 / 回收站 / 网络 / 用户目录 排最前，占住左上角",
    },
    {
        "id": "shortcuts_first",
        "name": "快捷方式优先",
        "desc": ".lnk / .url 排在普通文件与文件夹之前",
    },
    {
        "id": "by_type",
        "name": "按类型分组",
        "desc": "系统图标 → 快捷方式 → 文件 → 文件夹",
    },
    {
        "id": "by_category",
        "name": "按类别分组",
        "desc": "图片 / 文档 / 表格 / 视频…同类排在一起",
    },
    {
        "id": "by_time",
        "name": "按修改时间",
        "desc": "最近改过的排前面",
    },
    {
        "id": "by_name",
        "name": "按名称",
        "desc": "同一组内按名称升序（大小写不敏感）",
    },
)

_SORT_KEY_IDS = frozenset(item["id"] for item in _SORT_KEYS)
_DEFAULT_SORT_KEYS: tuple[str, ...] = ("system_first", "shortcuts_first", "by_name")


def sort_keys() -> list[dict[str, str]]:
    """给前端做多选框用的排序键清单（顺序即展示顺序）。"""
    return [dict(item) for item in _SORT_KEYS]


def normalize_sort_keys(keys: Sequence[str] | None) -> list[str]:
    """去掉不认识的和重复的；一个都不剩就用默认组合。"""
    if not keys:
        return list(_DEFAULT_SORT_KEYS)
    out: list[str] = []
    for key in keys:
        name = str(key).strip()
        if name in _SORT_KEY_IDS and name not in out:
            out.append(name)
    return out or list(_DEFAULT_SORT_KEYS)


def category_of(item: DesktopIconInfo) -> str:
    """按扩展名归到 13 个类别之一（和整理功能用同一张映射表）。"""
    if item.is_system:
        return "系统"
    if item.is_shortcut:
        return "快捷方式"
    if item.is_directory:
        return "文件夹"
    try:  # 延迟导入：classify 依赖 proposal 链路，顶层导入会绕回来
        from .classify import EXT_CATEGORY

        return EXT_CATEGORY.get(item.ext, "其他")
    except Exception:  # noqa: BLE001 - 分类表拿不到不该让排版失败
        return "其他"


def _type_rank(item: DesktopIconInfo) -> int:
    if item.is_system or item.is_special:
        return 0
    if item.is_shortcut:
        return 1
    if item.is_directory:
        return 3
    return 2


def sort_by_keys(
    items: Sequence[DesktopIconInfo], keys: Sequence[str] | None = None
) -> list[DesktopIconInfo]:
    """按「排序键组合」排序：前面的键优先，后面的键只在前面的键打平时决定次序。"""
    ordered = list(items)
    for key in reversed(normalize_sort_keys(keys)):
        if key == "system_first":
            # is_special 也算系统图标：桌面上没有对应磁盘文件，就是 shell 命名空间项
            # （此电脑 / 回收站 / 网络 / 用户目录）。两个标记不一致时宁可先排上去。
            ordered.sort(key=lambda i: 0 if (i.is_system or i.is_special) else 1)
        elif key == "shortcuts_first":
            ordered.sort(key=lambda i: 0 if i.is_shortcut else 1)
        elif key == "by_type":
            ordered.sort(key=_type_rank)
        elif key == "by_category":
            ordered.sort(key=category_of)
        elif key == "by_time":
            ordered.sort(key=lambda i: -float(i.mtime))
        elif key == "by_name":
            ordered.sort(key=_name_key)
    return ordered


_LEGACY_STRATEGY_IDS = frozenset({"shortcuts_first", "grouped_columns", "compact_time"})


def _keys_for_strategy(strategy_id: str) -> list[str]:
    """把老的单一策略翻译成排序键组合，保证旧调用与旧测试继续成立。"""
    # grouped_columns 也要带 system_first：分区看板的组序是按 _type_rank
    # 系统→快捷方式→文件→文件夹，和 shortcuts_first 是同一套秩序；
    # 少这一层就会出现「同一个桌面，两个策略给出不同首位」的怪现象。
    if strategy_id == "grouped_columns":
        return ["system_first", "by_type", "by_name"]
    if strategy_id == "compact_time":
        return ["system_first", "shortcuts_first", "by_time"]
    return ["system_first", "shortcuts_first", "by_name"]


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
    """按策略排序。未知策略回落到 shortcuts_first，绝不抛异常打断排版。

    `shortcuts_first` 既是老策略 id 又是新排序键 id，这里以**老策略**优先解释，
    否则单独传它时会丢掉"系统图标最前"这一层，行为与历史版本不一致。
    """
    if strategy in _LEGACY_STRATEGY_IDS:
        return sort_by_keys(items, _keys_for_strategy(strategy))
    if strategy in _SORT_KEY_IDS:
        return sort_by_keys(items, [strategy])
    return sort_by_keys(items, _keys_for_strategy("shortcuts_first"))


def _is_key_list(strategy: Any) -> bool:
    return isinstance(strategy, (list, tuple))


def group_icons(
    items: Sequence[DesktopIconInfo], strategy: str | Sequence[str] = "grouped_columns"
) -> list[list[DesktopIconInfo]]:
    """按「系统 / 快捷方式 / 文件 / 文件夹」四组切开；非分区策略只有一组。"""
    if isinstance(strategy, (list, tuple)):
        ordered = sort_by_keys(items, strategy)
        ranker = _type_rank
        grouped = False  # 分不分列由调用方的 group_columns 决定
    else:
        ordered = sort_icons(items, strategy)
        ranker = _rank
        grouped = strategy == "grouped_columns"
    if not grouped:
        return [ordered] if ordered else []
    buckets: list[list[DesktopIconInfo]] = [[], [], [], []]
    for item in ordered:
        buckets[ranker(item)].append(item)
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


def work_area_bounds(work_area: ScreenWorkArea) -> dict:
    """转成 iconpos.clamp_position 认的边界字典。

    单个字段就不做成 dict 字面量塞在两处：夹取逻辑只看这四个边和格距，
    多一份手写拷贝就多一处会走样的地方。
    """
    return {
        "left": work_area.left,
        "top": work_area.top,
        "right": work_area.right,
        "bottom": work_area.bottom,
        "cell_w": work_area.cell_w,
        "cell_h": work_area.cell_h,
    }


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


_MIN_STEP = 30
_MAX_STEP = 300


def _common_step(values: Sequence[int]) -> int | None:
    """一维坐标里最常见的相邻差。太小的差是误差、太大的是跨列/跨屏，都不算步长。"""
    ordered = sorted({int(v) for v in values})
    if len(ordered) < 2:
        return None
    diffs = [b - a for a, b in zip(ordered, ordered[1:])]
    usable = [d for d in diffs if _MIN_STEP <= d <= _MAX_STEP]
    if not usable:
        return None
    counts: dict[int, int] = {}
    for d in usable:
        counts[d] = counts.get(d, 0) + 1
    best = max(counts.values())
    # 并列时取较小的：宁可格子略小，也不要算大了让图标重叠
    return min(d for d, n in counts.items() if n == best)


def icon_step_from_positions(
    items: Sequence[DesktopIconInfo],
) -> tuple[int, int]:
    """从桌面上图标的真实间距推出网格步长。

    为什么不用系统 API：实测 `GetSystemMetrics(38/39)` 给的是 75/75，
    `LVM_GETITEMSPACING` 给的是 96/81，而真实步长是 **75/104**。
    按 75 当行距排版，新坐标会落在 104 网格的格间，被顺手对齐后两个图标抢同一格。
    桌面自己的坐标是唯一不会骗人的证据。
    """
    if not items:
        return iconpos.DEFAULT_CELL_W, iconpos.DEFAULT_CELL_H
    step_w = _common_step([it.current_x for it in items])
    step_h = _common_step([it.current_y for it in items])
    return (
        step_w if step_w else iconpos.DEFAULT_CELL_W,
        step_h if step_h else iconpos.DEFAULT_CELL_H,
    )


def measure_work_area(
    *,
    rect: tuple[int, int, int, int] | None = None,
    icons: Sequence[DesktopIconInfo] | None = None,
) -> ScreenWorkArea:
    """读真实工作区（避让任务栏），格距用图标实测间距。

    `rect` / `icons` 只在测试里注入；真机路径下走 SystemParametersInfoW。
    """
    cell_w, cell_h = icon_step_from_positions(icons or [])

    bounds = rect
    if bounds is None:  # pragma: no cover - 真机
        user32 = _user32()
        area = wintypes.RECT()
        if user32.SystemParametersInfoW(_SPI_GETWORKAREA, 0, ctypes.byref(area), 0):
            bounds = (int(area.left), int(area.top), int(area.right), int(area.bottom))
        else:
            bounds = (
                0,
                0,
                int(user32.GetSystemMetrics(0)) or 1920,
                int(user32.GetSystemMetrics(1)) or 1080,
            )

    left, top, right, bottom = (int(v) for v in bounds)
    return ScreenWorkArea(
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        cell_w=cell_w,
        cell_h=cell_h,
    )


def public_desktop_root() -> Path | None:
    """公共桌面目录（`C:\\Users\\Public\\Desktop`）。

    桌面其实是**两个**目录叠在一起：用户桌面 + 公共桌面。只查用户桌面的话，
    公共桌面上的快捷方式（很多安装器默认装到公共桌面）会被判成"壳命名空间
    项"，进而被 `system_first` 顶到最前面——用户看到的正是这个。
    """
    try:
        buf = ctypes.create_unicode_buffer(260)
        # CSIDL_COMMON_DESKTOPDIRECTORY = 0x0019
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0019, None, 0, buf) == 0:
            path = Path(buf.value)
            if path.is_dir():
                return path
    except Exception:  # noqa: BLE001
        pass
    public = os.environ.get("PUBLIC")
    if public:
        candidate = Path(public) / "Desktop"
        if candidate.is_dir():
            return candidate
    return None


def desktop_roots() -> list[Path]:
    """桌面涉及的所有目录：用户桌面在前，公共桌面在后（去重）。"""
    roots: list[Path] = [Path(iconpos.desktop_root())]
    pub = public_desktop_root()
    if pub is not None:
        seen = {os.path.normcase(str(p)) for p in roots}
        if os.path.normcase(str(pub)) not in seen:
            roots.append(pub)
    return roots


def _as_roots(root: str | Path | Sequence[str | Path] | None) -> list[Path]:
    if root is None:
        return []
    if isinstance(root, (str, Path)):
        return [Path(root)]
    return [Path(item) for item in root if item]


def resolve_icon_path(
    root: str | Path | Sequence[str | Path] | None, name: str
) -> Path | None:
    """把「桌面显示的图标名」还原成磁盘上的真实文件。

    关键坑一：Explorer 默认隐藏 `.lnk` / `.url` 后缀，桌面显示的是 `Addictive Drums 2`，
    磁盘上却是 `Addictive Drums 2.lnk`。只拿显示名去 `root/name` 找必然找不到。
    关键坑二：桌面是两个目录的叠加（用户 + 公共），只在其中一边找也会漏掉一半。
    """
    for base in _as_roots(root):
        for candidate in (base / name, base / f"{name}.lnk", base / f"{name}.url"):
            try:
                if candidate.exists():
                    return candidate
            except OSError:
                continue
    return None


# 桌面上没有对应文件的系统图标：中文系统与英文系统各一套
_SHELL_NAMES = frozenset(
    {
        "此电脑",
        "我的电脑",
        "计算机",
        "回收站",
        "网上邻居",
        "网络",
        "控制面板",
        "用户",
        "Administrator",
        "Public",
        "This PC",
        "Recycle Bin",
        "Network",
        "Control Panel",
        "Libraries",
        "库",
    }
)


def describe_icon(
    root: str | Path | Sequence[str | Path] | None, name: str, *, home_exists: bool = False
) -> DesktopIconInfo:
    """判定一个桌面图标的身份（只读元数据，绝不读文件内容）。

    `home_exists` 只给测试用：真机上"用户目录"图标的名字等于 `%USERPROFILE%` 的末段，
    但它在桌面上不是普通文件夹，而是 shell 的用户目录命名空间。
    """
    path = resolve_icon_path(root, name)
    exists = path is not None
    is_dir = False
    ext = ""
    mtime = 0.0
    if exists and path is not None:
        try:
            is_dir = path.is_dir()
        except OSError:
            is_dir = False
        ext = path.suffix.lower()
        try:
            mtime = float(path.stat().st_mtime)
        except OSError:
            mtime = 0.0
    else:
        try:
            ext = Path(name).suffix.lower()
        except ValueError:
            ext = ""

    is_user_folder = bool(home_exists or name == Path.home().name) and not exists
    is_system = (not exists and name in _SHELL_NAMES) or is_user_folder

    return DesktopIconInfo(
        name=name,
        current_x=0,
        current_y=0,
        is_special=not exists,
        is_shortcut=exists and ext in _SHORTCUT_EXTS,
        is_directory=is_dir,
        ext=ext,
        mtime=mtime,
        is_system=is_system,
    )


def collect_icons() -> list[DesktopIconInfo]:  # pragma: no cover - 真机
    """读出桌面上每个图标并判定身份（只读文件元数据，绝不读内容）。"""
    roots = desktop_roots()
    out: list[DesktopIconInfo] = []
    for name, x, y in iconpos.iter_items():
        info = describe_icon(roots, name)
        out.append(
            DesktopIconInfo(
                name=info.name,
                current_x=int(x),
                current_y=int(y),
                is_special=info.is_special,
                is_shortcut=info.is_shortcut,
                is_directory=info.is_directory,
                ext=info.ext,
                mtime=info.mtime,
                is_system=info.is_system,
            )
        )
    return out


# ---------------------------------------------------------------- 执行与撤销


def apply_layout(
    sort_keys: Sequence[str] | str = "shortcuts_first",
    *,
    group_columns: bool = False,
    collect: Callable[[], list[DesktopIconInfo]] | None = None,
    measure: Callable[[], ScreenWorkArea] | None = None,
    snapshot: Callable[[], dict] | None = None,
    save: Callable[[dict, Path], Any] | None = None,
    get_autoarrange: Callable[[], bool] | None = None,
    set_autoarrange: Callable[[bool], Any] | None = None,
    make_writer: Callable[[], Callable[[str, int, int], Any]] | None = None,
    read_positions: Callable[[], dict[str, tuple[int, int]]] | None = None,
    sleep: Callable[[float], Any] | None = None,
    attempts: int = 4,
    undo_path: str | Path | None = None,
) -> dict:
    """执行一次排版。顺序是死的：先备份、再关自动排列、最后写坐标。

    写完必须**回读校验**：Explorer 会在收到坐标后异步重排，写完就报成功等于撒谎。
    校验不过就重建 writer 重试（重排后索引会错位），重试用尽则如实报 misfit。
    """
    keys = normalize_sort_keys(
        _keys_for_strategy(sort_keys) if isinstance(sort_keys, str) else sort_keys
    )
    # strategy 字段是回执：传老的策略 id 或单个键 id 就原样回显，
    # 传组合键才拼成 "a+b+c"。认不出来的输入回落默认策略的名字——谎报
    # 「你选的那个生效了」比报回落更糟。
    if isinstance(sort_keys, str):
        if sort_keys in _LEGACY_STRATEGY_IDS or sort_keys in _SORT_KEY_IDS:
            label = sort_keys
        else:
            label = "shortcuts_first"
    else:
        label = "+".join(keys)
    collect = collect or collect_icons
    snapshot = snapshot or (lambda: iconpos.snapshot_live())
    save = save or _save_undo
    set_autoarrange = set_autoarrange or iconpos.set_autoarrange
    make_writer = make_writer or iconpos.make_position_writer
    # 回读校验是「可选加强」：调用方没给 reader 就只写一轮。
    # 不给默认值是有意的——默认去读真实桌面会让只做单元测试的调用方
    # 静默碰上真实 shell，反倒把测试变成环境依赖。
    reader = read_positions
    sleep = sleep or time.sleep
    undo_path = Path(undo_path) if undo_path is not None else default_undo_path()

    errors: list[str] = []

    try:
        items = list(collect())
    except Exception as exc:  # noqa: BLE001
        return _fail(label, f"读取桌面图标失败：{exc}")

    if not items:
        return {
            "ok": True,
            "total": 0,
            "moved": 0,
            "misfit": 0,
            "attempts_used": 0,
            "skipped_overflow": 0,
            "strategy": label,
            "undo_available": False,
            "errors": [],
        }

    ordered = sort_by_keys(items, keys)
    if group_columns:
        buckets: list[list[DesktopIconInfo]] = [[], [], [], []]
        for item in ordered:
            buckets[_type_rank(item)].append(item)
        groups = [bucket for bucket in buckets if bucket]
    else:
        groups = [ordered]
    breaks = column_break_indices(groups) if group_columns else set()

    try:
        # 不传 measure 时用刚收集到的图标算格距——省一次桌面枚举，也保证两处看到的是同一批
        work_area = measure() if measure else measure_work_area(icons=items)
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
        return _fail(label, f"无法保存撤销快照，已放弃排版（未改动任何图标）：{exc}")

    try:
        set_autoarrange(False)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"关闭自动排列失败：{exc}")

    moved = 0
    mislaid: list[str] = []
    # 没有 reader 就没有「是否到位」的判据，多写几轮只会重复同样的动作，
    # 所以轮数直接压到 1 轮；有 reader 时才值得为 Explorer 的异步重排重试。
    rounds = 1 if reader is None else max(1, int(attempts))
    used = 0
    for attempt in range(rounds):
        used = attempt + 1
        try:
            writer = make_writer()
        except Exception as exc:  # noqa: BLE001
            return _fail(label, f"无法连接桌面图标控件：{exc}")

        for name, (x, y) in coords.items():
            try:
                writer(name, x, y)
                if attempt == 0:
                    moved += 1
            except Exception as exc:  # noqa: BLE001
                if attempt == 0:
                    errors.append(f"{name}: {exc}")

        if reader is None:
            break

        # 回读：哪些没到位（Explorer 异步重排会把刚写的挪走）
        try:
            actual = reader()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"回读图标位置失败，无法校验：{exc}")
            mislaid = []
            break
        mislaid = [
            name
            for name, (x, y) in coords.items()
            # 按「落在哪一格」比，不按像素比：Explorer 会把 (12,12) 吸附成 (11,2)，
            # 像素永远对不上，但格子是同一格——按像素比会把 251 个全判成没到位。
            if name in actual
            and iconpos.cell_of(actual[name][0], actual[name][1], work_area.cell_w, work_area.cell_h)
            != iconpos.cell_of(x, y, work_area.cell_w, work_area.cell_h)
        ]
        if not mislaid:
            break
        if attempt + 1 < rounds:
            sleep(0.25)

    if mislaid:
        errors.append(
            f"{len(mislaid)} 个图标未就位（Explorer 会异步重排），已重试 {used} 轮："
            + "、".join(mislaid[:5])
            + ("…" if len(mislaid) > 5 else "")
        )

    if overflow > 0:
        errors.append(f"工作区放不下全部图标，{overflow} 个未移动（不会排到屏幕外）")

    return {
        "ok": moved > 0,
        "total": len(items),
        "moved": moved,
        "misfit": len(mislaid),
        "attempts_used": used,
        "skipped_overflow": overflow,
        "strategy": label,
        "undo_available": True,
        "errors": errors,
    }


SV_STRATEGY_IDS = frozenset({"shortcuts_first", "grouped_columns", "compact_time"})


def undo_layout(
    *,
    undo_path: str | Path | None = None,
    write_position: Callable[[str, int, int], Any] | None = None,
    get_autoarrange: Callable[[], bool] | None = None,
    set_autoarrange: Callable[[bool], Any] | None = None,
    read_positions: Callable[[], dict[str, tuple[int, int]]] | None = None,
    make_writer: Callable[[], Callable[[str, int, int], Any]] | None = None,
    sleep: Callable[[float], Any] | None = None,
    attempts: int = 3,
) -> dict:
    """撤销上一次排版：把坐标写回备份时的样子，并回读校验。

    为什么外面还要再来几轮：`iconpos.restore_positions` 内部那 10 轮只覆盖了
    「同一次写入被 Explorer 挪走」，而真机上出现过「整轮写完后 Shell 才统一重排」，
    于是第一轮校验必然失败、第二轮才稳。撤销是用户唯一的安全绳，宁可多等几秒也不能
    报个 False 让他以为没救回来。
    """
    path = Path(undo_path) if undo_path is not None else default_undo_path()
    snapshot = iconpos.load_snapshot(path)
    if snapshot is None:
        return {"ok": False, "restored": 0, "error": "找不到可撤销的排版记录（layout_undo.json 不存在或已损坏）"}

    reader = read_positions if read_positions is not None else iconpos.read_positions_live
    writer_factory = make_writer or iconpos.make_position_writer
    pause = sleep or time.sleep

    result: dict = {}
    rounds = max(1, int(attempts))
    for round_index in range(rounds):
        writer = write_position
        if writer is None:
            writer = writer_factory()
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
            make_writer=writer_factory,
            sleep=pause,
        )
        if result.get("verified") is not False:
            break
        if round_index + 1 < rounds:
            pause(0.6)

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
