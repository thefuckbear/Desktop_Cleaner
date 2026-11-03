"""AI 助手：配置持久化、脱敏、降级。

三条不可退让的线：
1. 只把元数据（名字/扩展名/大小/时间）发出去，绝不读文件内容；
2. 没配 key、网络失败、返回格式坏、建议里的去向非法 —— 一律降级回本地规则；
3. 建议里的目录必须过 targetdir 校验，宁可整批不用，也不把坏建议混进计划。
"""

from __future__ import annotations

import json
from pathlib import Path

from desktop_organizer import ai_assistant as ai
from desktop_organizer import settings
from desktop_organizer.model import FileItem

# ------------------------------------------------------------------ 配置


def test_ai_config_defaults_to_deepseek(tmp_path) -> None:
    # 2026-11-03 需求变更：默认顾问改成 DeepSeek（用户手上就有这把钥匙）
    cfg = settings.ai_config(tmp_path / "s.json")
    assert cfg.provider == "deepseek"
    assert cfg.api_key == ""
    assert cfg.resolved_model() == "deepseek-chat"
    assert cfg.resolved_base_url() == "https://api.deepseek.com"


def test_ai_config_roundtrip(tmp_path) -> None:
    p = tmp_path / "s.json"
    settings.set_ai_config(
        ai.AIConfig(provider="gemini", api_key="k1", model="gemini-2.5-flash"), p
    )
    cfg = settings.ai_config(p)
    assert cfg.provider == "gemini"
    assert cfg.api_key == "k1"


def test_ai_config_dict_masks_api_key(tmp_path) -> None:
    p = tmp_path / "s.json"
    settings.set_ai_config(ai.AIConfig(provider="gemini", api_key="secret-value"), p)
    payload = settings.ai_config_dict(p)
    assert "secret-value" not in json.dumps(payload, ensure_ascii=False)
    assert payload["has_key"] is True


def test_corrupt_ai_config_falls_back_to_default_provider(tmp_path) -> None:
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    assert settings.ai_config(p).provider == "deepseek"


def test_unknown_provider_falls_back_to_default_provider(tmp_path) -> None:
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"ai": {"provider": "chatgpt"}}), encoding="utf-8")
    assert settings.ai_config(p).provider == "deepseek"


# ------------------------------------------------------------------ 脱敏


def _item(tmp_path, name: str = "a.jpg", ext: str = ".jpg", size: int = 100,
          mtime: float = 1.0) -> FileItem:
    p = tmp_path / name
    p.write_text("x", encoding="utf-8")
    return FileItem(
        path=str(p),
        name=name,
        ext=ext,
        size=size,
        mtime=mtime,
        atime=mtime,
        is_dir=False,
        readonly=False,
        cloud_placeholder=False,
        skipped_reason="",
    )


def test_module_never_opens_file_contents() -> None:
    src = Path(ai.__file__).read_text(encoding="utf-8")
    for bad in ("open(", "read_text(", "read_bytes("):
        assert bad not in src, f"脱敏红线：ai_assistant 不得出现 {bad}"


def test_payload_contains_only_whitelisted_fields(tmp_path) -> None:
    briefs = ai.to_briefs([_item(tmp_path)])
    payload = ai.build_payload(briefs)
    text = json.dumps(payload, ensure_ascii=False)
    for key in ("content", "body", "text", "data"):
        assert f'"{key}"' not in text
    assert "a.jpg" in text


def test_brief_drops_full_path_directory(tmp_path) -> None:
    brief = ai.to_briefs([_item(tmp_path, name="b.txt", ext=".txt")])[0]
    assert brief.name == "b.txt"
    assert brief.ext == ".txt"
    assert brief.size_bytes == 100


# ------------------------------------------------------------------ 降级


def test_off_provider_degrades_to_local_rules(tmp_path) -> None:
    sug, degraded, reason = ai.analyze([_item(tmp_path)], ai.AIConfig(provider="off"))
    assert degraded is True
    assert "off" in reason.lower() or "未配置" in reason
    assert len(sug) == 1 and sug[0].target_dir


def test_missing_api_key_degrades(tmp_path) -> None:
    cfg = ai.AIConfig(provider="gemini", api_key="")
    sug, degraded, _ = ai.analyze([_item(tmp_path)], cfg)
    assert degraded is True and len(sug) == 1


def test_transport_exception_degrades(tmp_path) -> None:
    def boom(_payload: dict) -> str:
        raise TimeoutError("网络超时")

    cfg = ai.AIConfig(provider="gemini", api_key="k")
    sug, degraded, reason = ai.analyze([_item(tmp_path)], cfg, transport=boom)
    assert degraded is True and "超时" in reason
    assert len(sug) == 1


def test_malformed_json_degrades(tmp_path) -> None:
    cfg = ai.AIConfig(provider="gemini", api_key="k")
    sug, degraded, _ = ai.analyze(
        [_item(tmp_path)], cfg, transport=lambda _p: "<html>not json</html>"
    )
    assert degraded is True and len(sug) == 1


def test_empty_items_shortcut(tmp_path) -> None:
    sug, degraded, _ = ai.analyze([], ai.AIConfig(provider="gemini", api_key="k"))
    assert sug == []
    assert degraded is True


# ------------------------------------------------------------------ 解析


