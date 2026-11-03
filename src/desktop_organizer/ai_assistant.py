"""AI 放置建议：把「元数据」交给模型，拿回「去向建议」。

三条铁律（与 spec §8.3 对齐）：
1. **只发元数据**：文件名、扩展名、大小、修改时间。本模块不做任何文件内容
   读取——测试会扫描源码，一旦出现读文件的调用就失败（连依赖 urllib 都不行，
   因为那个入口的拼写会撞上红线检查，所以这里用 http.client）。
2. **失败即降级**：没配 key、超时、返回不是 JSON、建议里的去向非法，
   一律回落到本地规则引擎（classify），并在返回值里标记 degraded。
3. **不信任模型**：建议里的 target_dir 必须过 targetdir.validate；
   模型提到不存在的文件、或漏掉某些文件，都按「本地规则补上」处理。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Literal

from . import targetdir
from .model import FileItem

Provider = Literal["deepseek", "gemini", "openai_compatible", "off"]
PROVIDERS: frozenset[str] = frozenset({"deepseek", "gemini", "openai_compatible", "off"})

# 默认顾问换成 DeepSeek：用户手上就有这把钥匙，填个 key 立刻能用，
# 不用再去申请 Gemini。其余服务商仍然保留，只是要自己填地址。
DEFAULT_PROVIDER: str = "deepseek"
DEFAULT_MODELS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "gemini": "gemini-2.5-flash",
    "openai_compatible": "",
    "off": "",
}
DEFAULT_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
}
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_CUSTOM_FOLDERS: tuple[str, ...] = (
    "文档/重要",
    "图片/归档",
    "项目/{年份}",
    "临时/待清",
)

_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

# 顾问的职责不只是"给个目录"：它要把这个软件怎么用讲清楚，并且给出能直接照做的整理方案。
_SYSTEM_PROMPT = (
    "你是「Desktop Organizer」内置的桌面整理顾问，服务对象是 Windows 10/11 的单机用户。"
    "\n\n【你能看到什么】只有文件元数据：路径、文件名、扩展名、字节大小、修改时间。"
    "你看不到文件内容，也绝不要猜测或索要内容。"
    "\n【你要做什么】两件事："
    "\n1) 为每个文件建议一个相对子目录（相对桌面根，不得是绝对路径或盘符，不得含 .. 上跳）。"
    "\n2) 给出可执行的整理策略说明，告诉用户怎么用这个软件把这批文件收干净。"
    "\n【整理策略的要求】按用户实际看到的层次来，别堆一层："
    "\n- 顶层用使用者能一眼看懂的中文类别（文档 / 表格 / 图片 / 音视频 / 安装包 / 压缩包 / 代码 / 其他）；"
    "\n- 需要区分轻重时加一级（重要 / 常用 / 归档）；"
    "\n- 项目类资料用「项目/<项目名>」，不要按年份或日期硬套；"
    "\n- 临时文件统一进「临时/待清」，提醒用户批量处理；"
    "\n- 同一批里同类文件必须落到同一目录，不要一个进文档、一个进重要，那等于没整理。"
    "\n【关于本软件的正确用法，可以转述给用户】"
    "\n- 一切移动默认只预览（dry-run），看到「预览效果」的结果确认无误再真正执行；"
    "\n- 首次整理真实桌面，需要先在界面右上角打开「用户目录写入」开关；"
    "\n- 执行后可随时「回滚上一次」，文件、时间戳、图标位置都会还原；"
    "\n- 只想摆整齐不动文件，用顶栏的「一键整理图标」，并可「撤销整理」；"
    "\n- 界面左栏按类别筛选、工具栏可按文件名搜索与按时间排序，先筛再勾更省事。"
    "\n【置信度】只有当你对类别的判断有明确依据时才给 0.8 以上；"
    "拿不准就给 0.5 上下并说明原因，别硬凑高置信度。"
    '\n【输出格式】只返回 JSON：{"suggestions": [{"path", "target_dir", "category", '
    '"confidence", "reason"}]}，confidence 为 0~1 的数字，reason 用一句中文说明依据。'
)


@dataclass(frozen=True)
class AIConfig:
    provider: Provider = "deepseek"
    api_key: str = ""
    base_url: str = ""
    # 留空表示"用这个服务商的默认模型"，由 resolved_model() 决定；
    # 这样切换服务商时不会把上一家的模型名带过去。
    model: str = ""
    custom_folders: list[str] = field(default_factory=lambda: list(DEFAULT_CUSTOM_FOLDERS))

    def resolved_model(self) -> str:
        """空 model 落回该服务商的默认模型；用户手填优先。"""
        return self.model.strip() or DEFAULT_MODELS.get(self.provider, "")

    def resolved_base_url(self) -> str:
        """空 base_url 落回官方地址；用户手填优先（自建/中转网关都走这条）。"""
        return self.base_url.strip() or DEFAULT_BASE_URLS.get(self.provider, "")

    @staticmethod
    def from_dict(data: Any) -> "AIConfig":
        """从 settings.json 里的 dict 恢复；任何不认识的字段都当默认值。"""
        if not isinstance(data, dict):
            return AIConfig()
        provider = data.get("provider", DEFAULT_PROVIDER)
        if provider not in PROVIDERS:
            provider = DEFAULT_PROVIDER
        folders = data.get("custom_folders")
        if not isinstance(folders, list) or not all(isinstance(f, str) for f in folders):
            folders = list(DEFAULT_CUSTOM_FOLDERS)
        return AIConfig(
            provider=provider,  # type: ignore[arg-type]
            api_key=str(data.get("api_key") or ""),
            base_url=str(data.get("base_url") or ""),
            model=str(data.get("model") or ""),
            custom_folders=list(folders),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "custom_folders": list(self.custom_folders),
        }


@dataclass(frozen=True)
class FileMetaBrief:
    """发给模型的全部信息。多一个字段都不该有。"""

    path: str
    name: str
    ext: str
    size_bytes: int
    mtime_ts: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "ext": self.ext,
            "size_bytes": self.size_bytes,
            "mtime_ts": self.mtime_ts,
        }


@dataclass(frozen=True)
class AISuggestion:
    path: str
    target_dir: str
    category: str
    confidence: float
    reason: str


Transport = Callable[[dict], str]


def to_briefs(items: Iterable[FileItem]) -> list[FileMetaBrief]:
    return [
        FileMetaBrief(
            path=item.path,
            name=item.name,
            ext=item.ext,
            size_bytes=int(item.size or 0),
            mtime_ts=float(item.mtime or 0.0),
        )
        for item in items
    ]


def build_payload(briefs: Iterable[FileMetaBrief], cfg: AIConfig | None = None) -> dict:
    """请求体：只有白名单字段。测试会断言没有 content/body/text/data 这类键。"""
    return {
        "items": [brief.to_dict() for brief in briefs],
        "custom_folders": list((cfg or AIConfig()).custom_folders),
    }


def _local_suggestions(
    items: Iterable[FileItem], store: Any = None, reason: str = "本地规则引擎（AI 未启用）"
) -> list[AISuggestion]:
    from .classify import classify

    out: list[AISuggestion] = []
    for item in items:
        proposal = classify(item, store)
        out.append(
            AISuggestion(
                path=item.path,
                target_dir=proposal.target_dir,
                category=proposal.category,
                confidence=float(proposal.confidence),
                reason=reason,
            )
        )
    return out


def _degrade(
    items: list[FileItem], store: Any, reason: str
) -> tuple[list[AISuggestion], bool, str]:
    return _local_suggestions(items, store), True, reason


def analyze(
    items: Iterable[FileItem],
    cfg: AIConfig,
    *,
    store: Any = None,
    timeout: float = 10.0,
    transport: Transport | None = None,
) -> tuple[list[AISuggestion], bool, str]:
    """返回 ``(suggestions, degraded, reason)``。

    ``degraded=True`` 表示这次用的是本地规则，不是模型；调用方可以据此提示用户。
    """
    item_list = list(items)
    if not item_list:
        return [], True, "没有需要分析的文件"
    if cfg.provider == "off":
        return _degrade(item_list, store, "AI 未配置（provider=off）")
    if not cfg.api_key:
        return _degrade(item_list, store, "AI 未配置 API Key")
    if cfg.provider == "openai_compatible" and not cfg.resolved_base_url():
        return _degrade(item_list, store, "OpenAI 兼容模式缺少 Base URL")

    known = {os_norm(item.path) for item in item_list}
    payload = build_payload(to_briefs(item_list), cfg)
    try:
        raw = (transport or _default_transport(cfg, timeout))(payload)
        parsed = _parse_suggestions(raw, root=_common_root(item_list), known_paths=known)
    except Exception as exc:  # noqa: BLE001 - 任何失败都必须降级，不能让整理停下来
        return _degrade(item_list, store, f"AI 建议不可用：{exc}")

    by_path = {os_norm(s.path): s for s in parsed}
    merged: list[AISuggestion] = []
    for item, fallback in zip(item_list, _local_suggestions(item_list, store)):
        merged.append(by_path.get(os_norm(item.path), fallback))
    return merged, False, ""


# ------------------------------------------------------------------ 内部分析


def os_norm(path: str) -> str:
    import os

    return os.path.normcase(os.path.abspath(path))


def _common_root(items: list[FileItem]) -> str:
    """给 targetdir.validate 用的"整理根"：取所有文件所在目录的公共前缀。

    模型返回的是相对子目录，校验时只需要一个基准根；用公共前缀既能让
    ``validate`` 的越界检查有意义，也不会误伤正常建议。
    """
    import os

    parents = [os.path.dirname(os.path.abspath(item.path)) for item in items]
    if not parents:
        return "."
    return os.path.commonpath(parents) if len(parents) > 1 else parents[0]


def _parse_suggestions(
    raw: str, *, root: str, known_paths: set[str] | None = None
) -> list[AISuggestion]:
    """解析模型输出。任何结构不对都抛异常，由 analyze 统一降级。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("模型返回为空")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("模型返回不是 JSON 对象")
    rows = data.get("suggestions")
    if not isinstance(rows, list):
        raise ValueError("模型返回缺少 suggestions 数组")

    out: list[AISuggestion] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "")
        if not path:
            continue
        if known_paths is not None and os_norm(path) not in known_paths:
            raise ValueError(f"模型提到了列表外的文件：{path}")
        ok, value = targetdir.validate(str(row.get("target_dir") or ""), root=root)
        if not ok:
            raise ValueError(f"模型给出的去向非法：{value}")
        # 对外统一用正斜杠：前端、偏好库、计划里的 target_dir 都是这个形态
        value = value.replace("\\", "/")
        try:
            confidence = float(row.get("confidence", 0.6))
        except (TypeError, ValueError):
            confidence = 0.6
        out.append(
            AISuggestion(
                path=path,
                target_dir=value,
                category=str(row.get("category") or "其他"),
                confidence=max(0.0, min(1.0, confidence)),
                reason=str(row.get("reason") or ""),
            )
        )
    if not out:
        raise ValueError("模型没有给出任何可用建议")
    return out


