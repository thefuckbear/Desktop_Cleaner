"""只读扫描器：把目录内容枚举成 FileItem 列表。

铁律：
- 本模块**只读**。除 guard 判定外不调用任何写 API（不 open 写、不 rename、不 chmod）。
- 扫描根走 guard.assert_readable（只读通道，允许真实桌面），与写盘用的
  assert_safe 严格分开，避免"扫描顺手拿到写权限"。
- 单个条目的权限/IO 错误只标注 skipped_reason，不中断整体扫描。
- 云占位符（OneDrive 等）只标注、不读取内容、后续也绝不移动。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import guard
from .model import FileItem

# ---- Windows 文件属性位（st_file_attributes）----
_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_SYSTEM = 0x4
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_ATTRIBUTE_OFFLINE = 0x1000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000

_CLOUD_ATTRS = _FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

# 系统盘根目录绝不能碰的固定文件（小写比较）
_PROTECTED_NAMES = frozenset({
    "pagefile.sys",
    "hiberfil.sys",
    "swapfile.sys",
    "desktop.ini",
    "thumbs.db",
    "ntuser.dat",
    "ntuser.dat.log",
    "$recycle.bin",
    "system volume information",
})

_MAX_PATH = 260


def _long(path: str) -> str:
    """按需加 \\\\?\\ 前缀以突破 260 字符限制。

    仅用于传给操作系统；FileItem.path 永远保存无前缀的常规路径，
    否则 guard 归一化后会对不上，也污染 UI 展示。
    """
    if len(path) < _MAX_PATH or path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def _skip_reason(name: str, attrs: int, *, is_dir: bool, is_reparse: bool) -> str | None:
    """判定一个条目该不该被跳过，返回原因或 None。

    顺序即优先级：云占位符最危险（一碰就可能触发下载/丢文件），
    其次重解析点（可能指向目录外），再按目录/受保护名/系统/隐藏。
    """
    if attrs & _CLOUD_ATTRS:
        return "cloud_placeholder"
    if is_reparse:
        return "reparse_point"
    if is_dir:
        return "directory"
    if name.lower() in _PROTECTED_NAMES:
        return "protected_name"
    if attrs & _FILE_ATTRIBUTE_SYSTEM:
        return "system"
    if attrs & _FILE_ATTRIBUTE_HIDDEN:
        return "hidden"
    return None


@dataclass(frozen=True)
class _Entry:
    name: str
    path: str
    is_dir: bool
    is_reparse: bool
    st: os.stat_result | None = None
    error: str | None = None


def _read_entry(display_parent: str, entry: os.DirEntry, *, follow_symlinks: bool) -> _Entry:
    display_path = os.path.join(display_parent, entry.name)
    try:
        is_reparse = entry.is_symlink() or bool(
            getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
            & _FILE_ATTRIBUTE_REPARSE_POINT
        )
    except OSError:
        is_reparse = entry.is_symlink()
    try:
        st = entry.stat(follow_symlinks=follow_symlinks)
    except PermissionError as exc:
        return _Entry(entry.name, display_path, entry.is_dir(follow_symlinks=False),
                      is_reparse, None, f"permission_denied:{exc}")
    except OSError as exc:
        return _Entry(entry.name, display_path, entry.is_dir(follow_symlinks=False),
                      is_reparse, None, f"error:{exc.__class__.__name__}")
    return _Entry(entry.name, display_path, entry.is_dir(follow_symlinks=False), is_reparse, st)


def _to_item(entry: _Entry, attrs: int) -> FileItem:
    st = entry.st
    # 读取失败优先：读不到 stat 就谈不上属性判定，直接标注错误原因。
    # 对外值按契约收敛为两种：permission_denied / error:<类型名>，
    # 原始 OSError 细节留在 _read_entry 的阶段，避免下游被迫解析自由文本。
    if entry.error:
        reason = "permission_denied" if entry.error.startswith("permission_denied") else entry.error
    else:
        reason = _skip_reason(entry.name, attrs, is_dir=entry.is_dir, is_reparse=entry.is_reparse)
    return FileItem(
        path=entry.path,
        name=entry.name,
        ext=os.path.splitext(entry.name)[1].lower(),
        size=getattr(st, "st_size", 0) if st else 0,
        mtime=getattr(st, "st_mtime", 0.0) if st else 0.0,
        atime=getattr(st, "st_atime", 0.0) if st else 0.0,
        is_dir=entry.is_dir,
        readonly=bool(getattr(st, "st_mode", 0) and not os.access(_long(entry.path), os.W_OK)),
        cloud_placeholder=bool(attrs & _CLOUD_ATTRS),
        skipped_reason=reason,
    )


def scan(
    root: str,
    *,
    max_depth: int = 1,
    follow_symlinks: bool = False,
) -> list[FileItem]:
    """只读扫描 root，返回按 name 稳定排序的 FileItem 列表。

    max_depth：1 = 只看根目录一层；2 = 再看一层子目录；以此类推。
    目录条目本身会出现在结果里（is_dir=True, skipped_reason="directory"），
    交给上层决定是否展示，扫描器不擅自丢数据。
    """
    guard.assert_readable(root)
    if max_depth < 1:
        raise ValueError("max_depth 必须 >= 1")

    items: list[FileItem] = []
    # 显式栈代替递归，深度可控且不受 Python 递归上限影响。
    stack: list[tuple[str, int]] = [(os.path.abspath(root), 1)]
    while stack:
        current, depth = stack.pop()
        try:
            with os.scandir(_long(current)) as it:
                entries = [_read_entry(current, e, follow_symlinks=follow_symlinks) for e in it]
        except PermissionError:
            if depth == 1:
                raise
            continue
        except OSError:
            if depth == 1:
                raise
            continue

        for entry in entries:
            attrs = getattr(entry.st, "st_file_attributes", 0) if entry.st else 0
            items.append(_to_item(entry, attrs))
            if (entry.is_dir and not entry.is_reparse and entry.error is None
                    and depth < max_depth):
                stack.append((entry.path, depth + 1))

    items.sort(key=lambda i: (i.name.casefold(), i.name))
    return items
