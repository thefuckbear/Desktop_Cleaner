# 卡点记录（blockers.md）

> 格式：现象 → 已尝试 → 结论/绕行方案。

## B1 `schedule_create` 工具不存在
- **现象**：任务要求"开工 10 分钟内用 schedule_create 建立检查点（15:30/17:00/18:30/19:40）"，但本会话工具集里只有 `create_goal` / `get_goal` / `update_goal`，没有 `schedule_create`。
- **已尝试**：检查可用工具清单（含 Agent Teams、job_* 系列、goal 系列），确认无定时调度类工具。
- **绕行**：用 `create_goal`（objective 描述完整里程碑计划，max_goal_rounds=30）建立持续续轮；每轮开头先读 `progress.md`，接着上次位置继续。在 17:00 与 19:40 两个真实时间点主动执行对账（M1–M6 进度 vs 剩余时间），若不够则砍范围并写入 decisions.md。
- **状态**：已绕行，不阻塞。

## B2 沙箱位于桌面之下
- **现象**：安全铁律要求"绝不写真实桌面"，但项目根 `C:\Users\HY\Desktop\Projects\Desktop_Cleaner` 与沙箱 `...\sandbox` 物理上都在 `%USERPROFILE%\Desktop` 之下。
- **已尝试**：guard 判定链初版把 userdir 拒绝放在 allowlist 之前 → 项目自身无法写入，测试全红。
- **绕行**：调整为"系统目录黑名单 > 项目根 allowlist > 用户目录黑名单"，allowlist 硬编码为项目根单一值，不可通过 CLI/配置扩展；真实桌面其余部分仍全部拒绝。该顺序的代价与约束已写入 decisions.md D4。
- **状态**：已绕行，有专门的守卫测试守护（test_guard.py 断言真实桌面被拒、项目根被允许）。
