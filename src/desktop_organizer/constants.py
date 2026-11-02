"""项目常量。除本文件外，任何模块不应硬编码这些值。"""

from __future__ import annotations

import os
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
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_DIR = PROJECT_ROOT / "sandbox"
EVIDENCE_DIR = PROJECT_ROOT / "evidence"

def user_home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())
