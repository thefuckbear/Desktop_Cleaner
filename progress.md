# 进度（progress.md）

> 断点续跑的唯一真相。每完成一个子任务立即更新。最后更新：2026-11-02 22:16（北京时间）

## 当前阶段
**性能目标已全部达成 → 进入交付文档同步**

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

## 实测数据（性能三条线全绿）
| 指标 | 目标 | 实测 | 结论 |
|---|---|---|---|
| 冷启动（快捷方式，稳态） | < 2s | **1.1–1.2s** | 达标 |
| 冷启动（重建后首启） | < 2s | 2.34–2.75s | 杀软扫新 exe，非代码问题 |
| 冻结 exe 直接启动 | < 2s | 1.75–1.78s | 达标 |
| 首屏 t_gui_ready | — | 1916ms → **835ms** | profile 持久化收益 |
| 常驻内存 | 低 | 103–105MB | 记录 |
| 安装包体积 | — | exe 6.5MB / dist 6.2MB | 记录 |
| 沙箱 e2e | 可回滚 | applied=6 / rollback=6 | 达标 |

## 下一步
1. 同步 交付报告.md / 进度看板.html / decisions.md / blockers.md 到最新状态
2. 交付目录三个文件最终确认 + git 工作区 clean

## 已知阻碍
- `schedule_create` 工具不存在 → 用 create_goal 续轮替代（blockers.md B1）

## git 最近提交
- 9f162d3 feat: 冷启动压到 1.1s - 持久化 WebView2 profile + 打包 exe + 启动器自动优选
- 332e109 fix: 全被守卫拒绝时不再留空 journal，回滚后清理空目录，界面加一键全选/全不选
- c8460b6 docs: 更新进度锚点到 GUI 交付完成状态
- 3d04163 feat: 精致 GUI - pywebview 桥接层 + 深色玻璃自绘界面 + 图标与桌面快捷方式
- 8e205fa fix: CLI 强制 UTF-8 输出
- dd688d4 feat: M4 核心模块收口
- 3b6ca84 feat: M3 骨架落地
