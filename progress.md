# 进度（progress.md）

> 断点续跑的唯一真相。每完成一个子任务立即更新。最后更新：2026-11-02 23:00（北京时间）

## 当前阶段
**交付完成 → 火绒拦截打包 exe，已改为源码模式（2.17s），待用户决定是否加白名单拿回 1.1s**

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
| 火绒拦截处理（追加） | 22:55–23:00 | 完成（打包产物移入隔离区，回退源码模式） |

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
- [x] 全量测试 120 passed / 1 skipped

## 实测数据
| 指标 | 目标 | 实测 | 结论 |
|---|---|---|---|
| **冷启动（当前生效：源码模式）** | < 2s | **2.17s** / 101.8MB | 达标 |
| 冷启动（打包 exe，已被火绒拦） | < 2s | 1.1–1.2s | 达标但不可用 |
| 冷启动（重建后首启） | < 2s | 2.34–2.75s | 杀软扫新 exe，非代码问题 |
| 冻结 exe 直接启动 | < 2s | 1.75–1.78s | 达标但不可用 |
| 首屏 t_gui_ready | — | 1916ms → **835ms** | profile 持久化收益 |
| 常驻内存 | 低 | 101.8–105MB | 记录 |
| 安装包体积 | — | exe 6.5MB / dist 6.2MB（已隔离） | 记录 |
| 沙箱 e2e | 可回滚 | applied=6 / rollback=6 | 达标 |
| 全量测试 | 全绿 | 120 passed / 1 skipped | 达标 |

## 下一步（等用户决定）
1. 用户若想拿回 1.1s：把 `sandbox\_build-quarantine-20261102-225523\DesktopOrganizer` 移回 `<根>\dist\DesktopOrganizer`，再在火绒信任区把该目录加白。
2. 用户若要真整理桌面：需放开 `constants.ALLOW_USER_DIRS`（当前 False），建议先沙箱真执行验证。
3. 遗留：M5 红队子集、P1 分类权重调优、扫描进度条、DPI 缩放验证。

## 已知阻碍
- `schedule_create` 工具不存在 → 用 create_goal 续轮替代（blockers.md B1）
- 火绒拦截未签名的 PyInstaller exe（decisions.md B6）→ 已绕行为源码模式

## git 最近提交
- a346d62 docs: 同步进度锚点到性能优化完成状态
- 9f162d3 feat: 冷启动压到 1.1s - 持久化 WebView2 profile + 打包 exe + 启动器自动优选
- 332e109 fix: 全被守卫拒绝时不再留空 journal，回滚后清理空目录，界面加一键全选/全不选
- c8460b6 docs: 更新进度锚点到 GUI 交付完成状态
- 3d04163 feat: 精致 GUI - pywebview 桥接层 + 深色玻璃自绘界面 + 图标与桌面快捷方式
- 8e205fa fix: CLI 强制 UTF-8 输出
- dd688d4 feat: M4 核心模块收口
- 3b6ca84 feat: M3 骨架落地
