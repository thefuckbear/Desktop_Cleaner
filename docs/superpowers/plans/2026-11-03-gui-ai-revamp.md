# GUI 跃升 + AI 助手 + 实时进度 + 内存瘦身 实施计划

> **给执行者：** 按任务顺序逐条执行，每个任务都是「先写失败测试 → 跑到红 → 最小实现 → 跑到绿 → 提交」。用 `- [ ]` 勾选跟踪。
>
> **Spec：** `docs/superpowers/specs/2026-11-03-gui-revamp-design.md`（§8 为第二版需求，覆盖 §0 的三项结论）

**Goal:** 把 Desktop Organizer 从「能用的整理工具」升级为「有 AI 建议、有实时进度、界面现代、默认零联网」的桌面客户端，同时不破坏既有 193 个测试。

**Architecture:** 三层分离——`ai_assistant.py` 只做「元数据 → 建议」的纯计算并能离线降级；`bridge.py` 是唯一出入口，负责把事件推给窗口、把用户输入收敛成合法 `Plan`；`web/index.html` 是纯自绘前端，零外部依赖。进度走「推流为主、轮询兜底」双通道。

**Tech Stack:** Python 3.13.1 / pywebview 6.2.1 (WebView2) / pytest / 标准库 urllib（不引入 requests）/ 纯 CSS + inline SVG + Canvas

---

## Global Constraints

- 既有 193 个测试的**断言与逻辑一个字都不改**；新测试只叠加。
- `src/desktop_organizer/guard.py`、`journal.py`、`iconpos.py` **只读**，不得修改其行为。
- `ai_assistant.py` 中**不得出现** `open(` / `read_text(` / `read_bytes(` 读取文件内容；只允许 `os.stat` / `os.path.getsize` 类元数据访问。
- 所有目标目录必须先 `os.path.normpath` 校验，再 `guard.assert_safe(root/target_dir)`；禁止绝对路径、盘符、`..` 越界、Windows 保留字符。
- 默认 dry-run 不变：AI 建议与批量改目录**只改内存 Plan**。
- 前端零外网：无 CDN、无外链字体、无外链图标、无 `http://` / `https://` 字符串。
- 测试命令固定：`$env:PYTHONPATH='src'; $env:PYTHONIOENCODING='utf-8'; python -m pytest tests/ -q`
- 最终测试数 ≥ 205 passed，0 failed。
- 内存目标 < 75MB 是**目标不是承诺**：必须实测并如实记录，不达标写遗留项。

## Review Focus

1. **脱敏边界**：调用 AI 时若把文件正文或绝对路径带出去 = 隐私事故。测试必须断言 payload 只含白名单字段。
2. **路径越界**：`../../Windows`、`C:\Windows`、`/etc`、`foo\..\..\bar` 必须全部被拒，且不产生任何磁盘副作用。
3. **AI 挂掉不能拖垮整理**：网络超时、返回 HTML、返回畸形 JSON、API Key 错误，都必须降级为本地规则且照常可用。
4. **推流失败不能卡界面**：`evaluate_js` 抛异常、window 未就绪，进度功能失效但扫描/执行/回滚必须照常完成。
5. **既有测试不能因新参数而改变行为**：`execute` / `rollback` / `scan` 新增参数默认 `None` 时，执行路径与现在逐字节等价。

---

## 文件结构

