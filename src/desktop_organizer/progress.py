"""进度事件：给前端显示的单一数据形状。

为什么单独一个模块：进度要同时被 scanner、executor、bridge 三方使用，
如果各自拼字典，前端迟早要写三套解析。这里只放数据与百分比算法，
没有任何 IO，因此可以放心在热循环里调用。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Stage = Literal["scan", "plan", "ai_analyzing", "apply", "rollback"]

STAGES: frozenset[str] = frozenset({"scan", "plan", "ai_analyzing", "apply", "rollback"})


@dataclass(frozen=True)
class ProgressEvent:
    """一次进度上报。

    ``percent`` 由 :meth:`create` 统一算出来，避免各处各写一遍四舍五入。
    """

    stage: Stage
    current: int
    total: int
    current_item: str
    percent: float
    message: str

    @staticmethod
    def create(
        stage: Stage,
        current: int,
        total: int,
        current_item: str = "",
        message: str = "",
    ) -> "ProgressEvent":
        if stage not in STAGES:
            raise ValueError(f"未知进度阶段: {stage}")
        total = max(0, int(total))
        current = max(0, int(current))
        if total <= 0:
            percent = 0.0
        else:
            percent = min(100.0, round(current / total * 100.0, 1))
        return ProgressEvent(
            stage=stage,
            current=current,
            total=total,
            current_item=current_item,
            percent=percent,
            message=message,
        )

    def to_dict(self) -> dict:
        return asdict(self)


def safe_report(cb, done: int, total: int, label: str = "") -> None:
    """调用进度回调，并把回调自己的异常吞掉。

    纪律：进度条坏了不能影响整理本身。这里没有 `logger`，因为失败不需要
    让用户知道——他看界面时，进度条卡住比"整理被中断"轻微得多。
    """
    if cb is None:
        return
    try:
        cb(done, total, label)
    except Exception:  # noqa: BLE001 - 见 docstring：前端异常不得影响业务
        pass
