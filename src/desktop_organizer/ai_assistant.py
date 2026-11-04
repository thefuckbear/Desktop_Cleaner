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
import os
import re
import time
import uuid
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
    """请求体：只有白名单字段。测试会断言没有 content/body/text/data 这类键。

    带上 ``model`` 是为了让"实际用了哪个模型"在传输层就能被看见：
    模型名填错时，只有在这里留痕，测试和日志才说得清发出去的是谁。
    """
    conf = cfg or AIConfig()
    return {
        "model": conf.resolved_model(),
        "items": [brief.to_dict() for brief in briefs],
        "custom_folders": list(conf.custom_folders),
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
    timeout: float = 30.0,
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
    if _looks_like_relay_key(cfg):
        return _degrade(
            item_list,
            store,
            "这把 Key 不像 "
            f"{cfg.provider} 官方格式（官方以 sk- 开头），更像是第三方中转站的 Key。"
            "请在该服务商的 Base URL 里填写中转站地址（例如 https://your-relay.com/v1），"
            "否则请求会被发往官方地址并必然被拒",
        )

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


_ILLEGAL_CHARS = '<>:"|?*'
_ILLEGAL_MAP = {ch: "_" for ch in _ILLEGAL_CHARS}
_ABSOLUTE_PREFIX = re.compile(r"^(?:[A-Za-z]:|[/\\])")


def sanitize_target(target: str) -> str:
    """把模型给的去向修成 Windows 合法的相对路径。

    模型常常把分类原因写进去向里（`文档: 重要`、`图片|归档`）。这类路径在 Windows
    上建不出来，但**错的是分隔符不是意图**——整批降级等于让用户白等一次调用。

    注意：绝对路径与盘符开头的**原样放行**，交给 targetdir 去拒绝。如果先洗一遍，
    `C:\\Windows` 会被洗成 `C_/Windows` 这种"合法的相对路径"，等于把用户想逃出
    桌面目录的意图洗白了——宁可让校验器明确拒掉。
    """
    text = (target or "").strip().replace("\\", "/")
    if not text or _ABSOLUTE_PREFIX.match(text):
        return text
    parts: list[str] = []
    for chunk in text.split("/"):
        cleaned = "".join(_ILLEGAL_MAP.get(ch, ch) for ch in chunk)
        cleaned = re.sub(r"[\s_]*_[\s_]*", "_", cleaned.strip())  # 把 "文档_ 重要" 收成 "文档_重要"
        cleaned = cleaned.strip().strip(".")
        if cleaned:
            parts.append(cleaned)
    return "/".join(parts)


_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)


def _strip_fence(text: str) -> str:
    """剥掉 ```` ```json ```` 围栏。

    中转站上不少模型即便收到"只返回 JSON"也会包一层 markdown 代码块；
    为此整批降级太贵了——真正要的是里面的 JSON。
    """
    match = _FENCE.match(text or "")
    return match.group(1).strip() if match else text


def _parse_suggestions(
    raw: str, *, root: str, known_paths: set[str] | None = None
) -> list[AISuggestion]:
    """解析模型输出。任何结构不对都抛异常，由 analyze 统一降级。"""
    text = _strip_fence((raw or "").strip())
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
        ok, value = targetdir.validate(sanitize_target(str(row.get("target_dir") or "")), root=root)
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

# opencode go 这类网关要求带一个会话标识，缺了直接 400 MissingSessionID。
# 同一进程内固定一个：换 ID 对服务端是噪声，对日志是干扰；官方 API 会忽略未知头。
_SESSION_ID = uuid.uuid4().hex
_SESSION_HEADER = "x-opencode-session"

# 版本段判定：/v1、/v2、/v1.2 结尾都算"已经有了，别再叠"
_VERSION_TAIL = re.compile(r"/v\d+(?:\.\d+)?$", re.IGNORECASE)

# 官方 key 形态：DeepSeek/OpenAI 都是 sk- 开头
_OFFICIAL_KEY_PREFIX = re.compile(r"^sk-[A-Za-z0-9]", re.IGNORECASE)
# 中转站常见形态：<厂商>_sk_<随机>，如 opencode go 的 oc_sk_xxx。
# 只认"带厂商前缀的 sk"，因为"不是 sk- 开头"的证据太弱——用户可能用别的合法格式。
_RELAY_KEY_PREFIX = re.compile(r"^[A-Za-z]{2,}_sk_", re.IGNORECASE)
_OFFICIAL_PROVIDERS = frozenset({"deepseek"})


