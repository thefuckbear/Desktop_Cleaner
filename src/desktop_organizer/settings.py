"""用户级持久化设置。

目前只有一个开关：**是否允许写入用户数据目录**（桌面 / 文档 / 下载 …）。

为什么做成运行时设置而不是常量：`constants.ALLOW_USER_DIRS` 在打包后的 exe 里
改不动（要重新编译），而「整理真实桌面」恰恰是用户必须亲自拍板的事 ——
所以默认永远是 deny，只有用户在界面上显式打开、并且这个选择要跨进程记住。

安全底线：文件损坏、字段类型不对、读失败，一律退回 deny。绝不因为"读不出来"
就当成允许。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .constants import DATA_DIR

_KEY = "allow_user_dirs"


def settings_path(path: str | Path | None = None) -> Path:
    """设置文件位置。默认 ``<项目根>/data/settings.json``（已被 .gitignore 排除）。"""
    if path is not None:
        return Path(path)
    return DATA_DIR / "settings.json"


def _load(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def allow_user_dirs(path: str | Path | None = None) -> bool:
    """是否允许写用户数据目录。只有显式存了布尔 True 才算开。"""
    data = _load(settings_path(path))
    return data.get(_KEY) is True


def set_allow_user_dirs(value: bool, path: str | Path | None = None) -> bool:
    """持久化开关，返回落盘后的实际值。原子写：先写 .tmp 再 os.replace。"""
    target = settings_path(path)
    enabled = value is True
    data = _load(target)
    data[_KEY] = enabled

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return enabled


def as_dict(path: str | Path | None = None) -> dict[str, Any]:
    """给桥接层用的 JSON 安全快照。"""
    return {_KEY: allow_user_dirs(path)}
