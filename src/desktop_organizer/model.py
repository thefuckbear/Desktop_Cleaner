"""数据模型：全模块共享的契约（v0.1 冻结）。

任何模块之间传递数据只允许用这里的类型，禁止传裸 dict 或元组。
改动本文件视为契约变更，必须同步 docs/03-interface-contract.md 与契约测试。
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from typing import Any

# 一级类别。顺序即 UI 展示顺序，新增类别必须同时更新 classify 与测试夹具。
CATEGORIES: tuple[str, ...] = (
    "图片", "文档", "表格", "演示", "PDF", "音视频", "压缩包",
    "安装包", "代码", "快捷方式", "字体", "电子书", "其他",
)

IMPORTANCE_LEVELS: tuple[str, ...] = ("high", "medium", "low")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class FileItem:
    """扫描产出的单个条目。只描述事实，不含任何建议。"""

    path: str
    name: str
    ext: str = ""          # 小写、含前导点；无扩展名为 ""
    size: int = 0
    mtime: float = 0.0
    atime: float = 0.0
    is_dir: bool = False
    readonly: bool = False
    cloud_placeholder: bool = False   # OneDrive/坚果云等占位符，一律跳过不碰
    skipped_reason: str | None = None

    @property
    def skipped(self) -> bool:
        return self.skipped_reason is not None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class Proposal:
    """AI/规则引擎给出的放置建议。人是最终决策者。"""

    path: str
    target_dir: str        # 相对源根目录的层级路径，如 "图片/重要"
    category: str
    importance: str = "medium"
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    rule_id: str = ""      # 命中规则标识，改判学习用于定位

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class PlanAction:
    """一条待执行的原子动作。kind=move 之外的值一律不执行。"""

    action_id: str
    src: str
    dst: str
    kind: str = "move"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class Plan:
    plan_id: str
    root: str
    created_at: str
    actions: list[PlanAction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ExecResult:
    ok: bool = False
    applied: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    journal_id: str = ""
    rolled_back: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class GuardError(PermissionError):
    """路径守卫拒绝操作的统一异常。"""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"路径被安全守卫拒绝: {path} ({reason})")
        self.path = path
        self.reason = reason
