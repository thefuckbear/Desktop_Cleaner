"""桥接层：进度推流 + AI 配置 + AI 建议。"""

from __future__ import annotations

import json

from desktop_organizer import ai_assistant
from desktop_organizer.bridge import Bridge


class _FakeWindow:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def evaluate_js(self, script: str) -> None:
        self.calls.append(script)


def _bridge(tmp_path) -> Bridge:
    return Bridge(
        root=str(tmp_path),
        store_path=tmp_path / "p.json",
        settings_path=tmp_path / "s.json",
    )


def test_notify_progress_calls_evaluate_js(tmp_path) -> None:
    b = _bridge(tmp_path)
    w = _FakeWindow()
    b.set_window(w)
    b.notify_progress("scan", 1, 4, current_item="a.txt")
    assert w.calls and "onProgress" in w.calls[0]
    payload = w.calls[0].split("onProgress(", 1)[1].rstrip(")")
    data = json.loads(payload)
    assert data["stage"] == "scan"
    assert data["current"] == 1
    assert data["total"] == 4
    assert data["percent"] == 25.0
    assert data["current_item"] == "a.txt"


def test_notify_progress_swallows_broken_window(tmp_path) -> None:
    b = _bridge(tmp_path)

    class Bad:
        def evaluate_js(self, _s: str) -> None:
            raise RuntimeError("窗口没了")

    b.set_window(Bad())
    b.notify_progress("apply", 1, 2)  # 不得抛出


def test_notify_progress_without_window_is_noop(tmp_path) -> None:
    b = _bridge(tmp_path)
    b.notify_progress("apply", 1, 2)  # 没设窗口也不能崩


def test_progress_snapshot_has_stage_and_percent(tmp_path) -> None:
    b = _bridge(tmp_path)
    d = b.progress()
    assert "stage" in d and "percent" in d


def test_notify_progress_updates_snapshot(tmp_path) -> None:
    b = _bridge(tmp_path)
    b.notify_progress("apply", 3, 4, current_item="z.txt")
    d = b.progress()
    assert d["stage"] == "apply"
    assert d["percent"] == 75.0


def test_scan_reports_progress(tmp_path) -> None:
    (tmp_path / "a.jpg").write_text("x", encoding="utf-8")
    (tmp_path / "b.zip").write_text("y", encoding="utf-8")
    b = _bridge(tmp_path)
    w = _FakeWindow()
    b.set_window(w)
    b.scan()
    stages = [json.loads(c.split("onProgress(", 1)[1].rstrip(")"))["stage"] for c in w.calls]
    assert "scan" in stages


def test_ai_suggest_without_key_returns_local_and_marks_degraded(tmp_path) -> None:
    (tmp_path / "a.jpg").write_text("x", encoding="utf-8")
    b = _bridge(tmp_path)
    b.scan()
    res = b.ai_suggest()
    assert res["degraded"] is True
    assert res["total"] >= 1
    assert res["suggestions"][0]["target_dir"]


def test_ai_suggest_requires_a_plan_first(tmp_path) -> None:
    b = _bridge(tmp_path)
    res = b.ai_suggest()
    assert res["degraded"] is True
    assert res["total"] == 0


def test_ai_settings_never_returns_raw_key(tmp_path) -> None:
    b = _bridge(tmp_path)
    b.save_ai_settings("gemini", api_key="super-secret")
    snapshot = str(b.ai_settings())
    assert "super-secret" not in snapshot
    assert b.ai_settings()["has_key"] is True


def test_save_ai_settings_persists(tmp_path) -> None:
    b = _bridge(tmp_path)
    b.save_ai_settings("openai_compatible", api_key="k", base_url="https://x/v1", model="m")
    again = _bridge(tmp_path)
    cfg = again.ai_settings()
    assert cfg["provider"] == "openai_compatible"
    assert cfg["base_url"] == "https://x/v1"
    assert cfg["model"] == "m"
    assert cfg["has_key"] is True


def test_save_ai_settings_off_clears_nothing_else(tmp_path) -> None:
    b = _bridge(tmp_path)
    b.save_ai_settings("gemini", api_key="k")
    b.save_ai_settings("off")
    cfg = b.ai_settings()
    assert cfg["provider"] == "off"


def test_ai_suggest_uses_transport_when_configured(tmp_path) -> None:
    (tmp_path / "a.jpg").write_text("x", encoding="utf-8")
    b = _bridge(tmp_path)
    b.scan()
    b.save_ai_settings("gemini", api_key="k")
    item = b._items[0]
    body = json.dumps(
        {
            "suggestions": [
                {
                    "path": item.path,
                    "target_dir": "我的相册",
                    "category": "图片",
                    "confidence": 0.9,
                    "reason": "照片",
                }
            ]
        },
        ensure_ascii=False,
    )
    res = b.ai_suggest(transport=lambda _p: body)
    assert res["degraded"] is False
    assert res["suggestions"][0]["target_dir"] == "我的相册"


def test_apply_suggestion_writes_into_plan(tmp_path) -> None:
    (tmp_path / "a.jpg").write_text("x", encoding="utf-8")
    b = _bridge(tmp_path)
    b.scan()
    b.plan()
    res = b.apply_suggestions(
        [{"path": b._items[0].path, "target_dir": "我的相册"}]
    )
    assert res["ok"] is True
    assert res["updated"] == 1
    row = b.plan_for(b._items[0].path)
    assert row["target_dir"].replace("\\", "/") == "我的相册"


def test_apply_suggestions_rejects_illegal_dir(tmp_path) -> None:
    (tmp_path / "a.jpg").write_text("x", encoding="utf-8")
    b = _bridge(tmp_path)
    b.scan()
    b.plan()
    res = b.apply_suggestions([{"path": b._items[0].path, "target_dir": "../../Windows"}])
    assert res["ok"] is False
    assert res["error"]


def test_apply_suggestions_tolerates_unknown_paths(tmp_path) -> None:
    (tmp_path / "a.jpg").write_text("x", encoding="utf-8")
    b = _bridge(tmp_path)
    b.scan()
    b.plan()
    res = b.apply_suggestions([{"path": "C:\\nowhere\\x.txt", "target_dir": "别处"}])
    assert res["ok"] is True
    assert res["updated"] == 0


def test_ai_config_defaults_to_deepseek(tmp_path) -> None:
    """2026-11-03 需求变更（用户 m08212）：默认顾问改为 DeepSeek。

    原来是 ``off``（只用本地规则）；现在默认指向 DeepSeek，没填 Key 时
    仍然自动降级回本地规则，所以"不需要配置也能用"这个性质没变。
    """
    b = _bridge(tmp_path)
    assert b.ai_settings()["provider"] == "deepseek"
    assert b.ai_settings()["has_key"] is False


def test_ai_assistant_exports_config_class() -> None:
    assert ai_assistant.AIConfig().provider == ai_assistant.DEFAULT_PROVIDER
