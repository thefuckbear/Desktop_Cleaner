"""使用频次：从 Windows 的 UserAssist 里读出「这个程序被开过几次」。

为什么不看文件 atime：NTFS 默认把 atime 更新关了一半，而且「打开文件」和
「点击桌面图标」是两件事。为什么不看 Prefetch：那需要管理员权限，还得解析 pf 格式。

UserAssist 是 Explorer 自己记的「你点了几次」，键名用 ROT13 编码（微软的"防呆"，
不是加密），每个值 72 字节里第 4 字节开始是运行次数。全程只读，不改任何东西。

匹配策略：桌面图标的名字和实际程序名经常对不上（`Chrome` vs `Google Chrome`），
所以先按完整的 lnk 路径精确匹配，再退回"包含"匹配，最后按名字本身匹配。
"""

from __future__ import annotations

import codecs
import struct
import winreg
from pathlib import Path
from typing import Iterable

_USER_ASSIST = r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"
# 只有这两类子键里是「用户点开的程序」，其余是系统统计项
_APP_GUIDS = (
    "{CEBFF5CD-ACE2-4F4F-9178-9926F41749EA}",  # 可执行文件
    "{F4E57C4B-2036-45F0-A9AB-443BCFE33D9F}",  # 快捷方式 / UWP
)
# 这些不是用户程序，是 Explorer 自己的计数项
_NOISE = frozenset({"UEME_CTLSESSION", "UEME_CTLCUACount:ctor"})


def _rot13(text: str) -> str:
    return codecs.decode(text, "rot13")


def _run_count(blob: bytes) -> int:
    """72 字节结构里，第 4~8 字节是运行次数（Win7 之后的位置）。"""
    if len(blob) < 8:
        return 0
    return int(struct.unpack_from("<I", blob, 4)[0])


def read_raw(root=None) -> dict[str, int]:
    """把 UserAssist 读成 {解码后的名字: 最大运行次数}。只读，异常一律返回空。"""
    try:
        key = winreg.OpenKey(root or winreg.HKEY_CURRENT_USER, _USER_ASSIST)
    except OSError:
        return {}

    counts: dict[str, int] = {}
    try:
        total = winreg.QueryInfoKey(key)[0]
        for index in range(total):
            try:
                sub_name = winreg.EnumKey(key, index)
            except OSError:
                continue
            if sub_name not in _APP_GUIDS:
                continue
            try:
                sub = winreg.OpenKey(key, sub_name + r"\Count")
            except OSError:
                continue
            for value_index in range(winreg.QueryInfoKey(sub)[1]):
                try:
                    name, data, _ = winreg.EnumValue(sub, value_index)
                except OSError:
                    continue
                if not isinstance(data, (bytes, bytearray)):
                    continue
                count = _run_count(bytes(data))
                if count <= 0:
                    continue
                decoded = _rot13(name)
                if decoded in _NOISE:
                    continue
                # 同一个程序可能以 exe、lnk、AppUserModelID 三种形式各记一次，取最大
                counts[decoded] = max(counts.get(decoded, 0), count)
    except OSError:
        return {}
    finally:
        key.Close()
    return counts


def _basename(text: str) -> str:
    """从 `C:\\...\\Foo.lnk` 或 `{GUID}\\TaskBar\\Foo.lnk` 里取出 `Foo`。"""
    tail = text.replace("\\", "/").rsplit("/", 1)[-1]
    for suffix in (".lnk", ".exe", ".url"):
        if tail.lower().endswith(suffix):
            tail = tail[: -len(suffix)]
            break
    return tail.strip()


def build_index(raw: dict[str, int]) -> dict[str, int]:
    """把原始条目归一成 {小写基名: 次数}，顺便把 exe 名也收进来做别名。"""
    index: dict[str, int] = {}
    for name, count in raw.items():
        keys = {_basename(name).casefold()}
        # `Microsoft.Office.EXCEL.EXE.15` 这种也留一个 `excel` 别名
        parts = [p for p in name.replace("\\", "/").split("/") if p]
        for part in parts:
            for suffix in (".exe", ".lnk"):
                if part.lower().endswith(suffix):
                    keys.add(part[: -len(suffix)].casefold())
        if name.lower().endswith((".exe", ".15")):
            keys.add(_basename(name).casefold())
        for key in keys:
            if key:
                index[key] = max(index.get(key, 0), count)
    return index


def usage_of(name: str, index: dict[str, int]) -> int:
    """查一个桌面图标被点过几次：先精确，再包含。找不到就是 0。"""
    key = name.casefold().strip()
    if not key:
        return 0
    exact = index.get(key)
    if exact is not None:
        return exact
    # 包含匹配：桌面叫 `Chrome`，UserAssist 里是 `Google Chrome`
    best = 0
    for candidate, count in index.items():
        if len(candidate) >= 3 and (candidate in key or key in candidate):
            best = max(best, count)
    return best


def usage_map(names: Iterable[str], root=None) -> dict[str, int]:
    """给一批桌面图标名，返回 {名字: 次数}。读不到就给全 0，绝不抛。"""
    index = build_index(read_raw(root))
    return {name: usage_of(name, index) for name in names}
