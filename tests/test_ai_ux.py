"""AI 部分的易用性：模型名自动纠正、模型清单缓存、失败日志可查。

背景（2026-11-04 用户实测）：界面里 `model` 填成 `deepseek-flash`，而网关给的
28 个名字是 `deepseek-v4.1-flash` / `deepseek-v4-pro` / `glm-5.2` 之类 —— 根本没这
个名字。更糟的是「测试连接」只查 `/models`，看起来全绿；真跑分析才失败，而
`bridge.py` 里一个日志写入都没有，于是出问题后**没有任何证据可查**。

本文件锁住三件事：

1. `pick_model` 只凭「用户填的名字 + 网关给的名字」就能给出最接近的可用模型，
   并且明确告诉用户"你填的没有，我换成了什么"；
2. 拉模型清单会缓存（同进程 5 分钟内不重复请求），换 base 必须重新拉；
3. 每次 AI 分析都写 `logs/ai.log`，Key 一律脱敏，任何人拿到日志也读不出 Key。
"""

from __future__ import annotations

import json

import pytest

from desktop_organizer import ai_assistant as ai
from desktop_organizer.model import FileItem

AVAILABLE = [
    "deepseek-v4.1-flash",
    "deepseek-v4-pro",
    "glm-5.2",
    "glm-5.3",
    "grok-4.7",
]


# ------------------------------------------------------------------ pick_model


def test_exact_model_name_is_kept_silently() -> None:
    """名字对得上就一个字都不改，也别多嘴。"""
    model, note = ai.pick_model("glm-5.3", AVAILABLE)
    assert model == "glm-5.3"
    assert note == ""


def test_short_name_is_corrected_to_the_closest_real_one() -> None:
    """用户填 deepseek-flash，网关里只有 deepseek-v4.1-flash —— 得能自己找过去。"""
    model, note = ai.pick_model("deepseek-flash", AVAILABLE)
    assert model == "deepseek-v4.1-flash"
    assert "deepseek-flash" in note
    assert "deepseek-v4.1-flash" in note


def test_unknown_family_falls_back_to_first_available() -> None:
    """差得太远时也得给个能用的，并说清楚是"挑了一个"而不是"你填的对"。"""
    model, note = ai.pick_model("qwen-max", AVAILABLE)
    assert model in AVAILABLE
    assert "qwen-max" in note


def test_empty_want_picks_first_available() -> None:
    """没填模型 → 用网关的第一个，别把空串发出去。"""
    model, note = ai.pick_model("", AVAILABLE)
    assert model == AVAILABLE[0]
    assert note == ""


def test_no_available_models_keeps_the_original() -> None:
    """拉不到清单（离线/接口不支持）时不许自作主张改名字，也不许抛。"""
    model, note = ai.pick_model("deepseek-flash", [])
    assert model == "deepseek-flash"
    assert note == ""


def test_pick_model_tolerates_whitespace_and_case() -> None:
    model, note = ai.pick_model("  GLM-5.2  ", AVAILABLE)
    assert model == "glm-5.2"
    assert note == ""


# --------------------------------------------------------------- 模型清单缓存


def test_models_are_fetched_once_within_ttl(monkeypatch) -> None:
    """5 分钟内重复调用只打一次网络——分析前校验不该让每次分析都等两秒。"""
    calls: list[str] = []

    def fake_getter(url: str, headers: dict[str, str], timeout: float) -> tuple[int, str]:
        calls.append(url)
        return 200, json.dumps({"data": [{"id": "m1"}, {"id": "m2"}]})

    ai.clear_model_cache()
    first = ai.list_models("https://host/v1", "k", getter=fake_getter, now=lambda: 1000.0)
    second = ai.list_models("https://host/v1", "k", getter=fake_getter, now=lambda: 1001.0)
    assert first == ["m1", "m2"]
    assert second == first
    assert len(calls) == 1


def test_cache_expires_after_ttl(monkeypatch) -> None:
    calls: list[str] = []

    def fake_getter(url: str, headers: dict[str, str], timeout: float) -> tuple[int, str]:
        calls.append(url)
        return 200, json.dumps({"data": [{"id": "m1"}]})

    ai.clear_model_cache()
    ai.list_models("https://host/v1", "k", getter=fake_getter, now=lambda: 1000.0)
    ai.list_models("https://host/v1", "k", getter=fake_getter, now=lambda: 1000.0 + ai.MODEL_CACHE_TTL + 1)
    assert len(calls) == 2


def test_different_base_url_is_not_served_from_cache() -> None:
    """换网关必须重新拉：两个站点的模型名完全可能不通用。"""
    calls: list[str] = []

    def fake_getter(url: str, headers: dict[str, str], timeout: float) -> tuple[int, str]:
        calls.append(url)
        return 200, json.dumps({"data": [{"id": "m1"}]})

    ai.clear_model_cache()
    ai.list_models("https://a/v1", "k", getter=fake_getter, now=lambda: 1.0)
    ai.list_models("https://b/v1", "k", getter=fake_getter, now=lambda: 2.0)
    assert len(calls) == 2


def test_list_models_returns_empty_instead_of_raising() -> None:
    """拿不到清单是常态（网关没 /models、网络抖），绝不能把分析整条拦死。"""

    def boom(url: str, headers: dict[str, str], timeout: float) -> tuple[int, str]:
        raise OSError("网络断了")

    ai.clear_model_cache()
    assert ai.list_models("https://host/v1", "k", getter=boom) == []


# -------------------------------------------------------------------- 脱敏


