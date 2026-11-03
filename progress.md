# 进度（progress.md）

> 断点续跑的唯一真相。每完成一个子任务立即更新。最后更新：2026-11-03 21:52（北京时间）

## 当前阶段
**按使用频次排序 + DeepSeek 默认顾问已交付：只读解析 Windows UserAssist（ROT13 值名 + 偏移 4 的运行次数）得到「点开过几次」，新增 `by_usage` 排序键（升序 → 最常用落最右）；AI 顾问默认 DeepSeek（留空自动回落 `deepseek-chat` / `https://api.deepseek.com`），system prompt 教会它本软件用法与整理策略。387 绿 + exe 已重建 6,573,109 bytes + 截图确认七键芯片与 DeepSeek 面板**

## 时间预算
| 里程碑 | 计划时段 | 状态 |
|---|---|---|
| M1 需求边界 | 14:00–14:50 | 完成（docs/01-requirements.md） |
| M2 架构+契约 | 14:50–15:50 | 完成（docs/02-architecture.md + 契约三件套冻结） |
| M3 骨架+首次提交 | 15:50–16:50 | 完成（提交 3b6ca84） |
| M4 核心模块 | 16:50–18:20 | 完成（提交 dd688d4，91 绿） |
| M5 红队自测 | 18:20–19:20 | 部分完成（沙箱 e2e 已验，部分红队用例列为遗留） |
| M6 收尾 | 19:40–20:00 | 完成（交付报告 + 看板落盘） |
| GUI 需求（追加） | 19:50–20:17 | 完成（提交 3d04163） |
| 缺陷修复（追加） | 20:45–21:00 | 完成（提交 332e109） |
| 冷启动优化（追加） | 21:00–22:16 | 完成（提交 9f162d3） |
| 火绒拦截处理（追加） | 22:55–23:00 | 完成（临时回退源码模式，提交 ae983d0） |
| 火绒加白验证（追加） | 23:05–23:13 | 完成（dist 已移回、加白生效、实测 5 次分布） |
| 写盘许可开关（追加） | 23:18–23:43 | 完成（提交 212f96b，137 绿，exe 重建） |
| 回滚保序（追加） | 23:49–00:20 | 完成（143 绿，沙箱 e2e 保序通过，exe 重建 6503285 bytes） |
| 回滚全面复原 + 界面检索（追加） | 00:28–00:50 | 完成（提交 b88dd0c，151 绿，沙箱 e2e 四重一致，exe 重建 6507366 bytes） |
| 图标位置真回滚（追加） | 14:48–15:12 | 完成（用户手工关闭自动排列；187 绿；真机写回实测通过） |
| 图标回读校验重试（追加） | 15:10–15:40 | 完成（193 绿；修好用户 4 个跑位的 `社会实践*.jpg`） |
| **GUI 革新 + AI 顾问（追加）** | **16:48–17:20** | **完成（282 绿；进度条/自由去向/批量改向/AI 建议/三栏 UI；exe 重建）** |
| **一键整理图标（追加）** | **18:28–18:52** | **完成（319 绿；三策略/备份可撤销/顶栏下拉+按钮；exe 重建 6556922 bytes）** |
| **越界裁剪 + 实测网格步长（追加）** | **19:44–19:52** | **完成（337 绿；换分辨率不再丢图标；提交 43c62c0；exe 重建 6560039 bytes）** |
| **复合策略 + 类别勾选 + 撤销（追加）** | **20:12–21:03** | **完成（370 绿；六个排序键可多选、按类别勾选、撤销常驻；提交 2ea877f / 0f12c73；exe 重建 6566815 bytes）** |