| 文件 | 职责 | 状态 |
|---|---|---|
| `src/desktop_organizer/ai_assistant.py` | AIConfig / FileMetaBrief / AISuggestion 数据类；脱敏打包；Gemini 与 OpenAI 兼容调用；离线降级 | 新建 |
| `src/desktop_organizer/progress.py` | ProgressEvent 数据类 + Stage 常量 | 新建 |
| `src/desktop_organizer/settings.py` | 增加 AI 配置持久化（不解密、不日志打印 key） | 修改 |
| `src/desktop_organizer/bridge.py` | `set_window`、`notify_progress`、`ai_settings`、`save_ai_settings`、`ai_suggest`、`set_target_dir`、`set_target_dir_bulk` | 修改 |
| `src/desktop_organizer/executor.py` | `execute` / `rollback` 增加 `progress_cb` | 修改 |
| `src/desktop_organizer/scanner.py` | `scan` 增加 `on_progress` | 修改 |
| `src/desktop_organizer/gui_web.py` | Chromium 环境变量；`bridge.set_window(window)` | 修改 |
| `src/desktop_organizer/web/index.html` | 三栏布局 + 环形图 + 进度条 + Copilot 抽屉 + 行内去向编辑 | 修改 |
| `tests/test_ai_assistant.py` | 配置 / 脱敏 / 降级 / 自由目录 | 新建 |
| `tests/test_progress.py` | ProgressEvent / 推流 / 轮询兜底 / 回调不干扰 | 新建 |
| `tests/test_target_dir.py` | 单行与批量设目录、非法输入拦截 | 新建 |
| `tests/test_web_assets.py` | 补静态检查（进度条、抽屉、data-target、无外链） | 修改 |

---

## Task 1: 进度事件模型

**Files:**
- Create: `src/desktop_organizer/progress.py`
- Test: `tests/test_progress.py`

**Interfaces:**
- Produces: `Stage`（`"scan" | "plan" | "ai_analyzing" | "apply" | "rollback"`）、`ProgressEvent(stage, current, total, current_item, percent, message)`、`ProgressEvent.to_dict() -> dict`、`ProgressEvent.create(stage, current, total, current_item="", message="") -> ProgressEvent`

- [ ] **Step 1: 写失败测试**

```python
from desktop_organizer.progress import ProgressEvent

def test_percent_is_zero_when_total_is_zero() -> None:
    ev = ProgressEvent.create("scan", 0, 0)
    assert ev.percent == 0.0

def test_percent_rounds_to_one_decimal() -> None:
    ev = ProgressEvent.create("scan", 1, 3)
    assert ev.percent == 33.3

def test_percent_is_capped_at_hundred() -> None:
    ev = ProgressEvent.create("apply", 200, 100)
    assert ev.percent == 100.0

def test_to_dict_is_json_safe_and_complete() -> None:
    ev = ProgressEvent.create("apply", 5, 10, current_item="a.txt", message="正在移动")
    d = ev.to_dict()
    assert set(d) == {"stage", "current", "total", "current_item", "percent", "message"}
    assert d["current_item"] == "a.txt"
    import json
    json.dumps(d)

def test_stage_rejects_unknown_value() -> None:
    try:
        ProgressEvent.create("bogus", 0, 1)  # type: ignore[arg-type]
    except ValueError as exc:
        assert "bogus" in str(exc)
    else:
        raise AssertionError("未知阶段必须报错")
```

- [ ] **Step 2: 跑测试确认失败** → `pytest tests/test_progress.py -v`，预期 `ModuleNotFoundError: desktop_organizer.progress`

- [ ] **Step 3: 最小实现**

```python
"""进度事件：给前端显示的单一数据形状。"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

Stage = Literal["scan", "plan", "ai_analyzing", "apply", "rollback"]
_STAGES = frozenset({"scan", "plan", "ai_analyzing", "apply", "rollback"})


@dataclass(frozen=True)
class ProgressEvent:
    stage: Stage
    current: int
    total: int
    current_item: str
    percent: float
    message: str

    @staticmethod
    def create(stage: Stage, current: int, total: int,
               current_item: str = "", message: str = "") -> "ProgressEvent":
        if stage not in _STAGES:
            raise ValueError(f"未知进度阶段: {stage}")
        total = max(0, int(total))
        current = max(0, int(current))
        if total <= 0:
            percent = 0.0
        else:
            percent = min(100.0, round(current / total * 100.0, 1))
        return ProgressEvent(stage, current, total, current_item, percent, message)

    def to_dict(self) -> dict:
        return asdict(self)
```