def _is_official_base(base: str) -> bool:
    """判断是不是官方地址——只有官方才保证认识 response_format 这类扩展参数。"""
    host = (base or "").strip().lower()
    for official in DEFAULT_BASE_URLS.values():
        if official and host.startswith(official.lower()):
            return True
    return False


def _looks_like_relay_key(cfg: AIConfig) -> bool:
    """官方 provider + 没填 Base URL + key 是"厂商前缀 + _sk_"形态 => 这把 key 属于中转站。

    这时若照旧打到官方地址，必然 401，而 401 的文案会让人去查 key——
    实际上该查的是地址。所以提前拦下来，直接说清该改哪里。
    只认强证据（`oc_sk_` 这种带厂商前缀的形态），不拿"没写 sk-"当理由。
    """
    if cfg.provider not in _OFFICIAL_PROVIDERS:
        return False
    if (cfg.base_url or "").strip():
        return False
    if _OFFICIAL_KEY_PREFIX.match(cfg.api_key or ""):
        return False
    return bool(_RELAY_KEY_PREFIX.match(cfg.api_key or ""))


def _bases_to_try(base: str) -> list[str]:
    """用户填的 base 要不要补 /v1：能自己试就别让人猜。"""
    base = (base or "").strip().rstrip("/")
    if not base:
        return []
    if _VERSION_TAIL.search(base):
        return [base]
    return [base, f"{base}/v1"]


def _openai_endpoints(base: str) -> list[str]:
    """候选 chat/completions 地址，按"用户怎么填的可能性"排序。"""
    return [f"{b}/chat/completions" for b in _bases_to_try(base)]


def _openai_headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        _SESSION_HEADER: _SESSION_ID,
    }


def _default_transport(cfg: AIConfig, timeout: float) -> Transport:
    if cfg.provider == "gemini":
        return lambda payload: _post_gemini(cfg, payload, timeout)
    return lambda payload: _post_openai(cfg, payload, timeout)


def _proxy_from_env() -> str:
    """找本机代理：先环境变量，再 Windows 系统代理。找不到返回空串。

    http.client 不像 requests 那样自动读系统代理，而本机直连境外 API 会超时
    （实测 github 直连 21 秒失败、走代理 3 秒成功）。所以这里补一层：
    环境变量优先，其次读注册表里的 ProxyEnable/ProxyServer。
    """
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value.split("://", 1)[-1]
    if os.name != "nt":
        return ""
    try:
        import winreg  # noqa: PLC0415 - 只有 Windows 才需要

        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
            if not enabled:
                return ""
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "")
    except (OSError, ValueError, ImportError):
        return ""
    # 形如 "127.0.0.1:7897" 或 "http=1.2.3.4:80;https=5.6.7.8:443"
    for chunk in server.split(";"):
        if "=" in chunk:
            scheme, _, rest = chunk.partition("=")
            if scheme.strip().lower() in ("https", "http"):
                return rest.strip()
        elif chunk.strip():
            return chunk.strip()
    return ""


def _http_request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> tuple[int, str]:
    """最小 HTTPS 请求，返回 ``(状态码, 正文)``。

    这里**不把 4xx 当异常抛**：调用方要靠状态码决定"这个端点不对，换下一个"
    还是"key/地址配错了，别再试"。异常只用于真正的传输失败（连不上、超时）。
    用 http.client 而非 urllib：避免撞上源码红线检查。
    """
    import http.client  # noqa: PLC0415 - 延迟导入，测试注入 transport 时不碰网络
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError("只允许 https 地址")
    proxy = _proxy_from_env()
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    try:
        if proxy:
            host, _, port = proxy.rpartition(":")
            conn = http.client.HTTPSConnection(host or proxy, int(port or 80), timeout=timeout)
            conn.set_tunnel(parts.netloc, 443)
        else:
            conn = http.client.HTTPSConnection(parts.netloc, timeout=timeout)
    except (OSError, ValueError) as exc:
        raise ValueError(f"代理地址不可用（{proxy}）：{exc}") from exc
    try:
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        text = response.read().decode("utf-8", "replace")
        return response.status, text
    except TimeoutError as exc:
        how = f"经由代理 {proxy}" if proxy else "直连（未检测到代理）"
        raise ValueError(f"请求超时（{timeout:.0f} 秒，{how}）。网络慢或代理不通，可调大超时再试") from exc
    finally:
        conn.close()


