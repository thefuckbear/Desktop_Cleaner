"""生成应用图标 icon.ico（蓝紫渐变 + 整理符号）。

只依赖 Pillow（本机已有）。一次性脚本，产物提交进仓库，运行期不再需要 Pillow。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

SCALE = 4  # 超采样倍数，边缘才不毛刺
SIZES = (16, 24, 32, 48, 64, 128, 256)

C1 = (109, 94, 252)   # #6d5efc 主紫
C2 = (168, 85, 247)   # #a855f7 次紫


def _gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            px[x, y] = (
                round(C1[0] + (C2[0] - C1[0]) * t),
                round(C1[1] + (C2[1] - C1[1]) * t),
                round(C1[2] + (C2[2] - C1[2]) * t),
            )
    return img


def render(px: int) -> Image.Image:
    s = px * SCALE
    base = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # 圆角方块底色
    radius = int(s * 0.235)
    grad = _gradient(s).convert("RGBA")
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=radius, fill=255)
    base.paste(grad, (0, 0), mask)

    draw = ImageDraw.Draw(base)
    white = (255, 255, 255, 255)
    soft = (255, 255, 255, 168)

    # 文件夹主体
    fx0, fy0 = int(s * 0.235), int(s * 0.325)
    fx1, fy1 = int(s * 0.765), int(s * 0.705)
    tab_h = int(s * 0.075)
    draw.rounded_rectangle((fx0, fy0 - tab_h, fx0 + int(s * 0.245), fy0 + tab_h), radius=int(s * 0.035), fill=white)
    draw.rounded_rectangle((fx0, fy0, fx1, fy1), radius=int(s * 0.055), fill=white)

    # 文件夹里的"整理条"——三条递减横线
    line_x0 = int(s * 0.305)
    widths = (0.375, 0.285, 0.195)
    ys = (0.435, 0.525, 0.615)
    thick = max(2, int(s * 0.052))
    for w, y in zip(widths, ys):
        draw.rounded_rectangle(
            (line_x0, int(s * y), line_x0 + int(s * w), int(s * y) + thick),
            radius=thick // 2,
            fill=(109, 94, 252, 255),
        )

    # 顶部高光，玻璃质感
    draw.rounded_rectangle(
        (int(s * 0.10), int(s * 0.055), int(s * 0.90), int(s * 0.50)),
        radius=int(s * 0.20),
        fill=None,
        outline=soft,
        width=max(1, int(s * 0.012)),
    )
    return base.resize((px, px), Image.LANCZOS)


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1] / "assets" / "icon.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    frames = [render(n) for n in SIZES]
    frames[-1].save(out, format="ICO", sizes=[(n, n) for n in SIZES])
    # 同时导出 PNG，便于 README / 快捷方式预览
    frames[-1].save(out.with_suffix(".png"), format="PNG")
    print(f"OK {out} ({out.stat().st_size} bytes) sizes={SIZES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