## 已完成
- [x] 契约三件套：`model.py`、`constants.py`、`guard.py`（含只读通道 check_read_path）
- [x] 核心模块：scanner / classify / rules / store / planner / executor / journal / bridge
- [x] CLI：scan / plan / apply / rollback / journals / gui（apply 默认 dry-run，需 --no-dry-run + --yes）
- [x] GUI：pywebview 6.2.1 + 自绘 HTML（深色玻璃 + 蓝紫渐变），实拍验证通过
- [x] 图标 assets/icon.ico（35752 bytes）+ 桌面快捷方式 `C:\Users\HY\Desktop\Desktop Organizer.lnk`（1924 bytes）
- [x] 修空 journal / 全被拒中文指引 / 回滚清理空目录（332e109）
- [x] GUI 一键全选 / 全不选（332e109）
- [x] 冷启动优化：持久化 WebView2 profile + PyInstaller onedir + 启动器自动优选（9f162d3）
- [x] 修表头竖排 / 按钮被拉宽（全局 button{width:100%} 污染 .mini）
- [x] 火绒信任区加白目录 `dist\DesktopOrganizer`，打包 exe 恢复可用
- [x] 写盘许可开关：`settings.py` + executor/bridge 透传 + 界面右上角开关 + CLI `--allow-user-dirs`（212f96b）
- [x] 回滚保序：journal move 记录带 mtime_ns/atime_ns/size，回滚时 os.utime 复原；`_prune_empty_dirs` 拒绝删除用户目录本体
- [x] 回滚全面复原：journal 同时记 `birthtime_ns`，`_set_birthtime_win` 用 `SetFileTime` 还原创建时间；回滚后 `shellrefresh.notify_after_rollback` 主动通知 shell 重枚举（b88dd0c）
- [x] 界面：按文件名搜索 + 5 种排序（名称/修改时间/大小）+ 扫描后不再默认勾选 + 「全选」只勾当前可见行（b88dd0c）
- [x] 临时 e2e 脚本已删除；CLI rollback 的正确用法是 `rollback --journal <id>`
- [x] 图标位置真回滚：`iconpos.py` 快照/写回 + `gridcheck.py` 格点验收 + executor/bridge/CLI 接线（9b4fd62）
- [x] 图标写回回读校验与重试：`restore_positions` 每轮回读、不符就重建 writer 重试（10 次 × 150ms），始终没出现的单独归入 `absent` 只提示不判失败
- [x] 进度条：`progress.py`（`ProgressEvent`/`safe_report`）+ scanner `on_progress` + executor `progress_cb` + bridge `notify_progress` 推 `window.onProgress`（只显示百分比）
- [x] 自由去向：`targetdir.validate`（拒绝对路径/跨盘/`..`/非法字符）+ bridge 单行 `set_target_dir` 与批量 `set_target_dir_bulk`
- [x] AI 顾问：`ai_assistant.py`（Gemini / OpenAI 兼容、只传元数据、`http.client` 不用 urllib、失败降级本地规则）+ `settings.ai_config*`（api_key 打码）+ bridge `ai_suggest`/`apply_suggestions`/`save_ai_settings`
- [x] WebView2 瘦身：`chromium_args()` / `apply_chromium_env()`（11 个 flag，不含 `--single-process`；已有环境变量追加不覆盖）
- [x] 三栏 UI：左 Donut 空间占用 + 类别筛选、中工作台 + 百分比进度条 + 批量改去向、右 AI 顾问抽屉（服务商/Key/模型/网关/保存/让 AI 提建议/一键采纳）
- [x] 一键整理图标：`layout.py` 三策略（快捷方式优先／分区看板／最近活跃优先）+ 纯坐标写回 + 先备份可撤销 + `bridge` 三方法 + 顶栏下拉/按钮/撤销 toast（e73c05d）
- [x] `iconpos.restored` 口径修正：报本次写回总数，而不是最后一轮重试的数量
- [x] **P8 越界裁剪**：`iconpos.clamp_position` 写回前按当前工作区夹取，越界计数写进 errors（43c62c0）
- [x] **排版步长改由桌面实测推断**：`layout.icon_step_from_positions` 取相邻差众数；实测 75/104，而 `GetSystemMetrics(38/39)`=75/75、`LVM_GETITEMSPACING`=96/81 全是错的
- [x] `executor._restore_icons` 回滚写回前先取当前工作区 bounds（换屏幕后回滚也不丢图标）
- [x] **排版策略拆成可叠加的六个排序键**：`system_first` / `shortcuts_first` / `by_type` / `by_category` / `by_time` / `by_name`，多选按顺序逐层稳定排序；老策略 id 仍兼容
- [x] **修「快捷方式优先从未生效」**：`resolve_icon_path` 依次试原名 / `.lnk` / `.url`，并同时搜用户桌面与公共桌面（`C:\Users\Public\Desktop` 有 38 个，只搜用户桌面会误判成系统图标）
- [x] **修「左上角空一格」**：`bridge.apply_desktop_layout` 显式传 `read_positions` 做回读校验，且判定改按**格子**（75×104）不按像素（写 (12,12)、Shell 吸附成 (11,2)）
- [x] **撤销改成多轮**：`layout.undo_layout(attempts=3)`，每轮重建 writer、间隔 0.6s，不再出现点一次撤销仍旧错位
- [x] 界面：顶栏六个可点选 chip（显示叠加序号）+「一键整理图标」+ 常驻「撤销整理」；工具条「按类别勾选…」+「选中本类别」；顶栏放不下时换行
- [x] 全量测试 **370 passed / 1 skipped**

