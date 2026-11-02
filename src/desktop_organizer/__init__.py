"""Desktop Organizer —— 个人自用的 Windows 桌面整理工具。

默认 dry-run；所有写操作必须经过 guard 判定；一切移动可回滚。
"""

from .constants import APP_NAME, APP_VERSION

__all__ = ["APP_NAME", "APP_VERSION"]
__version__ = APP_VERSION
