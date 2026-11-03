"""自由去向目录的校验。

用户可以在界面上把某个文件改到任意命名的子目录（比如「2026/专案组」），
所以这个名字必须当成不可信输入处理：它最终会拼成 ``root / 去向`` 再交给
executor 去写盘，一旦放过 ``..`` 或盘符，就等于把写盘白名单绕掉了。

这里只做「字符串层面」的合法性判断，真正的路径安全由 guard 在写盘前把关。
"""

from __future__ import annotations

import os

# Windows 文件名非法字符；冒号也一并拒绝，避免 "C:xxx" 这种盘符相对路径。
_BAD_CHARS = frozenset('<>:"|?*')
_MAX_LEN = 120


def validate(target_dir: str, root: str) -> tuple[bool, str]:
    """校验用户输入的去向子目录。

    返回 ``(ok, normalized_or_reason)``：ok 为 True 时第二个值是规范化后的
    相对路径（用系统分隔符），为 False 时是一句能直接展示给用户的原因。
    """
    raw = (target_dir or "").strip()
    if not raw:
        return False, "去向不能为空"
    if len(raw) > _MAX_LEN:
        return False, f"去向太长（超过 {_MAX_LEN} 个字符）"
    if any(ch in _BAD_CHARS for ch in raw):
        return False, '去向不能包含 < > : " | ? * 这些字符'
    if raw.startswith(("/", "\\")) or os.path.isabs(raw) or (len(raw) > 1 and raw[1] == ":"):
        return False, "去向必须是相对路径，不能是绝对路径或盘符路径"

    normalized = os.path.normpath(raw.replace("/", os.sep))
    parts = [part for part in normalized.split(os.sep) if part not in ("", ".")]
    if not parts:
        return False, "去向不能为空"
    if any(part == ".." for part in parts):
        return False, "去向不能包含 .. 上跳，不能越出整理目录"

    # 再用拼接后的绝对路径复核一次：防止依赖 normpath 的边角行为（保留设备名等）。
    absolute = os.path.abspath(os.path.join(root or ".", normalized))
    root_absolute = os.path.abspath(root or ".")
    if os.path.normcase(absolute) != os.path.normcase(root_absolute) and not os.path.normcase(
        absolute
    ).startswith(os.path.normcase(root_absolute) + os.sep):
        return False, "去向不能越出整理目录"

    return True, os.path.join(*parts)