def _http_post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> str:
    """POST 并在非 2xx 时抛错（老接口，单端点场景仍可用）。"""
    status, text = _http_request("POST", url, headers, body, timeout)
    if status >= 400:
        raise ValueError(_explain_status(status, text, url))
    return text


def _explain_status(status: int, text: str, url: str) -> str:
    """把 HTTP 状态翻成"用户能据此改配置"的话。

    401 的旧文案一口咬定"Key 无效"——当中转 key 被发去官网时，这句
    把"地址配错了"伪装成"key 坏了"，是这次排查绕远的直接原因。
    """
    snippet = (text or "").strip()[:200]
    if status in (401, 403):
        return (
            f"该地址不接受这把 Key（HTTP {status}）：{url}\n"
            "若是第三方中转站的 Key，请确认 Base URL 填的是中转站地址而不是服务商官网；"
            "若地址无误，再去服务商后台核对 Key 是否过期或被停用"
        )
    if status == 400 and "MissingSessionID" in snippet:
        return (
            f"服务端要求会话标识（HTTP 400）：{url}\n"
            f"已自动附带 {_SESSION_HEADER} 请求头；仍报此错说明该网关用别的头名，"
            "可把这段报文反馈给开发者"
        )
    return f"HTTP {status}：{url}\n{snippet}"


def probe_endpoint(
    base_url: str = "",
    api_key: str = "",
    *,
    timeout: float = 20.0,
    getter: Callable[[str, dict[str, str], float], tuple[int, str]] | None = None,
) -> dict[str, Any]:
    """探一次 ``/models``，把可用 base 与模型列表拿回来。

    这是「测试连接」按钮的后端：填不填 /v1 由它试出来，试中哪个就回填哪个。
    任何失败都写进返回值，不抛——按钮点了没反应比报错更糟。
    """
    bases = _bases_to_try(base_url)
    if not bases:
        return {"ok": False, "base_url_used": "", "models": [], "error": "缺少 Base URL", "tried": []}
    do_get = getter or (lambda url, headers, t: _http_request("GET", url, headers, None, t))
    headers = _openai_headers(api_key)
    tried: list[dict[str, Any]] = []
    for base in bases:
        url = f"{base}/models"
        try:
            status, text = do_get(url, headers, timeout)
        except Exception as exc:  # noqa: BLE001 - 探测失败只能回报，不能把界面打挂
            tried.append({"url": url, "status": "error", "detail": str(exc)[:160]})
            continue
        tried.append({"url": url, "status": status})
        if status >= 400:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        rows = data.get("data") if isinstance(data, dict) else None
        ids = [
            str(row.get("id"))
            for row in (rows or [])
            if isinstance(row, dict) and row.get("id")
        ]
        return {"ok": True, "base_url_used": base, "models": ids, "error": "", "tried": tried}
    last = tried[-1] if tried else {}
    return {
        "ok": False,
        "base_url_used": "",
        "models": [],
        "error": _explain_status(
            int(last.get("status") or 0), "", str(last.get("url") or base_url)
        ),
        "tried": tried,
    }


# ------------------------------------------------- 模型清单：纠正 + 缓存 + 脱敏

# 5 分钟。分析前要校验模型名，但模型清单不该让每次分析都多等一个来回。
MODEL_CACHE_TTL = 300.0
_MODEL_CACHE: dict[str, tuple[float, list[str]]] = {}


def clear_model_cache() -> None:
    """清空模型清单缓存（测试与"换了 key 想立刻重拉"时用）。"""
    _MODEL_CACHE.clear()