- [ ] **Step 4: 跑测试确认通过** → 5 passed
- [ ] **Step 5: 提交** → `git add -A && git commit -m "feat: 新增进度事件模型，为实时进度条提供统一数据结构"`

---

## Task 2: 扫描与执行支持进度回调

**Files:**
- Modify: `src/desktop_organizer/scanner.py`（`scan` 签名）
- Modify: `src/desktop_organizer/executor.py`（`execute` / `rollback` 签名）
- Test: `tests/test_progress.py`（追加）

**Interfaces:**
- Produces: `scan(root, *, max_depth=1, follow_symlinks=False, on_progress=None)`；`execute(plan, dry_run=True, *, allow_user_dirs=None, capture_icons=None, progress_cb=None)`；`rollback(journal_id, *, allow_user_dirs=None, restore_icons=True, progress_cb=None)`。回调签名统一 `(done: int, total: int, label: str) -> None`。

- [ ] **Step 1: 追加失败测试**

```python
def _fake_plan(tmp_path, count):
    from desktop_organizer.model import Plan, PlanAction
    actions = []
    for i in range(count):
        src = tmp_path / f"f{i}.txt"
        src.write_text("x", encoding="utf-8")
        actions.append(PlanAction(action_id=f"a{i}", src=str(src),
                                  dst=str(tmp_path / "out" / f"f{i}.txt")))
    return Plan(plan_id="p", root=str(tmp_path), created_at="now", actions=actions)

def test_scan_reports_progress_for_every_item(tmp_path) -> None:
    from desktop_organizer import scanner
    for i in range(3):
        (tmp_path / f"a{i}.txt").write_text("x", encoding="utf-8")
    seen = []
    scanner.scan(str(tmp_path), max_depth=1, on_progress=lambda d, t, s: seen.append((d, t)))
    assert seen and seen[-1][0] == seen[-1][1]

def test_scan_without_callback_still_works(tmp_path) -> None:
    from desktop_organizer import scanner
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert scanner.scan(str(tmp_path), max_depth=1)

def test_execute_reports_progress_per_action(tmp_path) -> None:
    from desktop_organizer import executor
    plan = _fake_plan(tmp_path, 3)
    seen = []
    executor.execute(plan, dry_run=False, allow_user_dirs=True,
                     progress_cb=lambda d, t, s: seen.append((d, t)))
    assert seen[-1] == (3, 3)

def test_progress_callback_exception_does_not_break_scan(tmp_path) -> None:
    from desktop_organizer import scanner
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    def boom(_d, _t, _s):
        raise RuntimeError("前端炸了")
    assert scanner.scan(str(tmp_path), max_depth=1, on_progress=boom)

def test_progress_callback_exception_does_not_break_execute(tmp_path) -> None:
    from desktop_organizer import executor
    plan = _fake_plan(tmp_path, 2)
    def boom(_d, _t, _s):
        raise RuntimeError("前端炸了")
    res = executor.execute(plan, dry_run=False, allow_user_dirs=True, progress_cb=boom)
    assert res.applied == 2
```

- [ ] **Step 2: 跑测试确认失败** → 预期 `TypeError: scan() got an unexpected keyword argument 'on_progress'`
- [ ] **Step 3: 最小实现** —— 三个函数各加参数；内部用一个安全包装：

```python
def _safe_progress(cb, done: int, total: int, label: str) -> None:
    if cb is None:
        return
    try:
        cb(done, total, label)
    except Exception:  # noqa: BLE001 - 进度上报失败绝不能影响业务
        pass
```

`scan` 在遍历每个条目后调 `_safe_progress(on_progress, idx, total, item.name)`；`execute` 在 `_apply_one` 之后调；`rollback` 在每项处理后调。

- [ ] **Step 4: 跑测试确认通过**，再跑全量确认 193 旧测试仍绿
- [ ] **Step 5: 提交** → `git commit -m "feat: 扫描与执行支持进度回调，回调异常不影响业务"`

---

## Task 3: 路径校验与自由去向（单行 + 批量）

