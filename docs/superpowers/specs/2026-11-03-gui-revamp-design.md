# GUI 革新设计稿（2026-11-03）

> 目标：把现有「一屏表格 + 右侧统计」的界面重排成 **阶段仪表盘 + 常驻顾问侧栏**，并补齐三件事：进度反馈、本地规则顾问、行内自定义文件夹名。
> 本稿已与用户逐项确认，确认结论见 §0。实现前需用户对本文档做一次终审。

## 0. 已确认的决策

| 决策点 | 结论 | 来源 |
|---|---|---|
| AI 顾问的智能来源 | **本地规则引擎**，零网络、零延迟、零费用 | 用户选择 |
| 文件夹自主命名 | **每行单独改**（其余类别保持默认） | 用户选择 |
| 整体形态 | **方案 B：分区仪表盘 + 常驻顾问侧栏** | 用户选择 |
| 进度条的精度 | **只要一个百分比**（不需要当前文件名、不需要剩余条数） | 用户选择 |
| 顾问建议的行为 | **说了就能一键做**（每条建议带采纳按钮，点了直接改表格状态） | 用户选择 |

## 1. 布局

三栏：

```
顶栏：logo · 标题 · [● 用户目录写入：开/关] · 桌面路径徽标
左栏（窄，约 190px）：阶段导航 + 统计卡
中栏（自适应）：进度条 → 搜索/排序工具栏 → 文件表格（行内可改目标目录）→ 5 个操作按钮
右栏（固定约 300px）：顾问侧栏
```

- **左栏阶段导航**：四个阶段（扫描 / 预览 / 执行 / 回滚），每个阶段显示「未开始 / 进行中 xx% / 完成」，与进度条同一数据源。统计卡（扫描文件 / 选中移动 / 高置信 / 待确认）挪到左栏底部。
- **中栏**：顶部是进度条（一条横向条形 + 右侧百分比数字）；下面是既有的搜索框、排序下拉、全选/全不选/已选计数；再下面是表格；底部是原来那 5 个按钮。表格新增最右一列「目标目录」，内容是输入框。
- **右栏顾问**：标题「顾问建议」，下面是建议卡片列表，每条含一句话说明 + 「采纳」按钮 + 「忽略」链接。被忽略的折叠进底部「已忽略 N 条」。
- 响应式下限：窗口最小 940×640；左栏与右栏在窗口宽度 < 1080 时收窄（右栏 260px、左栏 160px）。

## 2. 数据流

### 2.1 进度（只要百分比）

pywebview 的 JS 调用是同步等待的，调用中途无法推事件，因此用**轮询**：

- `scanner.scan(root, *, max_depth=1, follow_symlinks=False, on_progress=None)`
- `executor.execute(plan, dry_run=True, *, allow_user_dirs=None, capture_icons=None, on_progress=None)`
- `executor.rollback(journal_id, *, allow_user_dirs=None, restore_icons=True, on_progress=None)`
- 回调签名 `on_progress(done: int, total: int, label: str) -> None`；**不传时行为与现在完全一致**（关键约束：不破坏既有 193 个测试）。
- 回调内部抛异常必须被吞掉——进度条坏了不能影响整理本身。
- `bridge` 维护 `self._progress = {"stage": "...", "done": 0, "total": 0, "running": bool}`；操作开始置 running，结束后 `running=False` 且 `done=total`。
- 新增 `bridge.progress() -> dict`；前端在点击按钮后 `setInterval(200ms)` 轮询，完成即清定时器。
- 百分比计算：`total<=0` 时显示 100%，否则 `round(done/total*100)`。

### 2.2 顾问

新增 `src/desktop_organizer/advisor.py`，无副作用纯函数：

```python
def suggest(rows: list[dict], store) -> list[dict]
```

每条建议结构：`{"id": str, "kind": str, "title": str, "detail": str, "action": dict, "paths": list[str]}`。`action` 是给前端执行的指令，`kind` 决定「采纳」按钮调用哪个桥接方法：

| kind | 触发规则 | 文案 | 采纳动作 |
|---|---|---|---|
| `skip_temp` | 名字以 `~$` 开头，或扩展名 ∈ `.tmp/.part/.crdownload` | 「发现 N 个临时/未完成下载文件，建议不要动它们」 | 取消这些行的勾选 |
| `skip_cloud` | `cloud_placeholder is True` | 「N 个云盘占位文件，移动会触发下载」 | 取消这些行的勾选 |
| `use_history` | `store.lookup(item)` 命中且与当前建议不同 | 「你上次把这类文件放到 X」 | 把这些行的目标目录改为历史值 |
| `big_files` | 单文件 ≥ 100 MB | 「N 个文件超过 100MB，移动会久一点」 | 只提示，无按钮（`action` 为空） |
| `merge_same_ext` | 同扩展名 ≥ 5 个且目标目录 ≥ 2 种 | 「N 个 .jpg 会散落到 M 个目录，要不要统一到 X」 | 把这些行目标目录统一为出现次数最多的那个 |
| `low_confidence` | `confidence < 0.55` | 「N 个我不太确定，建议逐个确认」 | 只高亮这些行，不改勾选 |

