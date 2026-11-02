"""让资源管理器重新读取目录/文件，使桌面图标按最新排序键重排。

背景：桌面开了「自动排列」时，图标位置 = 排序键的纯函数，但 Explorer 会缓存
一份图标位置（注册表 Bags\\1\\Desktop 的 IconLayouts）。文件被移走再移回后，
Explorer 有时会沿用缓存里的旧槽位，看起来就像「没回原位」。

``SHChangeNotify`` 是向 shell 广播「这个目录/文件变了，重新读」的官方途径，
比让用户手按 F5 更可靠，也不需要改动任何系统设置。
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

SHCNE_UPDATEDIR = 0x00001000
SHCNE_UPDATEITEM = 0x00002000
SHCNE_ASSOCCHANGED = 0x08000000

SHCNF_PATHW = 0x0005
SHCNF_FLUSH = 0x1000


def _call(event: int, path: Path) -> bool:
    """广播一条 shell 变更通知；失败返回 False，绝不抛异常打断主流程。"""
    try:
        # SHChangeNotify 在 shell32，签名：LONG ev, UINT flags, LPCVOID, LPCVOID
        func = ctypes.windll.shell32.SHChangeNotify
        func.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p]
        func.restype = None
        func(event, SHCNF_PATHW, str(path), None)
        return True
    except Exception:  # noqa: BLE001 - 通知失败不影响已经完成的文件操作
        return False


def _as_path(path: str | Path) -> Path | None:
    """把入参转成 Path；空串/非法类型一律返回 None（Path("") 会变成当前目录）。"""
    if isinstance(path, Path):
        return path
    if not isinstance(path, str) or not path.strip():
        return None
    try:
        return Path(path)
    except (TypeError, ValueError, OSError):
        return None


def notify_dir(path: str | Path) -> bool:
    """告诉 Explorer：这个目录的内容变了，请重新枚举并重排。"""
    target = _as_path(path)
    if target is None:
        return False
    try:
        if not target.is_dir():
            return False
    except OSError:
        return False
    return _call(SHCNE_UPDATEDIR, target)


def notify_item(path: str | Path) -> bool:
    """告诉 Explorer：这个具体文件变了（含时间戳），请重新读它的属性。"""
    target = _as_path(path)
    if target is None:
        return False
    try:
        if not target.exists():
            return False
    except OSError:
        return False
    return _call(SHCNE_UPDATEITEM, target)


def notify_after_rollback(root: str | Path, restored: list[str]) -> int:
    """回滚后统一广播：先逐项通知，再通知整个目录。返回成功条数。

    为什么两轮：逐项通知让 Explorer 重读被还原文件的时间戳；目录级通知让它
    重新枚举一次，把「临时出现的子文件夹消失」也反映出来。缺任何一轮，桌面
    都可能停在半旧半新的状态。
    """
    ok = 0
    for item in restored:
        if notify_item(item):
            ok += 1
    if notify_dir(root):
        ok += 1
    return ok


__all__ = [
    "notify_after_rollback",
    "notify_dir",
    "notify_item",
    "SHCNE_UPDATEDIR",
    "SHCNE_UPDATEITEM",
]