**Files:**
- Create: `src/desktop_organizer/targetdir.py`
- Modify: `src/desktop_organizer/bridge.py`
- Test: `tests/test_target_dir.py`

**Interfaces:**
- Produces: `targetdir.validate(target_dir: str, root: str) -> tuple[bool, str]`（返回 `(ok, normalized_or_reason)`）
- Produces: `Bridge.set_target_dir(path: str, target_dir: str) -> dict`、`Bridge.set_target_dir_bulk(paths: list[str], target_dir: str) -> dict`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from desktop_organizer import targetdir

@pytest.mark.parametrize("bad", [
    "", "   ", "..", "../x", "../../Windows", "foo/../../bar",
    "C:\\Windows", "/etc", "a:b", "a?b", "a*b", "a<b", "a|b", "a\"b",
])
def test_rejects_illegal_target(bad) -> None:
    ok, reason = targetdir.validate(bad, root="C:/tmp/root")
    assert ok is False
    assert reason

@pytest.mark.parametrize("good,expected", [
    ("2026/专案组", "2026/专案组"),
    ("临时脚本", "临时脚本"),
    ("a/b/c", "a/b/c"),
    ("a//b", "a/b"),
])
def test_accepts_legal_target(good, expected) -> None:
    ok, value = targetdir.validate(good, root="C:/tmp/root")
    assert ok is True
    assert value == expected.replace("/", "\\") or value == expected

def test_rejects_absolute_escape_after_normpath(tmp_path) -> None:
    ok, _ = targetdir.validate("x/../../..", root=str(tmp_path))
    assert ok is False
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 `targetdir.validate`**

```python
"""自由去向目录的校验。所有用户输入都必须过这一关。"""
from __future__ import annotations

import os

_BAD_CHARS = set('<>:"|?*')
_MAX_LEN = 120


def validate(target_dir: str, root: str) -> tuple[bool, str]:
    raw = (target_dir or "").strip()
    if not raw:
        return False, "去向不能为空"
    if len(raw) > _MAX_LEN:
        return False, f"去向太长（超过 {_MAX_LEN} 字符）"
    if any(ch in _BAD_CHARS for ch in raw):
        return False, '去向不能包含 < > : " | ? * 这些字符'
    if raw.startswith(("/", "\\")) or os.path.isabs(raw) or (len(raw) > 1 and raw[1] == ":"):
        return False, "去向必须是相对路径，不能是绝对路径或盘符路径"
    normalized = os.path.normpath(raw.replace("/", os.sep))
    if normalized in (".", "..") or normalized.startswith(".." + os.sep) or ".." in normalized.split(os.sep):
        return False, "去向不能包含 .. 上跳，不能越出整理目录"
    return True, normalized
```

- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: Bridge 接入**（同一任务内）

```python
def set_target_dir(self, path: str, target_dir: str) -> dict[str, Any]:
    return self._apply_target([path], target_dir)

def set_target_dir_bulk(self, paths: list[str], target_dir: str) -> dict[str, Any]:
    return self._apply_target(list(paths or []), target_dir)

def _apply_target(self, paths: list[str], target_dir: str) -> dict[str, Any]:
    from . import targetdir as _td, guard
    ok, value = _td.validate(target_dir, self.root)
    if not ok:
        return {"ok": False, "error": value, "updated": 0}
    plan = self._plan
    if plan is None:
        return {"ok": False, "error": "请先生成整理计划", "updated": 0}
    wanted = {os.path.normcase(os.path.abspath(p)) for p in paths}
    updated = 0
    new_actions = []
    for action in plan.actions:
        if os.path.normcase(os.path.abspath(action.src)) in wanted:
            dst_dir = os.path.join(self.root, value)
            try:
                guard.assert_safe(dst_dir, allow_user_dirs=self._permitted())
            except guard.GuardError as exc:
                return {"ok": False, "error": str(exc), "updated": 0}
            new_actions.append(dataclasses.replace(
                action, dst=os.path.join(dst_dir, os.path.basename(action.src))))
            updated += 1
        else:
            new_actions.append(action)
    self._plan = dataclasses.replace(plan, actions=new_actions)
    return {"ok": True, "error": "", "updated": updated, "target_dir": value}
```