def test_key_is_masked_with_head_and_tail_only() -> None:
    masked = ai.mask_key("oc_sk_06e488e87831_6n9wzrThOoRerjk_N1xld8kcueFlFzvP")
    assert "6e488e87831" not in masked
    assert "N1xld8kcueFlFzvP" not in masked
    assert masked.startswith("oc_sk_")
    assert masked.endswith("FzvP")


def test_short_key_never_leaks_its_body() -> None:
    assert ai.mask_key("abc") == "***"


def test_empty_key_is_empty() -> None:
    assert ai.mask_key("") == ""


# ------------------------------------------------------- ai_suggest 自动纠正


def _item(name: str) -> FileItem:
    return FileItem(path=f"C:\\Users\\HY\\Desktop\\{name}", name=name)


def _bridge(tmp_path):
    from desktop_organizer import bridge

    return bridge.Bridge(root=str(tmp_path), depth=1, store_path=tmp_path / "pref.json")


def _cfg(tmp_path, monkeypatch, *, model: str) -> None:
    from desktop_organizer import settings

    monkeypatch.setattr(
        settings,
        "ai_config",
        lambda path=None: ai.AIConfig(
            provider="openai_compatible",
            api_key="oc_sk_test",
            base_url="https://host/v1",
            model=model,
        ),
    )


def test_ai_suggest_corrects_the_model_before_calling(tmp_path, monkeypatch) -> None:
    """分析前的校验：模型名不在清单里就换成可用的，而不是等 API 报错。"""
    b = _bridge(tmp_path)
    b._items = [_item("a.txt")]
    _cfg(tmp_path, monkeypatch, model="deepseek-flash")

    monkeypatch.setattr(ai, "list_models", lambda *a, **k: ["deepseek-v4.1-flash"])
    seen: list[dict] = []

    def transport(payload: dict) -> str:
        seen.append(payload)
        return json.dumps({"suggestions": []})

    b.ai_suggest(transport=transport)
    assert seen and seen[0]["model"] == "deepseek-v4.1-flash"


def test_ai_suggest_records_the_substitution_in_the_log(tmp_path, monkeypatch) -> None:
    """纠正这件事必须留痕：用户得知道自己实际用了哪个模型。"""
    b = _bridge(tmp_path)
    b._items = [_item("a.txt")]
    _cfg(tmp_path, monkeypatch, model="deepseek-flash")
    monkeypatch.setattr(ai, "list_models", lambda *a, **k: ["deepseek-v4.1-flash"])

    b.ai_suggest(transport=lambda payload: json.dumps({"suggestions": []}))

    text = b.ai_log_path().read_text(encoding="utf-8")
    assert "deepseek-flash" in text
    assert "deepseek-v4.1-flash" in text


def test_ai_log_masks_the_key(tmp_path, monkeypatch) -> None:
    """日志会被用户发给别人看，里面绝不能有明文 Key。"""
    b = _bridge(tmp_path)
    b._items = [_item("a.txt")]
    _cfg(tmp_path, monkeypatch, model="glm-5.3")
    monkeypatch.setattr(ai, "list_models", lambda *a, **k: ["glm-5.3"])

    b.ai_suggest(transport=lambda payload: json.dumps({"suggestions": []}))

    text = b.ai_log_path().read_text(encoding="utf-8")
    assert "oc_sk_test" not in text


def test_ai_log_records_the_failure_reason(tmp_path, monkeypatch) -> None:
    """失败时日志里要有原因，否则用户只能看到界面上那句"AI 调用失败"。"""
    b = _bridge(tmp_path)
    b._items = [_item("a.txt")]
    _cfg(tmp_path, monkeypatch, model="glm-5.3")
    monkeypatch.setattr(ai, "list_models", lambda *a, **k: ["glm-5.3"])

    def broken(payload: dict) -> str:
        raise ValueError("HTTP 500: 上游炸了")

    b.ai_suggest(transport=broken)

    text = b.ai_log_path().read_text(encoding="utf-8")
    assert "HTTP 500" in text


def test_ai_log_uses_utf8_and_survives_gbk_console(tmp_path, monkeypatch) -> None:
    """中文原因要能写进文件（Windows 默认 cp936 会炸，也必须写 UTF-8）。"""
    b = _bridge(tmp_path)
    b._items = [_item("a.txt")]
    _cfg(tmp_path, monkeypatch, model="glm-5.3")
    monkeypatch.setattr(ai, "list_models", lambda *a, **k: ["glm-5.3"])

    def broken(payload: dict) -> str:
        raise ValueError("模型给出的去向非法")

    b.ai_suggest(transport=broken)

    raw = b.ai_log_path().read_bytes()
    assert "模型给出的去向非法" in raw.decode("utf-8")


# ------------------------------------------------------------ 建议的展示信息


def test_suggestions_carry_reason_for_the_ui(tmp_path, monkeypatch) -> None:
    """理由要回给前端：只说"文档/重要 0.8"用户没法判断该不该信。"""
    b = _bridge(tmp_path)
    b._items = [_item("合同.pdf")]
    _cfg(tmp_path, monkeypatch, model="glm-5.3")
    monkeypatch.setattr(ai, "list_models", lambda *a, **k: ["glm-5.3"])

    payload = {
        "suggestions": [
            {
                "path": "C:\\Users\\HY\\Desktop\\合同.pdf",
                "target_dir": "文档/重要",
                "category": "文档",
                "confidence": 0.9,
                "reason": "文件名含合同，属重要文档",
            }
        ]
    }
    res = b.ai_suggest(transport=lambda p: json.dumps(payload))
    assert res["suggestions"][0]["reason"] == "文件名含合同，属重要文档"
