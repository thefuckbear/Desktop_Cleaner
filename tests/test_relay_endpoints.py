"""中转站（openai 兼容网关）适配。

背景（2026-11-03 实测）：用户的 Key 来自 opencode go 中转站，不是某家官网。
当时的实现预设了官方地址，于是三件事一起出错：

1. base_url 留空就落到官方域名 → 中转 Key 被发去官网 → 401，
   而 401 的文案写「API Key 无效」，把"地址配错"伪装成"key 坏了"；
2. 端点写死成 `{base}/chat/completions` → 用户填 `https://host`（无 /v1）就 404；
   填 `https://host/v1` 才对，但用户无从知道该不该带 /v1；
3. opencode go 实测还要求 `x-opencode-session` 请求头，缺了直接 400
   MissingSessionID —— 这个错误跟 Key、地址都无关，却长得像鉴权失败。

本文件锁住修好之后的行为：地址是权威、端点会回退、报错带 URL 且能分辨
"地址不对"与"key 不对"、probe 能把模型列表拉回来。
"""

from __future__ import annotations

import json

import pytest

from desktop_organizer import ai_assistant as ai
from desktop_organizer.model import FileItem

# ------------------------------------------------------------------ 端点候选


def test_base_without_version_gets_a_v1_candidate() -> None:
    """用户填 https://host 时，必须能自己试出 https://host/v1。"""
    urls = ai._openai_endpoints("https://host")
    assert urls == [
        "https://host/chat/completions",
        "https://host/v1/chat/completions",
    ]


def test_base_already_ending_in_v1_is_used_as_is() -> None:
    """填了 /v1 就别再叠一层，否则拼成 /v1/v1。"""
    urls = ai._openai_endpoints("https://opencode.ai/zen/go/v1")
    assert urls == ["https://opencode.ai/zen/go/v1/chat/completions"]


def test_trailing_slash_does_not_produce_double_slash() -> None:
    assert ai._openai_endpoints("https://host/v1/") == ["https://host/v1/chat/completions"]


def test_endpoints_never_duplicate_a_version_segment() -> None:
    """v2/v3 这类版本段同样不该被再拼 /v1。"""
    urls = ai._openai_endpoints("https://host/api/v2")
    assert urls == ["https://host/api/v2/chat/completions"]


# ------------------------------------------------------------------ 会话头


def test_request_carries_a_session_header() -> None:
    """opencode go 缺 x-opencode-session 会 400，必须默认带上。"""
    headers = ai._openai_headers("sk-test")
    assert "x-opencode-session" in headers
    assert len(headers["x-opencode-session"]) >= 8


def test_session_header_is_stable_within_one_process() -> None:
    """同一进程内固定：每次请求换 ID 对服务端是噪声，对日志是干扰。"""
    a = ai._openai_headers("sk-test")["x-opencode-session"]
    b = ai._openai_headers("sk-test")["x-opencode-session"]
    assert a == b


def test_authorization_header_uses_bearer() -> None:
    assert ai._openai_headers("sk-abc")["Authorization"] == "Bearer sk-abc"


# ------------------------------------------------------------------ 报错归因


def test_401_names_the_url_that_rejected_the_key() -> None:
    """关键回归：401 必须带上真正被打的地址，否则用户永远查不出是地址错。"""
    cfg = ai.AIConfig(
        provider="openai_compatible", api_key="oc_sk_x", base_url="https://relay.example/v1"
    )
    with pytest.raises(ValueError) as exc:
        ai._post_openai(cfg, {}, 5.0, poster=_status_poster(401, "invalid key"))
    msg = str(exc.value)
    assert "https://relay.example/v1/chat/completions" in msg
    assert "中转" in msg  # 明确提示"如果是中转站，确认地址"


def test_404_falls_back_to_the_next_candidate() -> None:
    """填 https://host 而正确端点是 /v1 时，404 应自动换候选而不是直接失败。"""
    seen: list[str] = []

    def poster(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, str]:
        seen.append(url)
        if "/v1/" in url:
            return 200, json.dumps({"choices": [{"message": {"content": "{}"}}]})
        return 404, "not found"

    cfg = ai.AIConfig(
        provider="openai_compatible", api_key="k", base_url="https://host"
    )
    out = ai._post_openai(cfg, {}, 5.0, poster=poster)
    assert out.startswith("{")
    assert seen == [
        "https://host/chat/completions",
        "https://host/v1/chat/completions",
    ]


def test_all_candidates_404_reports_every_url_tried() -> None:
    def poster(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, str]:
        return 404, "nope"

    cfg = ai.AIConfig(provider="openai_compatible", api_key="k", base_url="https://host")
    with pytest.raises(ValueError) as exc:
        ai._post_openai(cfg, {}, 5.0, poster=poster)
    msg = str(exc.value)
    assert "https://host/chat/completions" in msg
    assert "https://host/v1/chat/completions" in msg


def test_missing_session_error_is_translated_not_dumped_raw() -> None:
    """服务端抱怨缺 session 时，不能让用户去看原始英文 JSON。"""

    def poster(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, str]:
        return 400, json.dumps(
            {"type": "error", "error": {"type": "MissingSessionID", "message": "..."}}
        )

    cfg = ai.AIConfig(provider="openai_compatible", api_key="k", base_url="https://h/v1")
    with pytest.raises(ValueError) as exc:
        ai._post_openai(cfg, {}, 5.0, poster=poster)
    assert "x-opencode-session" in str(exc.value) or "会话" in str(exc.value)


# ------------------------------------------------------------------ 官网 vs 中转


def test_official_provider_without_base_url_keeps_official_default() -> None:
    """现有 395 个测试依赖这条：不填地址时 deepseek 仍落官网。"""
    cfg = ai.AIConfig(provider="deepseek", api_key="sk-x")
    assert cfg.resolved_base_url() == "https://api.deepseek.com"


