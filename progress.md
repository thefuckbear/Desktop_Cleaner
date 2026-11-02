# 进度（progress.md）

> 断点续跑的唯一真相。每完成一个子任务立即更新。最后更新：2026-11-02 14:20（北京时间）

## 当前阶段
**M1 进行中 → M2 并行起草中**

## 时间预算
| 里程碑 | 计划时段 | 状态 |
|---|---|---|
| M1 需求边界 | 14:00–14:50 | 进行中（文档已落盘） |
| M2 架构+契约 | 14:50–15:50 | 已并行起草（架构文档已落盘，契约三件套已冻结） |
| M3 骨架+首次提交 | 15:50–16:50 | 未开始（目录已建、git 已 init） |
| M4 核心模块 | 16:50–18:20 | 未开始（3 teammate 已并行开工） |
| M5 红队自测 | 18:20–19:20 | 未开始 |
| M6 收尾 | 19:40–20:00 | 未开始 |

## 已完成
- [x] 探查目标目录（存在且为空，无 git）→ `git init -b main` 完成
- [x] 工具链探测：Python 3.13.1 / pytest / PyInstaller / tkinter 全部可用
- [x] 目录骨架：docs/ src/desktop_organizer/ui/ tests/ sandbox/ evidence/ scripts/
- [x] 契约三件套落盘：`model.py`、`constants.py`、`guard.py`
- [x] `.gitignore` 落盘
- [x] `docs/01-requirements.md` 落盘
- [x] `docs/02-architecture.md` 落盘（含 Mermaid 架构图/数据流/失败矩阵）
- [x] 3 个 teammate 已 spawn 并 running：fs-engine / ai-strategy / qa-redteam
- [x] 持久化 goal 已建立（替代缺失的 schedule_create）

## 进行中
- fs-engine：scanner.py / journal.py / executor.py + 测试
- ai-strategy：classify.py / rules.py / store.py / planner.py + 测试 + docs/decisions-ai.md
- qa-redteam：conftest/fixtures/test_guard/test_contracts + docs/04-test-plan.md

## 下一步
1. 写 `cli.py`（argparse：scan / plan / apply / rollback / undo）
2. 写 `ui/app.py`（tkinter 预览表 + 勾选 + 改判 + 一键采纳）
3. 等队友报回后跑集成，跑全量 pytest
4. 首次提交（M3 收口）

## 已知阻碍
- **`schedule_create` 工具不存在**：本环境只有 create_goal/get_goal/update_goal，无定时检查点能力。已改用 create_goal（max_goal_rounds=30）持续自动续轮 + 每轮开头读本文件。已记入 blockers.md。
- 沙箱物理位于 Desktop 之下，guard 通过项目根允许清单放行，真实桌面仍默认拒绝。

## git 最近提交
（尚无提交）
