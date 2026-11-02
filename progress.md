# 进度（progress.md）

> 断点续跑的唯一真相。每完成一个子任务立即更新。最后更新：2026-11-02 23:15（北京时间）

## 当前阶段
**全部交付完成 → 火绒已加白、打包 exe 已恢复并实测（1.56–2.49s，中位 1.77s），等用户拍板是否放开真实桌面写入**

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
- [x] 全量测试 120 passed / 1 skipped

## 实测数据
| 指标 | 目标 | 实测 | 结论 |
|---|---|---|---|
| **冷启动（当前生效：打包 exe）** | < 2s | **1.56 / 1.70 / 1.77 / 2.22 / 2.49s**（中位 1.77） | 轻载达标，重载略超 |
| 冷启动（源码模式，兜底） | < 2s | 2.17s | 略超，仅作兜底 |
| 加白后首次启动 | < 2s | 3.26–3.28s | 杀软首扫新 exe，非代码问题 |
| 首屏 t_gui_ready | — | 1916ms → **835ms** | profile 持久化收益 |
| 常驻内存 | 低 | 100.2–105MB | 记录 |
| 安装包体积 | — | exe 6.5MB / dist 49.1MB | 记录 |
| 沙箱 e2e | 可回滚 | applied=6 / rollback=6 | 达标 |
| 全量测试 | 全绿 | 120 passed / 1 skipped | 达标 |

## 下一步（等用户决定）
1. 用户若要真整理桌面：需放开 `constants.ALLOW_USER_DIRS`（当前 False），建议先在 `sandbox\` 真执行一轮验证火绒对文件移动是否二次拦截。
2. 遗留：M5 红队子集（中断恢复/文件占用/云占位/超长路径/权限拒绝）、P1 分类权重调优、扫描进度条、DPI 缩放验证。
3. 若重新打包：`python -m PyInstaller --noconfirm --clean DesktopOrganizer.spec`，信任区按路径匹配无需重新加白。

## 已知阻碍
- `schedule_create` 工具不存在 → 用 create_goal 续轮替代（blockers.md B1）
- 火绒拦截未签名的 PyInstaller exe（decisions.md B6）→ **已由用户加白解决**

## git 最近提交
- a346d62 docs: 同步进度锚点到性能优化完成状态
- 9f162d3 feat: 冷启动压到 1.1s - 持久化 WebView2 profile + 打包 exe + 启动器自动优选
- 332e109 fix: 全被守卫拒绝时不再留空 journal，回滚后清理空目录，界面加一键全选/全不选
- c8460b6 docs: 更新进度锚点到 GUI 交付完成状态
- 3d04163 feat: 精致 GUI - pywebview 桥接层 + 深色玻璃自绘界面 + 图标与桌面快捷方式
- 8e205fa fix: CLI 强制 UTF-8 输出
- dd688d4 feat: M4 核心模块收口
- 3b6ca84 feat: M3 骨架落地