- [ ] **Step 6: 追加 bridge 测试**（合法改一行 / 批量改多行 / 非法不改变 plan / 未生成计划时报错）
- [ ] **Step 7: 跑测试 → 全量绿 → 提交**

---

## Task 4: AI 配置持久化

**Files:**
- Modify: `src/desktop_organizer/settings.py`
- Test: `tests/test_ai_assistant.py`（配置部分）

**Interfaces:**
- Produces: `settings.ai_config(path=None) -> AIConfig`；`settings.set_ai_config(cfg, path=None) -> AIConfig`；`settings.ai_config_dict(path=None) -> dict`（**读给前端时 api_key 打码**）

- [ ] **Step 1: 写失败测试**

```python
def test_ai_config_defaults_to_off(tmp_path) -> None:
    from desktop_organizer import settings
    cfg = settings.ai_config(tmp_path / "s.json")
    assert cfg.provider == "off"
    assert cfg.api_key == ""

def test_ai_config_roundtrip(tmp_path) -> None:
    from desktop_organizer import settings
    from desktop_organizer.ai_assistant import AIConfig
    p = tmp_path / "s.json"
    settings.set_ai_config(AIConfig(provider="gemini", api_key="k1",
                                    model="gemini-2.5-flash"), p)
    cfg = settings.ai_config(p)
    assert cfg.provider == "gemini" and cfg.api_key == "k1"

def test_ai_config_dict_masks_api_key(tmp_path) -> None:
    from desktop_organizer import settings
    from desktop_organizer.ai_assistant import AIConfig
    p = tmp_path / "s.json"
    settings.set_ai_config(AIConfig(provider="gemini", api_key="secret-value"), p)
    d = settings.ai_config_dict(p)
    assert "secret-value" not in str(d)

def test_corrupt_ai_config_falls_back_to_off(tmp_path) -> None:
    from desktop_organizer import settings
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    assert settings.ai_config(p).provider == "off"
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**（复用既有 `_load` / 原子写；新增 `_AI_KEY = "ai"`；`ai_config_dict` 把 key 换成 `"***"` 或空串并附 `has_key: bool`）
- [ ] **Step 4: 跑测试通过**
- [ ] **Step 5: 提交** → `git commit -m "feat: AI 配置持久化，读给前端时对 API Key 打码"`

---

## Task 5: AI 助手核心

**Files:**
- Create: `src/desktop_organizer/ai_assistant.py`
- Test: `tests/test_ai_assistant.py`

**Interfaces:**
- Produces: `AIConfig`、`FileMetaBrief`、`AISuggestion`（字段严格照 §8.2）
- Produces: `to_briefs(items: list[FileItem]) -> list[FileMetaBrief]`
- Produces: `analyze(items, cfg, *, store=None, timeout=10.0, transport=None) -> tuple[list[AISuggestion], bool, str]`（`(suggestions, degraded, reason)`）
- Produces: `build_payload(briefs) -> dict`（脱敏白名单，供测试断言）

- [ ] **Step 1: 写失败测试（含脱敏与降级）**

```python
import json
from pathlib import Path
from desktop_organizer import ai_assistant as ai
from desktop_organizer.model import FileItem


def _item(tmp_path, name="a.jpg", ext=".jpg", size=100, mtime=1.0):
    p = tmp_path / name
    p.write_text("x", encoding="utf-8")
    return FileItem(path=str(p), name=name, ext=ext, size=size, mtime=mtime,
                    atime=mtime, is_dir=False, readonly=False,
                    cloud_placeholder=False, skipped_reason="")


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
    def boom(_payload):
        raise TimeoutError("网络超时")
    cfg = ai.AIConfig(provider="gemini", api_key="k")
    sug, degraded, reason = ai.analyze([_item(tmp_path)], cfg, transport=boom)
    assert degraded is True and "超时" in reason
    assert len(sug) == 1