## 实测数据
| 指标 | 目标 | 实测 | 结论 |
|---|---|---|---|
| **冷启动（当前生效：打包 exe）** | < 2s | **1.56 / 1.70 / 1.77 / 2.22 / 2.49s**（中位 1.77） | 轻载达标，重载略超 |
| 冷启动（重建后单次实测，23:43） | < 2s | 2.0s | 达标边缘 |
| 冷启动（源码模式，兜底） | < 2s | 2.17s | 略超，仅作兜底 |
| 加白后首次启动 | < 2s | 3.26–3.28s | 杀软首扫新 exe，非代码问题 |
| 首屏 t_gui_ready | — | 1916ms → **835ms** | profile 持久化收益 |
| 常驻内存 | 低 | 97.3–105MB | 记录 |
| 安装包体积 | — | exe 6.5MB / dist 49.1MB | 记录 |
| 沙箱 e2e（无许可） | 被拦 | applied=0 failed=164 | 白名单生效 |
| 沙箱 e2e（带许可） | 真实移动 | applied=164（dry-run）/ applied=3 真执行 | 达标 |
| 沙箱 e2e 回滚 | 可回滚 | rolled_back=3，空目录残留 0 | 达标 |
| **回滚保序 e2e（sandbox\e2e-order）** | 顺序复原 | NAMES_SAME=True / MTIME_SAME=True / 残留目录 0 / 根目录在 | 达标 |
| **回滚四重复原 e2e（sandbox\e2e-restore-all）** | 名称/大小/时间全复原 | `NAMES_SAME=True / SIZE_SAME=True / MTIME_SAME=True / BIRTHTIME_SAME=True / LEFTOVER_DIRS=[]` | 达标 |
| 快捷方式启动（重建后） | < 2s | 2.23s（走的是 exe，PROC=DesktopOrganizer） | 略超目标 |
| 快捷方式启动（b88dd0c 重建后） | < 2s | 1.98s（PROC=DesktopOrganizer，窗口正常） | 达标 |
| 快捷方式启动（GUI 革新版重建，17:18） | < 2s | 1.09s（热 profile，PID=35492，窗口 1180x780） | 达标 |
| **进程族常驻内存（进程树口径）** | 顾问要求 < 75MB | **WorkingSet 486.3MB / Private 209.5MB（7 个进程）** | **不达标，见遗留 P9** |
| 单进程常驻内存（旧口径，仅主进程） | 低 | 97.3–105MB | 记录（低估，勿单独引用） |
| WebView2 flag 生效性 | 生效 | browser 命令行 6/6 flag `PRESENT` | 达标（但 gpu-process 仍被创建） |
| **一键排版 + 撤销往返（真机，Bridge 路径）** | 净变化为零 | 251 项排版，246 个坐标变动；撤销后 `same=True moved=0`，`restored=251 verified=True` | 达标 |
| **桌面真实网格步长** | 与系统常量对齐 | **75 / 104**（系统 `SM_CXICONSPACING`=75/75、`LVM_GETITEMSPACING`=96/81 均不符） | 只能用桌面坐标推断 |
| **越界夹取（P8）** | 不出屏幕 | (3000,100)→(2485,100)；(100,2000)→(100,1317)；(-50,-80)→(0,0)；(5000,5000)→(2485,1317) | 达标 |
| **排版+撤销（步长修正后复测）** | 零溢出 + 净变化为零 | 容量 429 ≥ 251；排成 20 列×13 行，`skipped_overflow=0`；撤销 `restored=251 verified=True`，`diff same=True` | 达标 |
| **复合策略真机（系统图标置前）** | 第一格是系统图标 | `(11,2) HY`、`(86,2) Codex - OpenCode Go`、`(161,2) IntelliJ IDEA`；第 0 列是 HY/回收站/此电脑/网络 | 达标 |
| **快捷方式识别修正** | is_shortcut 不再全为 0 | 修前 `shortcut=0 / special=83`（其中 42 个其实有 .lnk）→ 修后 `system=4 / shortcut=79 / special=4` | 达标 |
| **misfit 口径（按格子比）** | 不误报 | `misfit=0`、`attempts_used=2`（修前按像素比会 251 个全报错） | 达标 |
| 全量测试 | 全绿 | **370 passed / 1 skipped** | 达标 |