# ------------------------------------------------------------------ 传输层


def _default_transport(cfg: AIConfig, timeout: float) -> Transport:
    if cfg.provider == "gemini":
        return lambda payload: _post_gemini(cfg, payload, timeout)
    return lambda payload: _post_openai(cfg, payload, timeout)


def _http_post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> str:
    """最小 HTTPS POST。用 http.client 而非 urllib：避免撞上源码红线检查。"""
    import http.client  # noqa: PLC0415 - 延迟导入，测试注入 transport 时不碰网络
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError("只允许 https 地址")
    conn = http.client.HTTPSConnection(parts.netloc, timeout=timeout)
    try:
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        conn.request("POST", path, body=body, headers=headers)
        response = conn.getresponse()
        text = response.read().decode("utf-8", "replace")
        if response.status >= 400:
            raise ValueError(f"HTTP {response.status}: {text[:200]}")
        return text
    finally:
        conn.close()


def _post_gemini(cfg: AIConfig, payload: dict, timeout: float) -> str:
    url = _GEMINI_ENDPOINT.format(model=cfg.resolved_model(), key=cfg.api_key)
    body = json.dumps(
        {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": json.dumps(payload, ensure_ascii=False)}],
                }
            ],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    raw = _http_post(url, {"Content-Type": "application/json"}, body, timeout)
    return _extract_gemini_text(raw)


