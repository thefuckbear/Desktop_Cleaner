"""项目常量。除本文件外，任何模块不应硬编码这些值。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Desktop Organizer"
APP_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0"

# ---- 安全默认值：绝不允许任何模块把它改成 False 以外的语义 ----
DEFAULT_DRY_RUN = True

# 用户数据目录是否允许写入。本会话永远为 False；产品交付后由用户显式开启。
# 不暴露任何 CLI 开关，避免"一条命令就破防"。
ALLOW_USER_DIRS = False

# ---- 置信度分档（ai-strategy 与 ui 共用的唯一真相）----
CONFIDENCE_HIGH = 0.80      # 可直接一键采纳
CONFIDENCE_MEDIUM = 0.55    # 需人工确认
# < CONFIDENCE_MEDIUM: 低置信，默认归入 "其他"，不主动移动

# ---- 目录层级基线：一级按类别，二级按重要度 ----
IMPORTANCE_DIRS = {"high": "重要", "medium": "常用", "low": "归档"}
IMPORTANCE_ORDER = ("high", "medium", "low")

# ---- 运行期目录 ----
def resolve_project_root(
    *, frozen: bool, exe_path: Path | None, file_path: Path
) -> Path:
    """定位"可写根目录"。

    源码运行：``src/desktop_organizer/constants.py`` 往上两级 = 仓库根。
    打包运行：``__file__`` 在 PyInstaller 的解压临时目录（``_MEIxxxx``）里，
    拿它算根会把日志、偏好、写盘白名单全指向临时目录 —— 所以改用 exe 所在目录。
    """
    if frozen and exe_path is not None:
        return Path(exe_path).resolve().parent
    return Path(file_path).resolve().parents[2]


PROJECT_ROOT = resolve_project_root(
    frozen=bool(getattr(sys, "frozen", False)),
    exe_path=Path(sys.executable) if getattr(sys, "frozen", False) else None,
    file_path=Path(__file__),
)
SANDBOX_DIR = PROJECT_ROOT / "sandbox"
EVIDENCE_DIR = PROJECT_ROOT / "evidence"
LOG_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"

def user_home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())