def test_malformed_json_degrades(tmp_path) -> None:
    cfg = ai.AIConfig(provider="gemini", api_key="k")
    sug, degraded, _ = ai.analyze([_item(tmp_path)], cfg,
                                  transport=lambda _p: "<html>not json</html>")
    assert degraded is True and len(sug) == 1


def test_successful_gemini_response_is_parsed(tmp_path) -> None:
    body = json.dumps({"suggestions": [
        {"path": str(tmp_path / "a.jpg"), "target_dir": "2026财务/票据",
         "category": "图片", "confidence": 0.9, "reason": "票据扫描件"}]})
    cfg = ai.AIConfig(provider="gemini", api_key="k")
    sug, degraded, _ = ai.analyze([_item(tmp_path)], cfg, transport=lambda _p: body)
    assert degraded is False
    assert sug[0].target_dir == "2026财务/票据"


def test_ai_target_dir_must_be_relative(tmp_path) -> None:
    body = json.dumps({"suggestions": [
        {"path": str(tmp_path / "a.jpg"), "target_dir": "C:\\\\Windows",
         "category": "图片", "confidence": 0.9, "reason": "坏建议"}]})
    cfg = ai.AIConfig(provider="gemini", api_key="k")
    sug, degraded, _ = ai.analyze([_item(tmp_path)], cfg, transport=lambda _p: body)
    assert degraded is True  # 非法去向整批降级，绝不带进计划
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 `ai_assistant.py`**（要点）
  - `to_briefs`：只取 `path/name/ext/size/mtime`，mtime 格式化为 `YYYY-MM-DD`的字符串另存 `mtime_text`？——**不**，严格照契约只放 `mtime_ts: float`；格式化放在 prompt 文本里。
  - `build_payload`：`{"items": [{"path","name","ext","size_bytes","mtime_ts"}, ...], "custom_folders": [...]}`
  - `_gemini_transport(cfg, payload, timeout)`：`POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}`，body 用 `contents[0].parts[0].text` 放 prompt JSON + `system_instruction`。
  - `_openai_transport(cfg, payload, timeout)`：`POST {base_url}/chat/completions`，`response_format={"type": "json_object"}`。
  - 两者都返回**文本**，统一交给 `_parse_suggestions(text)`；任何异常在 `analyze` 里捕获 → 降级。
  - 降级路径：`[AISuggestion(path=i.path, target_dir=classify(i, store).target_dir, category=..., confidence=..., reason="本地规则引擎（AI 未启用）") for i in items]`，并 `_log_degraded(reason)` 写 `logs/ai.log`。
  - `_parse_suggestions` 对每条校验 `target_dir`：调 `targetdir.validate`，任一非法 → 抛 `ValueError` → 整批降级（宁可全用本地规则，也不把坏建议混进计划）。

- [ ] **Step 4: 跑测试通过**
- [ ] **Step 5: 提交** → `git commit -m "feat: AI 助手支持 Gemini 与 OpenAI 兼容协议，未配置或失败时静默降级"`

---

## Task 6: Bridge 接入 AI 与推流

**Files:**
- Modify: `src/desktop_organizer/bridge.py`
- Test: `tests/test_ai_assistant.py`、`tests/test_progress.py`

**Interfaces:**
- Produces: `Bridge.set_window(window)`、`Bridge.notify_progress(stage, current, total, current_item="", message="")`、`Bridge.ai_settings()`、`Bridge.save_ai_settings(provider, api_key="", base_url="", model="")`、`Bridge.ai_suggest()`、`Bridge.progress()`

- [ ] **Step 1: 写失败测试**（用假 window 记录 evaluate_js 调用）

