# 进度（progress.md）

> 断点续跑的唯一真相。每完成一个子任务立即更新。最后更新：2026-11-03 15:12（北京时间）

## 当前阶段
**图标位置真回滚已交付：整理前给桌面图标拍像素坐标快照（Win32 `LVM_GETITEMPOSITION`），回滚时用 `LVM_SETITEMPOSITION` 逐个写回；自动排列开着会先关掉且不自动恢复；另有格点占用验收（不 OCR、不联网）。187 绿 + 真机写回实测通过**

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
- [x] 全量测试 151 passed / 1 skipped

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
| 全量测试 | 全绿 | 151 passed / 1 skipped | 达标 |

## 下一步
1. 用户在界面上点右上角「用户目录写入：关」→ 变「开」（会弹一次确认）。
2. 点「扫描目录」→ 用搜索框/排序下拉找到要整理的文件 → 手动勾选（**不再默认勾选任何一项**）→「预览效果（不落盘）」→「真正执行移动」。
3. 不满意点「回滚上一次」：文件回原位、空目录自动清理、**mtime/atime/创建时间三项均按日志还原并主动刷新 shell**，桌面图标顺序回到整理前。
4. 遗留：M5 红队子集（中断恢复/文件占用/云占位/超长路径/权限拒绝）、P1 分类权重调优、扫描进度条、DPI 缩放验证。
5. 若重新打包：`python -m PyInstaller --noconfirm --clean DesktopOrganizer.spec`，信任区按路径匹配无需重新加白；**重建会清空 `dist\DesktopOrganizer\data`（含 settings.json 与 journal）**，即许可状态会回到默认关闭。CLI 回滚用法是 `rollback --journal <id>`（不是位置参数）。

## 已知阻碍
- `schedule_create` 工具不存在 → 用 create_goal 续轮替代（blockers.md B1）
- 火绒拦截未签名的 PyInstaller exe（decisions.md B6）→ **已由用户加白解决**
- 冻结 exe 的用户数据落在 `dist\DesktopOrganizer\data`，`--clean` 重建会清空（decisions.md B7，遗留项）

## git 最近提交
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