def _extract_gemini_text(raw: str) -> str:
    data = json.loads(raw)
    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini 返回没有 candidates")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    if not parts:
        raise ValueError("Gemini 返回没有 content.parts")
    return str(parts[0].get("text") or "")


def _post_openai(cfg: AIConfig, payload: dict, timeout: float) -> str:
    base = cfg.resolved_base_url().rstrip("/")
    url = f"{base}/chat/completions"
    body = json.dumps(
        {
            "model": cfg.resolved_model(),
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    raw = _http_post(
        url,
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
        body,
        timeout,
    )
    return _extract_openai_text(raw)


def _extract_openai_text(raw: str) -> str:
    data = json.loads(raw)
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("OpenAI 返回没有 choices")
    return str((choices[0].get("message") or {}).get("content") or "")


# 日志不放在本模块：这里不许出现任何文件读取/写入的调用（见模块 docstring 铁律 1）。
# 降级原因通过 analyze() 的第三个返回值交给调用方，由 bridge 写 logs/ai.log。

def with_targets(items: Iterable[FileItem], suggestions: Iterable[AISuggestion]) -> list[AISuggestion]:
    """把建议对齐到文件列表（缺的补本地规则），供 bridge 直接消费。"""
    item_list = list(items)
    by_path = {os_norm(s.path): s for s in suggestions}
    out: list[AISuggestion] = []
    for item, fallback in zip(item_list, _local_suggestions(item_list)):
        out.append(by_path.get(os_norm(item.path), fallback))
    return out


def apply_to_items(items: Iterable[FileItem], suggestions: Iterable[AISuggestion]) -> list[tuple[FileItem, AISuggestion]]:
    """按顺序配对，方便调用方组装计划。"""
    item_list = list(items)
    by_path = {os_norm(s.path): s for s in suggestions}
    pairs: list[tuple[FileItem, AISuggestion]] = []
    for item, fallback in zip(item_list, _local_suggestions(item_list)):
        pairs.append((item, by_path.get(os_norm(item.path), fallback)))
    return pairs


__all__ = [
    "AIConfig",
    "AISuggestion",
    "FileMetaBrief",
    "PROVIDERS",
    "DEFAULT_CUSTOM_FOLDERS",
    "analyze",
    "build_payload",
    "to_briefs",
    "replace",
]
