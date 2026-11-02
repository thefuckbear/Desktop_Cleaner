"""分类器：扩展名 -> 类别 / 重要度 / 置信度。

纯函数：只读 item 与 store，不做任何文件 IO。
判定优先级（从高到低，先命中先返回）：
1. 用户改判偏好（store）      -> confidence 0.95，理由"沿用你的历史选择"
2. 规则引擎（内置 + 用户规则） -> 规则自带 confidence，rule_id 可解释
3. 扩展名明确映射              -> confidence 0.90
4. 文件名关键词                -> confidence 0.70
5. 兜底"其他"                  -> confidence 0.30
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .constants import IMPORTANCE_DIRS
from .model import FileItem, Proposal
from .rules import load_rules, match

if TYPE_CHECKING:  # 避免运行期循环导入
    from .store import PreferenceStore

# 明确映射：扩展名（小写、不含点）-> 类别。与 CATEGORIES 一一对应，兜底由"其他"承担。
EXTS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "图片": ("png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "ico", "heic"),
    "文档": ("doc", "docx", "txt", "md", "rtf", "odt"),
    "表格": ("xls", "xlsx", "csv", "ods"),
    "演示": ("ppt", "pptx", "odp"),
    "PDF": ("pdf",),
    "音视频": ("mp3", "wav", "flac", "aac", "mp4", "mkv", "avi", "mov", "wmv", "flv"),
    "压缩包": ("zip", "rar", "7z", "tar", "gz", "bz2"),
    "安装包": ("exe", "msi", "appx", "msix"),
    "代码": (
        "py", "js", "ts", "java", "c", "cpp", "cs", "go", "rs", "html", "css",
        "json", "xml", "yml", "yaml", "sql", "sh", "bat", "ps1",
    ),
    "快捷方式": ("lnk", "url"),
    "字体": ("ttf", "otf", "woff", "woff2"),
    "电子书": ("epub", "mobi", "azw3"),
}

EXT_CATEGORY: dict[str, str] = {
    "." + ext: category for category, exts in EXTS_BY_CATEGORY.items() for ext in exts
}

# 文件名关键词：只在扩展名无法判定时兜底（如无扩展名的"我的简历"）。
KEYWORDS: tuple[tuple[str, str], ...] = (
    ("截图", "图片"),
    ("screenshot", "图片"),
    ("壁纸", "图片"),
    ("wallpaper", "图片"),
    ("照片", "图片"),
    ("简历", "文档"),
    ("resume", "文档"),
    ("合同", "文档"),
    ("发票", "文档"),
    ("invoice", "文档"),
    ("报告", "文档"),
    ("report", "文档"),
    ("笔记", "文档"),
    ("账单", "表格"),
    ("报价", "表格"),
    ("预算", "表格"),
    ("汇报", "演示"),
    ("备份", "压缩包"),
    ("backup", "压缩包"),
    ("安装", "安装包"),
    ("setup", "安装包"),
)

# 判断"重要"的类别：近期改动且属于工作产出，才值得放进 重要/。
HIGH_VALUE_CATEGORIES = frozenset({"文档", "表格", "演示", "PDF", "代码"})

# 常用扩展名：一个月内仍在用的，放 常用/ 而不是 归档/。
COMMON_EXTS = frozenset(
    {
        ".doc", ".docx", ".txt", ".md", ".xls", ".xlsx", ".csv",
        ".ppt", ".pptx", ".pdf", ".jpg", ".jpeg", ".png", ".gif",
        ".mp4", ".zip", ".py", ".js", ".json",
    }
)

RECENT_DAYS = 7.0
MONTH_DAYS = 30.0
DAY_SECONDS = 86400.0

CONF_EXT = 0.90
CONF_KEYWORD = 0.70
CONF_FALLBACK = 0.30
CONF_LEARNED = 0.95


def _age_days(item: FileItem) -> float | None:
    if not item.mtime or item.mtime <= 0:
        return None
    import time

    return max(0.0, (time.time() - item.mtime) / DAY_SECONDS)


def _importance(item: FileItem, category: str) -> str:
    age = _age_days(item)
    if age is None:
        return "low"
    if category in HIGH_VALUE_CATEGORIES and age <= RECENT_DAYS:
        return "high"
    if (item.ext or "").lower() in COMMON_EXTS and age <= MONTH_DAYS:
        return "medium"
    return "low"


def _keyword_hit(name: str) -> tuple[str, str] | None:
    lowered = name.lower()
    for keyword, category in KEYWORDS:
        if keyword in lowered:
            return keyword, category
    return None


def _proposal(item: FileItem, category: str, importance: str, confidence: float, reasons: list[str], rule_id: str = "") -> Proposal:
    return Proposal(
        path=item.path,
        target_dir=f"{category}/{IMPORTANCE_DIRS[importance]}",
        category=category,
        importance=importance,
        confidence=confidence,
        reasons=reasons,
        rule_id=rule_id,
    )


def classify(item: FileItem, store: "PreferenceStore | None" = None) -> Proposal:
    """给出单条文件的放置建议。人对结果有最终否决权。"""
    if store is not None:
        learned = store.lookup(item)
        if learned is not None:
            learned.confidence = CONF_LEARNED
            if not learned.reasons:
                learned.reasons = ["沿用你的历史选择"]
            return learned

    hit = match(item, load_rules(store))
    if hit is not None:
        return _proposal(
            item,
            hit.target_category,
            hit.importance,
            hit.confidence,
            [f"命中规则 {hit.id}"],
            rule_id=hit.id,
        )

    category = EXT_CATEGORY.get((item.ext or "").lower())
    if category is not None:
        importance = _importance(item, category)
        return _proposal(
            item,
            category,
            importance,
            CONF_EXT,
            [f"扩展名 {item.ext} → {category}"],
        )

    keyword = _keyword_hit(item.name)
    if keyword is not None:
        word, keyword_category = keyword
        importance = _importance(item, keyword_category)
        return _proposal(
            item,
            keyword_category,
            importance,
            CONF_KEYWORD,
            [f"文件名含关键词「{word}」→ {keyword_category}"],
        )

    reason = f"未识别的扩展名 {item.ext}" if item.ext else "无扩展名且无关键词特征"
    return _proposal(item, "其他", "low", CONF_FALLBACK, [reason])