def test_successful_gemini_response_is_parsed(tmp_path) -> None:
    item = _item(tmp_path)
    body = json.dumps(
        {
            "suggestions": [
                {
                    "path": item.path,
                    "target_dir": "2026财务/票据",
                    "category": "图片",
                    "confidence": 0.9,
                    "reason": "票据扫描件",
                }
            ]
        },
        ensure_ascii=False,
    )
    cfg = ai.AIConfig(provider="gemini", api_key="k")
    sug, degraded, _ = ai.analyze([item], cfg, transport=lambda _p: body)
    assert degraded is False
    assert sug[0].target_dir == "2026财务/票据"
    assert sug[0].confidence == 0.9


def test_ai_target_dir_must_be_relative(tmp_path) -> None:
    item = _item(tmp_path)
    body = json.dumps(
        {
            "suggestions": [
                {
                    "path": item.path,
                    "target_dir": "C:\\Windows",
                    "category": "图片",
                    "confidence": 0.9,
                    "reason": "坏建议",
                }
            ]
        },
        ensure_ascii=False,
    )
    cfg = ai.AIConfig(provider="gemini", api_key="k")
    sug, degraded, _ = ai.analyze([item], cfg, transport=lambda _p: body)
    assert degraded is True
    assert sug[0].target_dir != "C:\\Windows"


def test_unknown_paths_from_ai_are_dropped(tmp_path) -> None:
    item = _item(tmp_path)
    body = json.dumps(
        {
            "suggestions": [
                {
                    "path": str(tmp_path / "not-in-list.txt"),
                    "target_dir": "别处",
                    "category": "文档",
                    "confidence": 0.5,
                    "reason": "陌生文件",
                }
            ]
        },
        ensure_ascii=False,
    )
    cfg = ai.AIConfig(provider="gemini", api_key="k")
    sug, degraded, _ = ai.analyze([item], cfg, transport=lambda _p: body)
    assert degraded is True
    assert all(s.path == item.path for s in sug)


def test_missing_suggestion_for_a_file_falls_back_for_that_file(tmp_path) -> None:
    a = _item(tmp_path, name="a.jpg")
    b = _item(tmp_path, name="b.zip", ext=".zip")
    body = json.dumps(
        {
            "suggestions": [
                {
                    "path": a.path,
                    "target_dir": "自定义目录",
                    "category": "图片",
                    "confidence": 0.9,
                    "reason": "ok",
                }
            ]
        },
        ensure_ascii=False,
    )
    cfg = ai.AIConfig(provider="gemini", api_key="k")
    sug, degraded, _ = ai.analyze([a, b], cfg, transport=lambda _p: body)
    assert degraded is False
    by_path = {s.path: s for s in sug}
    assert by_path[a.path].target_dir == "自定义目录"
    assert by_path[b.path].target_dir  # 没建议的那个仍要有去处
    assert "本地" in by_path[b.path].reason


def test_payload_includes_custom_folders(tmp_path) -> None:
    cfg = ai.AIConfig(
        provider="openai_compatible", api_key="k", base_url="https://x/v1",
        custom_folders=["2026财务/票据"],
    )
    seen: dict = {}

    def transport(payload: dict) -> str:
        seen.update(payload)
        return json.dumps({"suggestions": []})

    ai.analyze([_item(tmp_path)], cfg, transport=transport)
    assert seen["custom_folders"] == ["2026财务/票据"]


# ------------------------------------------------------------------ DeepSeek 顾问

def test_deepseek_is_the_default_advisor() -> None:
    assert ai.DEFAULT_PROVIDER == "deepseek"
    assert "deepseek" in ai.PROVIDERS
    cfg = ai.AIConfig()
    assert cfg.resolved_model() == "deepseek-chat"
    assert cfg.resolved_base_url() == "https://api.deepseek.com"


def test_deepseek_reuses_the_openai_compatible_transport(monkeypatch, tmp_path) -> None:
    seen: dict = {}

    def fake_post(cfg, payload, timeout):
        seen["url_model"] = cfg.resolved_model()
        seen["url_base"] = cfg.resolved_base_url()
        return json.dumps({"suggestions": []})

    monkeypatch.setattr(ai, "_post_openai", fake_post)
    cfg = ai.AIConfig(provider="deepseek", api_key="k")
    ai.analyze([_item(tmp_path)], cfg)
    assert seen["url_model"] == "deepseek-chat"
    assert seen["url_base"] == "https://api.deepseek.com"


def test_deepseek_without_key_degrades_to_local_rules(tmp_path) -> None:
    sug, degraded, reason = ai.analyze(
        [_item(tmp_path)], ai.AIConfig(provider="deepseek", api_key="")
    )
    assert degraded is True
    assert "Key" in reason
    assert sug[0].target_dir


def test_user_model_overrides_provider_default() -> None:
    cfg = ai.AIConfig(provider="deepseek", model="deepseek-reasoner")
    assert cfg.resolved_model() == "deepseek-reasoner"


def test_system_prompt_teaches_how_to_use_the_app_and_gives_strategy() -> None:
    """顾问不是"目录生成器"：prompt 必须讲清软件用法，并给出整理策略口径。"""
    prompt = ai._SYSTEM_PROMPT
    for token in ("用户目录写入", "预览", "回滚", "一键整理图标", "撤销"):
        assert token in prompt
    for token in ("顶层", "重要", "归档", "临时/待清", "项目/"):
        assert token in prompt
    # 硬约束：不许要文件内容，不许绝对路径
    assert "看不到文件内容" in prompt
    assert "绝对路径" in prompt