- 每条建议有稳定 `id`（`kind` + 排序后的 path 哈希前 8 位），供前端折叠/忽略。
- 忽略状态只存前端内存（同一会话内不再弹），不写磁盘——避免污染偏好文件。
- 规则内部任何异常都 `continue`，**顾问挂了不能影响扫描/预览**。
- 空列表或没有建议时，侧栏显示「暂时没有建议，列表看起来挺整齐」。

### 2.3 行内改名

- 表格最右列是 `<input data-target value="{target_dir}">`。
- 输入框失焦或按回车时调 `bridge.rename_target(path, target_dir) -> {"ok": bool, "error": str, "target_dir": str}`。
- 校验（在 Python 侧，前端只负责显示红框）：非空、不含 `..`、不含盘符冒号、不是绝对路径、长度 ≤ 120、不含 Windows 保留字符 `<>:"|?*`。
- 合法时：更新内存中该 action 的 `dst`（`os.path.join(root, *target_dir.split('/'))`，再走一次 `guard.assert_safe`），并调 `store.remember_custom_dir(item, target_dir)` 落盘。
- 下次同类文件：`classify` / `planner` 计算目标目录前先查 `store.custom_dir_for(item)`，命中就用你的名字（优先级高于类别默认，低于「显式写在计划里」）。
- 改名只改「将要移动到哪」，**不触碰磁盘上任何现有文件**。

### 2.4 存储扩展（`store.py`）

偏好文件新增顶层键 `dir_overrides`：

```json
{
  "version": 1,
  "ext_overrides": { ... },
  "name_overrides": { ... },
  "dir_overrides": { ".jpg": "图片/我的相册", "社会实践1.jpg": "截图" },
  "rules": [],
  "stats": { ... }
}
```

- 键规则与既有 `_key(item)` 一致：先尝试文件名（`name_overrides` 风格），再退到扩展名。即：同名文件记 `dir_overrides["社会实践1.jpg"]`，同扩展名记 `dir_overrides[".jpg"]`。
- 读取时先精确名字，再扩展名。
- 由于 `dir_overrides` 与既有 `ext_overrides` 的结构相似，实现上复用同一套 `_load/_save/原子写` 逻辑，不新增文件。

## 3. 改动清单

| 文件 | 改动 |
|---|---|
| `src/desktop_organizer/web/index.html` | 三栏布局重写；进度条；顾问侧栏；行内改名输入框；阶段导航 |
| `src/desktop_organizer/bridge.py` | 新增 `progress()`、`advisor()`、`rename_target()`、`apply_suggestion(sid)`；`scan/plan/apply/rollback` 透传 `on_progress` |
| `src/desktop_organizer/scanner.py` | `scan(...)` 加可选 `on_progress` |
| `src/desktop_organizer/executor.py` | `execute/rollback` 加可选 `on_progress` |
| `src/desktop_organizer/advisor.py` | **新建**，6 条规则 |
| `src/desktop_organizer/store.py` | `dir_overrides` 读写 + `remember_custom_dir()` + `custom_dir_for()` |
| `src/desktop_organizer/planner.py` | 目标目录计算前查 `custom_dir_for` |
| `tests/test_advisor.py` | **新建**，每规则一条 |
| `tests/test_progress.py` | **新建**，进度回调与轮询载荷 |
| `tests/test_rename_target.py` | **新建**，合法/非法名 |
| `tests/test_store.py` | 补 `dir_overrides` 用例 |
| `tests/test_web_assets.py` | 补「进度条元素存在」「顾问侧栏存在」「每行有 data-target 输入框」「无外部网络资源」 |

## 4. 错误处理

- 进度回调异常 → 吞掉，继续业务。
- 顾问规则异常 → 跳过该条，继续其余规则。
- 改名非法 → 返回 `{"ok": false, "error": "原因"}`，前端输入框标红、保留原值，**plan 不变**。
- 改名目标被守卫拒绝（写到系统目录）→ 同样 `ok: false`，错误里带守卫原因。
- 所有新增桥接方法必须返回 JSON 可序列化结构（沿用现有 `_row()` 的风格）。