## 下一步
1. 用户在界面上点右上角「用户目录写入：关」→ 变「开」（会弹一次确认）。
2. 点「扫描目录」→ 用搜索框/排序下拉/左侧类别筛选找到要整理的文件 → 手动勾选（**不再默认勾选任何一项**）→「预览效果（不落盘）」→「真正执行移动」。**进度条在表格上方，只显示百分比**。
3. 目标目录不满意：在「批量改去向」输入框写 `2026/专案组` 这类相对路径，点「应用到选中」；也支持单行改判。
4. 想让 AI 出建议：右栏「AI 顾问」选服务商（Gemini / OpenAI 兼容）、填 API Key（只存本地、不下发前端明文）、点「让 AI 提建议」→「一键采纳」。**默认是「关闭（只用本地规则）」，不填也能用**。
5. 不满意点「回滚上一次」：文件回原位、空目录自动清理、mtime/atime/创建时间三项按日志还原、主动刷新 shell、**桌面图标按整理前快照写回并回读校验**。
6. **只想把桌面摆整齐、不改任何文件**：顶栏六个选项按需点选（选中的显示 1/2/3 叠加序号）→「一键整理图标」→ 不满意随时点常驻的「撤销整理」（备份在 `data\layout_undo.json`；撤销会自己重试几轮，因为 Explorer 有时会延迟重排）。这条路径**只写图标坐标，一个文件都不动**。默认顺序是 系统图标（此电脑/用户/网络）→ 快捷方式 → 按名称。
   - 想批量勾选文件：工具条「按类别勾选…」选一个类别 →「选中本类别」。
   - 只按时间排：把「按修改时间」放到第一位（或只留它）。
7. 遗留：M5 红队子集（中断恢复/文件占用/云占位/超长路径/权限拒绝）、P1 分类权重调优、**进程族内存 486MB 未达 75MB 目标（P9）**。
8. 若重新打包：`python -m PyInstaller --noconfirm --clean DesktopOrganizer.spec`，信任区按路径匹配无需重新加白；**重建会清空 `dist\DesktopOrganizer\data`（含 settings.json 与 journal）**，即许可状态会回到默认关闭。CLI 回滚用法是 `rollback --journal <id>`（不是位置参数）。
9. 换显示器/改缩放后**不需要**做任何事：排版与回滚都会按当前工作区裁剪，越界数量会写在返回的 `errors` 里（界面日志区可见）。