```python
class _FakeWindow:
    def __init__(self):
        self.calls = []
    def evaluate_js(self, script):
        self.calls.append(script)


def test_notify_progress_calls_evaluate_js(tmp_path) -> None:
    from desktop_organizer.bridge import Bridge
    b = Bridge(root=str(tmp_path), store_path=tmp_path / "p.json",
               settings_path=tmp_path / "s.json")
    w = _FakeWindow()
    b.set_window(w)
    b.notify_progress("scan", 1, 4, current_item="a.txt")
    assert w.calls and "onProgress" in w.calls[0]


def test_notify_progress_swallows_broken_window(tmp_path) -> None:
    from desktop_organizer.bridge import Bridge
    b = Bridge(root=str(tmp_path), store_path=tmp_path / "p.json",
               settings_path=tmp_path / "s.json")
    class Bad:
        def evaluate_js(self, _s):
            raise RuntimeError("窗口没了")
    b.set_window(Bad())
    b.notify_progress("apply", 1, 2)  # 不得抛出


def test_progress_snapshot_has_stage_and_percent(tmp_path) -> None:
    from desktop_organizer.bridge import Bridge
    b = Bridge(root=str(tmp_path), store_path=tmp_path / "p.json",
               settings_path=tmp_path / "s.json")
    d = b.progress()
    assert "stage" in d and "percent" in d


def test_ai_suggest_without_key_returns_local_and_marks_degraded(tmp_path) -> None:
    from desktop_organizer.bridge import Bridge
    (tmp_path / "a.jpg").write_text("x", encoding="utf-8")
    b = Bridge(root=str(tmp_path), store_path=tmp_path / "p.json",
               settings_path=tmp_path / "s.json")
    b.scan()
    res = b.ai_suggest()
    assert res["degraded"] is True
    assert res["total"] >= 1


def test_ai_settings_never_returns_raw_key(tmp_path) -> None:
    from desktop_organizer.bridge import Bridge
    b = Bridge(root=str(tmp_path), store_path=tmp_path / "p.json",
               settings_path=tmp_path / "s.json")
    b.save_ai_settings("gemini", api_key="super-secret")
    assert "super-secret" not in str(b.ai_settings())
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现** —— `set_window` 存 `self._window`；`notify_progress` 构造 `ProgressEvent.create(...)` 并 `evaluate_js(f"window.onProgress && window.onProgress({json.dumps(ev.to_dict(), ensure_ascii=False)})")`，`except Exception: pass`；`apply()` / `rollback()` / `scan()` 内部传入 `progress_cb=lambda d, t, s: self.notify_progress(...)`；`ai_suggest()` 调 `ai_assistant.analyze` 并把结果转成 rows 可用的 dict 列表。
- [ ] **Step 4: 跑测试通过 → 全量绿**
- [ ] **Step 5: 提交** → `git commit -m "feat: 桥接层接入进度推流与 AI 建议，推流异常不影响业务"`

---

## Task 7: Chromium 瘦身与窗口注入

**Files:**
- Modify: `src/desktop_organizer/gui_web.py`
- Test: `tests/test_gui_web_config.py`（追加）

**Interfaces:**
- Produces: `gui_web.chromium_args() -> str`（返回注入用的参数串）、`gui_web.apply_chromium_env() -> None`

- [ ] **Step 1: 写失败测试**

```python
def test_chromium_args_disable_gpu_and_limit_renderers() -> None:
    from desktop_organizer import gui_web
    args = gui_web.chromium_args()
    assert "--disable-gpu" in args
    assert "--renderer-process-limit=1" in args
    assert "--disable-background-networking" in args

def test_apply_chromium_env_sets_variable(monkeypatch) -> None:
    from desktop_organizer import gui_web
    monkeypatch.delenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", raising=False)
    gui_web.apply_chromium_env()
    import os
    assert "--disable-gpu" in os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"]
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现** —— `chromium_args()` 返回那句参数串；`apply_chromium_env()` 设 `os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"]`；`run()` 开头调 `apply_chromium_env()`，`create_window` 之后调 `bridge.set_window(window)`。
- [ ] **Step 4: 跑测试通过**
- [ ] **Step 5: 提交** → `git commit -m "feat: 注入 Chromium 瘦身参数并挂接窗口实例以便推流"`

---

## Task 8: 三栏现代化界面