def _parse_model_ids(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    rows = data.get("data") if isinstance(data, dict) else None
    return [
        str(row.get("id")) for row in (rows or []) if isinstance(row, dict) and row.get("id")
    ]


def list_models(
    base_url: str = "",
    api_key: str = "",
    *,
    timeout: float = 20.0,
    getter: Callable[[str, dict[str, str], float], tuple[int, str]] | None = None,
    now: Callable[[], float] | None = None,
) -> list[str]:
    """拉网关的模型清单，5 分钟内复用。拿不到就返回空列表，绝不抛。

    空列表的语义是"问不出来"，调用方据此**不要**擅自改模型名——
    离线、网关没有 /models、401 都会走到这里，此时改名字只是瞎猜。
    """
    cache_key = (base_url or "").strip().rstrip("/")
    if not cache_key:
        return []
    clock = now or time.monotonic
    t = clock()
    hit = _MODEL_CACHE.get(cache_key)
    if hit and t - hit[0] < MODEL_CACHE_TTL:
        return list(hit[1])

    do_get = getter or (lambda url, headers, tm: _http_request("GET", url, headers, None, tm))
    headers = _openai_headers(api_key)
    for base in _bases_to_try(base_url):
        try:
            status, text = do_get(f"{base}/models", headers, timeout)
        except Exception:  # noqa: BLE001 - 网络抖一下不该把分析整条拦死
            continue
        if status >= 400:
            continue
        ids = _parse_model_ids(text)
        if ids:
            _MODEL_CACHE[cache_key] = (t, ids)
            return list(ids)
    return []


def _model_tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[-_.\s]+", (name or "").lower()) if t}


def pick_model(want: str, available: Iterable[str]) -> tuple[str, str]:
    """在网关真实清单里挑一个最接近 ``want`` 的模型，返回 ``(模型名, 给用户的说明)``。

    名字对得上就原样返回且说明为空（别多嘴）；对不上就找词重叠最多的那个，
    并把"你填的没有，我换成了什么"讲清楚——悄悄换掉模型比报错更难排查。
    ``available`` 为空表示"问不出清单"，此时**原样返回**，不擅自改用户的配置。
    """
    names = [str(n) for n in (available or []) if str(n).strip()]
    wanted = (want or "").strip()
    if not names:
        return wanted, ""
    if not wanted:
        return names[0], ""
    lowered = {n.lower(): n for n in names}
    if wanted.lower() in lowered:
        return lowered[wanted.lower()], ""

    want_tokens = _model_tokens(wanted)
    best, best_score = "", 0
    for name in names:
        score = len(want_tokens & _model_tokens(name))
        if score > best_score:
            best, best_score = name, score
    if best:
        return best, f"你填的模型「{wanted}」在这个网关的清单里没有，已改用「{best}」"
    return names[0], f"你填的模型「{wanted}」在这里找不到相近的，已挑一个可用的「{names[0]}」"


def mask_key(key: str) -> str:
    """日志里的 Key 只留头尾。日志经常被用户直接贴给别人看，绝不留明文。"""
    text = key or ""
    if not text:
        return ""
    if len(text) <= 8:
        return "***"
    return f"{text[:6]}***{text[-4:]}"


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


def _post_openai(
    cfg: AIConfig,
    payload: dict,
    timeout: float,
    poster: Callable[[str, dict[str, str], bytes, float], tuple[int, str]] | None = None,
) -> str:
    """往 OpenAI 兼容网关发一次，返回模型原始文本。

    端点按 ``_openai_endpoints`` 依次试：用户填 ``https://host`` 而真正端点是
    ``https://host/v1`` 时，404 只是"这个猜测不对"，不是失败。只有非 404/405
    才停手——那才是 key 或网关本身的问题，继续试只会掩盖真实原因。
    """
    bases = _bases_to_try(cfg.resolved_base_url())
    if not bases:
        raise ValueError("缺少 Base URL：中转站请填写完整地址，如 https://your-relay.com/v1")
    endpoints = [f"{b}/chat/completions" for b in bases]
    do_post = poster or (
        lambda url, headers, body, t: _http_request("POST", url, headers, body, t)
    )
    body_obj: dict = {
        "model": cfg.resolved_model(),
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }
    # 只有官方地址才发 response_format：官方保证 JSON 模式，中转站不保证支持，
    # 有的会直接 400，有的悄悄忽略——不如只靠提示词 + 外围剥围栏。
    if _is_official_base(cfg.resolved_base_url()):
        body_obj["response_format"] = {"type": "json_object"}
    body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
    headers = _openai_headers(cfg.api_key)

    tried: list[str] = []
    last_status, last_text = 0, ""
    for url in endpoints:
        tried.append(url)
        status, text = do_post(url, headers, body, timeout)
        if status < 400:
            return _extract_openai_text(text)
        last_status, last_text = status, text
        if status not in (404, 405):
            raise ValueError(_explain_status(status, text, url))

    raise ValueError(
        "所有候选端点都返回 "
        f"{last_status}，请确认 Base URL：\n  " + "\n  ".join(tried)
        + f"\n最后一条响应：{(last_text or '').strip()[:200]}"
    )


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
    "probe_endpoint",
    "to_briefs",
    "replace",
]