## 环境坑（新增）
- **截图正确姿势（17:16 定稿）**：先 `EnumWindows` 按 PID 列出该进程所有顶层窗口，选 `IsWindowVisible` 且**宽 > 600 且面积最大**的那个（句柄会变，且会有 160x28 的幽灵窗口），再 `PrintWindow(h, hdc, 2)`。`CopyFromScreen` 不管怎么切前台都会抓到挡在前面的别的窗口（实测两次抓到文件资源管理器）。`evidence/gui-shot15.png` / `gui-shot16.png` 是正确产物，`gui-shot11~14` 是失败尝试。
- **backdrop-filter 会让 PrintWindow 漏内容**：旧界面 `.acts` 带 `blur(22px)`，被提升成独立合成层导致按钮区拍不到；新版只在顶栏保留 backdrop-filter，其余已去掉，故 PrintWindow 可用。
- **内存别按进程名统计**：`Get-Process msedgewebview2` 会把 Windows 搜索与 clash-verge 的进程一起算进来（实测虚高到 25 进程 / 1134MB）。要按 `ParentProcessId` 递归建进程树。
- **`Copy-Item "$backup\*"` 还原目录会报** `Container cannot be copied onto existing leaf item`；改用 `Get-ChildItem $backup | ForEach-Object { Copy-Item $_.FullName (Join-Path $dest $_.Name) -Recurse -Force }`。
- **桌面格距不要信系统常量**：`GetSystemMetrics(38/39)` 报 75/75、`LVM_GETITEMSPACING` 报 96/81，而桌面相邻坐标差恒为 **75/104**。按错的行距排版会让两个图标被 Explorer 对齐进同一格。唯一可信来源是桌面自己的图标坐标。
- **本机 PowerShell 不支持 heredoc**：`python - <<'PYEOF'` 会报 `Missing file specification after redirection operator`；含中文的补丁必须写成 `.py` 文件再 `python file.py` 执行（here-string `python -c @"..."@` 也会把中文和 `\n` 搞坏）。

## 已知阻碍
- `schedule_create` 工具不存在 → 用 create_goal 续轮替代（blockers.md B1）- 火绒拦截未签名的 PyInstaller exe（decisions.md B6）→ **已由用户加白解决**
- 冻结 exe 的用户数据落在 `dist\DesktopOrganizer\data`，`--clean` 重建会清空（decisions.md B7，遗留项）
- **进程族内存 486.3MB（WorkingSet）/ 209.5MB（Private）远超顾问要求的 75MB**（遗留 P9）。已排查：6 个 Chromium flag 全部生效，`--disable-gpu` 并不能阻止 gpu-process 被创建（59.8MB）；WebView2 的 browser/renderer 各约 120MB 属运行时基线。要压下去只能换渲染方案（放弃 == 换掉 pywebview），不在本轮范围。

## git 最近提交
- e73c05d feat: 一键整理图标 - 三种排版策略 + 备份后可撤销的坐标写回
- 61f1a28 feat: 三栏现代化界面 + AI 顾问建议 + 进度条 + 自由去向
- b88dd0c fix: 回滚补齐创建时间并刷新 shell，界面加搜索/排序且不再默认勾选
- 1f1b880 fix: 回滚复原文件时间戳，桌面图标顺序不再被整理打乱
- 212f96b feat: 用户可自行打开写盘许可开关，桌面整理不再被硬拦
- a346d62 docs: 同步进度锚点到性能优化完成状态
- 9f162d3 feat: 冷启动压到 1.1s - 持久化 WebView2 profile + 打包 exe + 启动器自动优选
- 332e109 fix: 全被守卫拒绝时不再留空 journal，回滚后清理空目录，界面加一键全选/全不选
- c8460b6 docs: 更新进度锚点到 GUI 交付完成状态
- 3d04163 feat: 精致 GUI - pywebview 桥接层 + 深色玻璃自绘界面 + 图标与桌面快捷方式
- 8e205fa fix: CLI 强制 UTF-8 输出
- dd688d4 feat: M4 核心模块收口
- 3b6ca84 feat: M3 骨架落地

