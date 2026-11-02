"""路径安全守卫：代码层硬拦截。

判定顺序（v0.1 冻结，不可调换）：
1. 非绝对路径 / UNC / 盘符根 / 保留设备名  -> 拒绝
2. 命中系统目录黑名单                      -> 拒绝（无任何开关可解除）
3. 命中显式允许清单（项目根）              -> 允许（受控测试例外）
4. 命中用户数据目录且未显式放行            -> 拒绝
5. 其余                                    -> 允许

为什么允许清单排在用户目录之前：本项目的测试沙箱位于
%USERPROFILE%\\Desktop\\Projects\\Desktop_Cleaner\\sandbox，物理上在桌面之下。
只有项目根被登记为允许清单，真实桌面其余部分仍然全部拒绝。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .constants import ALLOW_USER_DIRS, PROJECT_ROOT
from .model import GuardError

_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)
}


def _norm(path: str | os.PathLike[str]) -> str:
    raw = os.path.expandvars(os.path.expanduser(str(path)))
    return os.path.normcase(os.path.abspath(raw))


def _under(child: str, parent: str) -> bool:
    if child == parent:
        return True
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:  # 不同盘符
        return False


def _system_forbidden() -> list[str]:
    drive = os.environ.get("SystemDrive", "C:")
    paths = [
        f"{drive}\\Windows",
        f"{drive}\\Program Files",
        f"{drive}\\Program Files (x86)",
        f"{drive}\\ProgramData",
        f"{drive}\\Recovery",
        f"{drive}\\$Recycle.Bin",
        f"{drive}\\System Volume Information",
        f"{drive}\\PerfLogs",
    ]
    for var in ("APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "SYSTEMROOT"):
        val = os.environ.get(var)
        if val and not _under(_norm(PROJECT_ROOT), _norm(val)):
            paths.append(val)
    return [_norm(p) for p in paths]


def _user_data_dirs() -> list[str]:
    home = os.environ.get("USERPROFILE")
    if not home:
        return []
    base = Path(home)
    names = ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music")
    dirs = [base / n for n in names]
    for onedrive in base.glob("OneDrive*"):
        if onedrive.is_dir():
            dirs.append(onedrive)
            dirs.extend(onedrive / n for n in names)
    return [_norm(p) for p in dirs]


def _allowlist() -> list[str]:
    return [_norm(PROJECT_ROOT)]


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str
    resolved: str
    tier: str  # allowlist | system | userdir | drive-root | ok


def _drive_roots() -> set[str]:
    roots = {f"{d}:\\" for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    return {r.lower() for r in roots}


def check_path(path: str | os.PathLike[str], *, allow_user_dirs: bool | None = None) -> GuardResult:
    """唯一判定入口。任何模块写盘前必须调用它或 assert_safe()。"""
    resolved = _norm(path)
    if allow_user_dirs is None:
        allow_user_dirs = ALLOW_USER_DIRS

    if not resolved:
        return GuardResult(False, "空路径", resolved, "system")
    if resolved.startswith("\\\\"):
        return GuardResult(False, "UNC 网络路径不受支持", resolved, "system")
    if not os.path.isabs(resolved):
        return GuardResult(False, "非绝对路径", resolved, "system")

    stem = Path(resolved).stem.upper()
    if stem in _RESERVED_NAMES:
        return GuardResult(False, "Windows 保留设备名", resolved, "system")
    if resolved.lower() in _drive_roots():
        return GuardResult(False, "磁盘根目录禁止写入", resolved, "drive-root")

    for allowed in _allowlist():
        if _under(resolved, allowed):
            return GuardResult(True, "命中项目允许清单", resolved, "allowlist")

    for bad in _system_forbidden():
        if _under(resolved, bad):
            return GuardResult(False, f"系统目录黑名单: {bad}", resolved, "system")

    for guarded in _user_data_dirs():
        if _under(resolved, guarded):
            if allow_user_dirs:
                return GuardResult(True, "用户目录已显式放行", resolved, "userdir")
            return GuardResult(False, f"用户数据目录默认拒绝: {guarded}", resolved, "userdir")

    return GuardResult(True, "通过", resolved, "ok")


def check_read_path(path: str | os.PathLike[str]) -> GuardResult:
    """只读通道：允许枚举用户目录（这是产品本身的功能），仍然拒绝系统目录。

    写入权限不得复用本函数——写盘一律走 check_path / assert_safe。
    """
    resolved = _norm(path)
    if not resolved or not os.path.isabs(resolved):
        return GuardResult(False, "非绝对路径", resolved, "system")
    if resolved.startswith("\\\\"):
        return GuardResult(False, "UNC 网络路径不受支持", resolved, "system")
    stem = Path(resolved).stem.upper()
    if stem in _RESERVED_NAMES:
        return GuardResult(False, "Windows 保留设备名", resolved, "system")
    for bad in _system_forbidden():
        if _under(resolved, bad):
            return GuardResult(False, f"系统目录禁止读取: {bad}", resolved, "system")
    return GuardResult(True, "只读通过", resolved, "read-ok")


def is_safe(path: str | os.PathLike[str], *, allow_user_dirs: bool | None = None) -> bool:
    return check_path(path, allow_user_dirs=allow_user_dirs).allowed


def can_read(path: str | os.PathLike[str]) -> bool:
    return check_read_path(path).allowed


def assert_readable(path: str | os.PathLike[str]) -> str:
    result = check_read_path(path)
    if not result.allowed:
        raise GuardError(str(path), result.reason)
    return result.resolved


def assert_safe(path: str | os.PathLike[str], *, allow_user_dirs: bool | None = None) -> str:
    result = check_path(path, allow_user_dirs=allow_user_dirs)
    if not result.allowed:
        raise GuardError(str(path), result.reason)
    return result.resolved