## 5. 测试策略

- **顾问**：每条规则一个夹具（构造 rows + 假 store）→ 断言 `kind` 与 `paths` 数量、`action` 内容；再补一条「规则内部抛异常不影响其他规则」。
- **进度**：断言 `on_progress` 调用次数 = 条目数；首次 `done=0`、末次 `done=total`；不传回调时不报错；`bridge.progress()` 在空闲时返回 `running: False`。
- **改名**：合法名写入后新建 Bridge 能读到；非法名（空 / `..` / `C:\` / 含 `?`）全部被拒且 plan 的 `dst` 不变。
- **前端静态**：`test_web_assets.py` 用正则确认 `id="progressBar"`、`id="advisorList"`、`data-target` 存在，且 HTML 内无 `http://` / `https://`。
- 真机：沙箱里造 20 个样本 → 走「扫描→预览→执行→回滚」，肉眼确认进度条走完、顾问建议合理、改名生效。

## 6. 明确不做（YAGNI）

- 不做云端大模型顾问（用户已选本地规则）。
- 不做顾问对话式聊天，只做建议列表。
- 不做进度条的「当前文件名 / 剩余时间」展示（用户明确只要百分比）。
- 不做拖拽排序、不做多显示器坐标裁剪（遗留 P8 单独记录）。
- 不引入任何前端框架，仍是单文件自绘 HTML。

## 7. 验收标准

1. 扫描 250 个图标时，进度条从 0% 到 100% 递增且不卡界面。
2. 顾问至少能给出 3 类建议，点「采纳」后表格勾选/目标目录立刻变化。
3. 任一行目标目录改成「我的相册」，执行后文件真的进 `Desktop\我的相册\...`；回滚能回原位。
4. 同上改名后，扫描另一个 `.jpg` 文件时默认目标目录变为「我的相册」。
5. 全量测试 ≥ 200 passed，0 failed；既有 193 个测试不被破坏。
6. 快捷方式启动仍是 exe 路径，冷启动轻载 < 2s。

---

# 8. 第二版需求（2026-11-03 16:45 追加，来源：用户顾问「哈基米」需求书）

> 本节覆盖 §0 的三项结论，**新需求优先**。冲突与取舍逐一列明，不留含糊。

## 8.1 与第一版的冲突与裁决

| 冲突点 | 第一版（用户已拍板） | 第二版（顾问需求书） | 裁决 |
|---|---|---|---|
| 进度条内容 | 只要一个百分比 | `ProgressEvent` 含 `stage / current / total / current_item / percent / message`，且用 `evaluate_js` **推流**而非轮询 | 采用第二版；本版不删百分比，只是多给两个字段 |
| AI 顾问来源 | 本地规则引擎，零网络 | Gemini + OpenAI 兼容，可自由命名去向；未配置时降级本地规则 | 采用第二版，但**默认 `provider="off"`**，即用户不改配置时行为等于第一版 |
| 顾问呈现 | 不主动弹窗 | 右栏 Copilot 抽屉，流式建议卡片 | 采用第二版；抽屉常驻，无建议时折叠 |
| 去向命名 | 每行单独改 | 支持自由相对路径（两级）+ **批量应用** | 两者都做：单行输入框 + 工具栏批量应用 |

## 8.2 数据契约（与需求书一致，逐字对齐）

```python
@dataclass
class AIConfig:
    provider: Literal["gemini", "openai_compatible", "off"] = "off"
    api_key: str = ""
    base_url: str = ""
    model: str = "gemini-2.5-flash"
    custom_folders: list[str] = field(default_factory=lambda: [
        "工作资料/本周待办", "常用软件/安装包", "媒体素材/临时截图", "学习笔记/文档归档"
    ])

@dataclass(frozen=True)
class FileMetaBrief:
    path: str
    name: str
    ext: str
    size_bytes: int
    mtime_ts: float

@dataclass
class AISuggestion:
    path: str
    target_dir: str
    category: str
    confidence: float
    reason: str

@dataclass(frozen=True)
class ProgressEvent:
    stage: Literal["scan", "plan", "ai_analyzing", "apply", "rollback"]
    current: int
    total: int
    current_item: str
    percent: float
    message: str
```

## 8.3 脱敏硬约束

- `FileMetaBrief` 只允许包含 `path / name / ext / size_bytes / mtime_ts` 五个字段。
- `ai_assistant.py` 中**不得出现任何 `open(` / `read_text(` / `read_bytes(` 调用**（对文件内容的读取）。由 `tests/test_ai_assistant.py::test_module_never_opens_file_contents` 用源码扫描断言。
- 发给远端的内容只允许是 `FileMetaBrief` 的 JSON；测试拦截 `urllib.request.urlopen` 断言 payload 中不含 `"content"` / `"body"` / `"text"` 键，且不含文件大小之外的内容字段。