**Files:**
- Modify: `src/desktop_organizer/web/index.html`
- Test: `tests/test_web_assets.py`（追加）

**Interfaces:**
- 消费：`window.onProgress(event)`、`api.progress()`、`api.set_target_dir`、`api.set_target_dir_bulk`、`api.ai_suggest`、`api.ai_settings`、`api.save_ai_settings`

- [ ] **Step 1: 追加静态检查测试**

```python
def test_progress_panel_exists() -> None:
    html = _html()
    assert 'id="progressPanel"' in html
    assert 'id="progressBar"' in html
    assert "window.onProgress" in html

def test_ai_drawer_and_settings_exist() -> None:
    html = _html()
    assert 'id="aiDrawer"' in html
    assert 'id="btnAiSuggest"' in html
    assert "ai_suggest" in html

def test_rows_have_editable_target_dir() -> None:
    html = _html()
    assert "data-target" in html
    assert "set_target_dir" in html

def test_bulk_target_controls_exist() -> None:
    html = _html()
    assert 'id="bulkTarget"' in html
    assert "set_target_dir_bulk" in html

def test_donut_canvas_exists() -> None:
    html = _html()
    assert 'id="donut"' in html

def test_no_external_network_resources() -> None:  # 已有，保持
    ...
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 重构 `index.html`** —— 三栏 grid；左栏 Canvas 环形图（按 `category` 汇总 `size` 画弧）+ 类别筛选 + 写盘许可 + AI 设置入口；中栏搜索 + 批量去向 + 进度面板（`window.onProgress` 更新宽度与百分比）+ 表格（去向列是可编辑输入）+ 5 按钮；右栏 Copilot（模型状态、智能分析、建议卡片、采纳）。
- [ ] **Step 4: 跑测试通过 → 全量绿**
- [ ] **Step 5: 截图验证**（正确拍法：`ShowWindow` + `SetForegroundWindow` + `CopyFromScreen`）
- [ ] **Step 6: 提交** → `git commit -m "feat: 三栏现代化界面，含环形图、实时进度、Copilot 抽屉与行内去向编辑"`

---

## Task 9: 端到端验收与交付

- [ ] **Step 1: 全量测试** → 期望 ≥ 205 passed, 0 failed，记录实际数字
- [ ] **Step 2: 沙箱 e2e** —— 造样本 → 设自由去向 `2026/专案组` → 执行 → 校验落点 → 回滚 → 校验复原
- [ ] **Step 3: 非法去向实测** —— `../../Windows` 必须被拒且零副作用
- [ ] **Step 4: 内存实测** —— 启动后稳定 5s，统计 `DesktopOrganizer` + 子 `msedgewebview2` 的 WorkingSet 之和，如实记录
- [ ] **Step 5: 重建 exe**（先停进程、备份 `data`）并记录体积与启动耗时
- [ ] **Step 6: 文档同步** —— `progress.md`、交付报告、进度看板、`decisions.md`（新增 D20：AI 助手走本地优先、脱敏白名单；D21：进度推流 + 轮询兜底；D22：自由去向的校验链）
- [ ] **Step 7: 提交** → `git commit -m "docs: 同步 AI 助手与三栏界面的交付状态"`

---

## 自检结论

- **spec 覆盖**：§8.2 契约 → Task 1/4/5；§8.3 脱敏 → Task 5；§8.4 降级 → Task 5；§8.5 推流 → Task 1/2/6/7；§8.6 自由去向 → Task 3；§8.7 内存 → Task 7/9；§8.8 UI → Task 8；§8.9 红线 → 各任务的 Review Focus 测试；§8.10 验收 → Task 9。
- **占位符扫描**：无 TBD/TODO，每个代码步骤都有可运行代码。
- **类型一致性**：`ProgressEvent` 字段与 §8.2 一致；`AIConfig` / `AISuggestion` / `FileMetaBrief` 字段与 §8.2 逐字一致；`set_target_dir` 返回 `{ok, error, updated, target_dir}` 在 Task 3 与 Task 8 前端一致。
