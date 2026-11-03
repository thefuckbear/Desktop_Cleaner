"""桌面格子占用验收：回滚后逐格比对，确认图标真的回去了。

坐标快照（iconpos）给出的是确定性数据；本模块额外提供一层"看画面"的验收：
把桌面按图标网格切成格子，只判断「这一格有没有图标」，不依赖 OCR、不联网、
不需要大模型——认字会错，认格子不会。

Pillow 在打包环境里可能不存在，所以只有在需要真正读图时才 import。
"""

from __future__ import annotations

from typing import Any, Sequence

from . import iconpos


def grid_occupancy(snapshot: dict) -> list[tuple[int, int]]:
    """快照里被占用的格子（列, 行），按列再按行排序。"""
    items: dict = snapshot.get("items") or {}
    cells = {(int(pos["col"]), int(pos["row"])) for pos in items.values()}
    return sorted(cells)


def compare_grids(before: dict, after: dict) -> dict:
    """逐格比对两张快照，并指出哪些名字换了格子。"""
    old = set(grid_occupancy(before))
    new = set(grid_occupancy(after))
    missing = sorted(old - new)
    extra = sorted(new - old)

    old_items: dict = before.get("items") or {}
    new_items: dict = after.get("items") or {}
    moved_names = [
        name
        for name in old_items
        if name in new_items
        and (
            old_items[name]["col"] != new_items[name]["col"]
            or old_items[name]["row"] != new_items[name]["row"]
        )
    ]
    return {
        "same": not missing and not extra and not moved_names,
        "missing_cells": missing,
        "extra_cells": extra,
        "moved_names": moved_names,
    }


def report_text(before: dict, after: dict, *, limit: int = 8) -> str:
    """给人看的一句话结论。"""
    diff = compare_grids(before, after)
    if diff["same"]:
        return f"格子占用一致（{(before.get('count') or 0)} 个图标全部回到原位）"

    parts = [f"未回到原位：{len(diff['moved_names'])} 个图标换了格子"]
    if diff["missing_cells"]:
        cells = "、".join(f"({c},{r})" for c, r in diff["missing_cells"][:limit])
        parts.append(f"缺失格子 {cells}")
    if diff["extra_cells"]:
        cells = "、".join(f"({c},{r})" for c, r in diff["extra_cells"][:limit])
        parts.append(f"多出格子 {cells}")
    if diff["moved_names"]:
        names = "、".join(diff["moved_names"][:limit])
        parts.append(f"挪位的图标 {names}")
    return "；".join(parts)


# ---------------------------------------------------------------- 图像层（可选）

def make_blank_image(*, cols: int, rows: int, cell_w: int = iconpos.DEFAULT_CELL_W,
                     cell_h: int = iconpos.DEFAULT_CELL_H) -> Any:
    """造一张全暗的图，测试与演示用。需要 Pillow。"""
    from PIL import Image

    return Image.new("RGB", (cols * cell_w, rows * cell_h), (0, 0, 0))


def paint_cell(img: Any, *, col: int, row: int, cell_w: int = iconpos.DEFAULT_CELL_W,
               cell_h: int = iconpos.DEFAULT_CELL_H, coverage: float = 0.05) -> None:
    """在指定格子中心画一小块亮色，模拟"这里有个图标"。

    coverage 是相对格子宽度的比例：默认画 5% 宽度的亮点。
    """
    size = max(1, int(cell_w * coverage))
    x0 = col * cell_w + cell_w // 2
    y0 = row * cell_h + cell_h // 2
    for dx in range(size):
        for dy in range(size):
            img.putpixel((x0 + dx, y0 + dy), (255, 255, 255))


def occupied_cells_from_image(img: Any, *, cell_w: int = iconpos.DEFAULT_CELL_W,
                              cell_h: int = iconpos.DEFAULT_CELL_H, cols: int = 0,
                              rows: int = 0, min_ratio: float = 0.0005) -> list[tuple[int, int]]:
    """从整屏截图里判断哪些格子有图标。

    做法：每格统计"非背景像素"占比。壁纸通常是渐变色，所以这里用**局部方差**而不是
    亮度绝对阈值——一块平坦的壁纸方差接近 0，有图标的格子因为线条与文字会明显更高。
    """
    width, height = img.size
    cols = cols or max(1, width // cell_w)
    rows = rows or max(1, height // cell_h)
    gray = img.convert("L")

    occupied: list[tuple[int, int]] = []
    for col in range(cols):
        for row in range(rows):
            x0, y0 = col * cell_w, row * cell_h
            x1, y1 = min(width, x0 + cell_w), min(height, y0 + cell_h)
            if x1 <= x0 or y1 <= y0:
                continue
            box = gray.crop((x0, y0, x1, y1))
            pixels = list(box.getdata())
            if not pixels:
                continue
            mean = sum(pixels) / len(pixels)
            variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
            if variance >= (min_ratio * 255 * 255):
                occupied.append((col, row))
    return occupied


def compare_occupancy(before_cells: Sequence[tuple[int, int]],
                      after_cells: Sequence[tuple[int, int]]) -> dict:
    old = set(before_cells)
    new = set(after_cells)
    return {
        "same": old == new,
        "missing_cells": sorted(old - new),
        "extra_cells": sorted(new - old),
    }