## 8.4 降级与超时

- 触发降级：`provider == "off"`、`api_key` 为空、`urllib` 抛任何异常、超时（默认 10s）、返回体非 JSON、JSON 结构不符。
- 降级动作：写一行日志到 `logs/ai.log`，然后**逐个调用 `classify(item, store)`** 得到本地建议，函数返回 `(suggestions, degraded=True, reason=...)`。
- 任何情况下都**不抛出到调用方**——AI 挂了不能影响整理。

## 8.5 进度推流

- `gui_web.py`：`create_window` 之后立刻 `bridge.set_window(window)`；本版**保留轮询接口 `progress()` 作为兜底**（推流失败时前端仍能显示）。
- `bridge.notify_progress(stage, current, total, item_name, message)`：构造 `ProgressEvent`，`percent = 0.0 if total <= 0 else round(current / total * 100, 1)`，执行 `self._window.evaluate_js(f"window.onProgress && window.onProgress({json.dumps(event)})")`，**异常吞掉**。
- `executor.execute(...)` / `rollback(...)` 新增 `progress_cb: Callable[[int, int, str], None] | None = None`，每处理完一个文件调用一次；`scanner.scan(...)` 同时新增 `on_progress`。

## 8.6 自由去向与批量

- 单行：表格 `target_dir` 单元格点击即编辑，回车/失焦提交，走 `bridge.set_target_dir(path, target_dir)`。
- 批量：中栏工具栏「批量设置去向」输入框 + 「应用到选中」按钮，走 `bridge.set_target_dir_bulk(paths, target_dir)`。
- 校验（Python 侧统一做，前端只显示错误）：`os.path.normpath` 后不得以 `..` 开头或包含 `..` 段；不得含盘符（`:`）；不得以 `\` 或 `/` 开头（绝对路径）；不得含 `< > " | ? *`；长度 ≤ 120；非空；最后拼到 root 下再走一次 `guard.assert_safe`。
- 只改内存 `Plan` 的 `dst`，**不落盘**；落盘仍只在「真正执行移动」+ 二次确认后。

## 8.7 内存瘦身

```python
os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
    "--disable-gpu --disable-background-networking --disable-sync "
    "--disable-extensions --renderer-process-limit=1 "
    "--disable-features=CalculateNativeWinOcclusion,SpareRendererForSitePerProcess "
    "--js-flags=--lite-mode --disable-component-update"
)
```
- 必须在 `create_window` / `start()` 之前设置。
- 实测口径：`Get-Process DesktopOrganizer | Measure WorkingSet` + 其子进程 `msedgewebview2` 的 WorkingSet 之和，启动后稳定 5s 取值。
- **诚实交付**：目标 < 75MB；若未达标，写实测值与原因到交付报告遗留项，不谎报达标。

## 8.8 三栏 UI（第二版）

- 左栏 240px：空间占用环形图（Canvas，按类别汇总 size）+ 类别快捷筛选 + 写盘许可开关 + 「AI 助手设置」入口。
- 中栏：搜索 + 批量去向工具条 + 进度条面板（平时隐藏，任务时展开，CSS 渐变流光）+ 文件列表（勾选框 / 文件名 / 类别 / 置信度 / **可编辑去向输入框**）+ 底部统计与 5 个操作按钮。
- 右栏 300px：Copilot 抽屉（模型状态标签 / 「智能分析」按钮 / 建议卡片流 / 采纳与忽略）。
- 零外网：无 CDN、无外部字体、无外链图标；图标一律 inline SVG。

## 8.9 负向约束（红线）

1. 只传元数据，绝不读文件内容。
2. 任何去向都必须过 `guard.assert_safe`，禁止绝对路径与跨盘。
3. 默认 dry-run：AI 建议与批量修改只改内存 Plan。
4. **既有 193 个测试的断言与逻辑一个字都不改**；新增测试叠加。

## 8.10 第二版验收

1. `python -m pytest tests/ -q` → **≥ 205 passed, 0 failed**。
2. 未配置 AI 时自动降级回本地规则（有单测）。
3. 非法去向 `../../Windows` 被拒；合法 `2026/专案组` 被采纳、执行、并由 WAL 完整回滚（有单测 + 沙箱 e2e）。
4. GUI 显示实时进度与百分比（真机截图）。
5. 内存实测值如实记录（达标或未达标都写）。