def test_custom_base_url_always_wins_over_provider_default() -> None:
    cfg = ai.AIConfig(
        provider="deepseek", api_key="oc_sk_x", base_url="https://opencode.ai/zen/go/v1"
    )
    assert cfg.resolved_base_url() == "https://opencode.ai/zen/go/v1"


def test_relay_key_with_official_provider_warns_instead_of_blaming_the_key() -> None:
    """oc_sk_ 这类第三方 Key 配官网地址，提示必须指向"地址"，不是"key 无效"。"""
    cfg = ai.AIConfig(provider="deepseek", api_key="oc_sk_deadbeef0000")
    items = [FileItem(path=r"C:\Users\x\Desktop\a.zip", name="a.zip", ext=".zip")]
    sug, degraded, reason = ai.analyze(items, cfg)
    assert degraded is True
    assert "Base URL" in reason or "地址" in reason
    # 关键：不许把"地址没配对"说成"key 无效"
    assert "无效" not in reason


# ------------------------------------------------------------------ probe


def test_probe_lists_models_and_reports_the_base_used() -> None:
    def getter(url: str, headers: dict, timeout: float) -> tuple[int, str]:
        assert url.endswith("/models")
        return 200, json.dumps({"data": [{"id": "deepseek-v4.1-flash"}, {"id": "glm-5.3"}]})

    out = ai.probe_endpoint(
        base_url="https://opencode.ai/zen/go/v1", api_key="k", getter=getter
    )
    assert out["ok"] is True
    assert out["models"] == ["deepseek-v4.1-flash", "glm-5.3"]
    assert out["base_url_used"] == "https://opencode.ai/zen/go/v1"


def test_probe_tries_v1_when_bare_base_404s() -> None:
    seen: list[str] = []

    def getter(url: str, headers: dict, timeout: float) -> tuple[int, str]:
        seen.append(url)
        if "/v1/models" in url:
            return 200, json.dumps({"data": [{"id": "m1"}]})
        return 404, ""

    out = ai.probe_endpoint(base_url="https://host", api_key="k", getter=getter)
    assert out["ok"] is True
    assert out["base_url_used"] == "https://host/v1"
    assert seen == ["https://host/models", "https://host/v1/models"]


def test_probe_surfaces_http_failure_without_raising() -> None:
    def getter(url: str, headers: dict, timeout: float) -> tuple[int, str]:
        return 401, "unauthorized"

    out = ai.probe_endpoint(base_url="https://host/v1", api_key="bad", getter=getter)
    assert out["ok"] is False
    assert "401" in out["error"]
    assert out["models"] == []


# ------------------------------------------------------------------ 参数兼容


def _capture_poster(sink: dict):
    def poster(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, str]:
        sink["url"] = url
        sink["headers"] = headers
        sink["body"] = json.loads(body.decode("utf-8"))
        return 200, json.dumps({"choices": [{"message": {"content": "{}"}}]})
    return poster


def test_official_base_keeps_response_format() -> None:
    """官方地址认识 response_format，继续发，别退化掉 JSON 保证。"""
    sink: dict = {}
    cfg = ai.AIConfig(provider="deepseek", api_key="sk-abc")
    ai._post_openai(cfg, {}, 5.0, poster=_capture_poster(sink))
    assert sink["body"]["response_format"] == {"type": "json_object"}


def test_relay_base_omits_response_format() -> None:
    """中转站不保证支持 response_format，发了可能整条请求 400。"""
    sink: dict = {}
    cfg = ai.AIConfig(
        provider="openai_compatible",
        api_key="oc_sk_x",
        base_url="https://opencode.ai/zen/go/v1",
    )
    ai._post_openai(cfg, {}, 5.0, poster=_capture_poster(sink))
    assert "response_format" not in sink["body"]
    assert sink["headers"]["x-opencode-session"]


# ------------------------------------------------------------------ 桥接层


def test_bridge_test_connection_refuses_when_ai_is_off(tmp_path) -> None:
    """provider=off 时不该去碰网络，直接说清为什么点不动。"""
    from desktop_organizer import bridge as bridge_mod

    b = bridge_mod.Bridge(root=str(tmp_path), depth=1, store_path=tmp_path / "pref.json")
    b.save_ai_settings("off", "k")
    out = b.test_ai_connection()
    assert out["ok"] is False
    assert "off" in out["error"]


def test_bridge_test_connection_uses_the_saved_base_url(tmp_path, monkeypatch) -> None:
    """界面上的地址必须真的被用掉，否则"测试连接"等于没测。"""
    from desktop_organizer import bridge as bridge_mod

    seen: dict = {}

    def fake_probe(base_url="", api_key="", **kw):
        seen["base_url"] = base_url
        seen["api_key"] = api_key
        return {"ok": True, "base_url_used": base_url, "models": ["m1"], "error": "", "tried": []}

    monkeypatch.setattr(ai, "probe_endpoint", fake_probe)
    b = bridge_mod.Bridge(root=str(tmp_path), depth=1, store_path=tmp_path / "pref.json")
    b.save_ai_settings("openai_compatible", "oc_sk_x", "https://opencode.ai/zen/go/v1")
    out = b.test_ai_connection()
    assert out["ok"] is True
    assert seen["base_url"] == "https://opencode.ai/zen/go/v1"
    assert seen["api_key"] == "oc_sk_x"


# ------------------------------------------------------------------ 解析容错


def _status_poster(status: int, body: str):
    def poster(url: str, headers: dict, body_bytes: bytes, timeout: float) -> tuple[int, str]:
        return status, body
    return poster