## GitHub 存档（2026-11-03 22:10）

- 仓库：**https://github.com/thefuckbear/Desktop_Cleaner**（**私有**，默认分支 `main`）
- 首个存档点：`ba6005c`，远端 76 个文件、28 次提交，与本地 HEAD 一致
- **推送必须走本机代理**：直连 `github.com:443` 会挂 21 秒后失败（`curl` 返回 000），
  走 `http://127.0.0.1:7897` 才 200。已在仓库级（不是全局）配好：
  `git config http.proxy http://127.0.0.1:7897`、`git config https.proxy http://127.0.0.1:7897`
- 没进仓库的东西（都在 `.gitignore` 里）：`dist/`（打包产物 49MB）、`build/`、`sandbox/`、
  `logs/`、`data/`（含 `settings.json` 的许可状态、journal 回滚记录、AI 配置）、`evidence/*.png`
- 仓库里没有的东西：API Key、token、真实桌面文件清单、桌面文件内容、>10MB 二进制。
  上传前扫过 `sk-*`/`gho_*`/`ghp_*`/`AIza*`/`api_key=` 与几个真实文件名，**命中 0**
- 想改公开：`gh repo edit thefuckbear/Desktop_Cleaner --visibility public --accept-visibility-change-consequences`
- 别人（或换台机器）拉下来怎么跑：`git clone` → `pip install pywebview` → 双击 `scripts\launch_gui.pyw`
  或 `python -m desktop_organizer gui`（需 `PYTHONPATH=src`）；打包版要自己跑一次 PyInstaller

## 中转站适配 + 真机跑通（2026-11-03 23:30）

- 起因：用户 `m08927` 指出「我的 key 是 opencode go 的 key，不要预设是 ds 官网 key」。
  此前把 key 判成无效是**误判**——key 一直是好的，错在代码预设了官方地址。
- 真机实测四处证据（全部为实际结果）：
  1. `GET https://opencode.ai/zen/go/v1/models` → **200**，返回 **28 个模型**
     （`deepseek-v4.1-flash`/`deepseek-v4-pro`/`glm-5.2`/`glm-5.3`/`grok-4.7`/…）
  2. 缺 `x-opencode-session` 头 → **400 `MissingSessionID`**；补上 → 200。
     这个错长得像鉴权失败，但跟 key 一点关系没有。
  3. `response_format: json_object` 该网关**支持**（返回 200），但仍只对官方地址发。
  4. `analyze()` 端到端：**`degraded=False`、3 条建议**，模型还自己标注
     「仅凭文件名判断」「6 字节疑似样例文件」——元数据边界守住了。
- 代码改动：`base_url` 权威化、端点 `{base}` 与 `{base}/v1` 两级回退（仅 404/405 换）、
  固定 `x-opencode-session`、401 文案带真实 URL 并指向"先核对 Base URL"、
  中转 key 仅按 `^[a-z]{2,}_sk_` 强证据识别、`_strip_fence` 剥 ```json 围栏。
- 界面：加「测试连接」按钮（先落盘再探 `/models`，成功把模型灌进 `#aiModelList`
  供 datalist 下拉），`#aiBase` 提示改成中转站写法。
- 门禁：`python -m pytest tests/ -q` → **416 passed, 1 skipped**（新增 `tests/test_relay_endpoints.py` 21 条）；
  exe **6,581,816 bytes / 23:29:41**（重建前备份 `dist\DesktopOrganizer\data`，建后还原）。
- 踩坑记录：placeholder 里写了 `https://` 直接触发
  `test_no_external_network_resources`（前端零外网是硬约束），改成不带协议才过——
  **没有为了过测试去放宽那条断言**。
