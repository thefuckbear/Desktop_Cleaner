# Desktop Organizer

个人自用的 Windows 桌面整理工具。把桌面堆积的文件按 **类别 / 重要程度** 整理成两层文件夹，放置建议由本地规则引擎给出，**人逐项确认**，每次改判被记住并影响下次建议。

- **默认 dry-run**，任何写盘都需要显式双开关 + 确认
- **路径守卫硬拦截**：系统目录与用户数据目录在代码层拒绝
- **每次移动都可回滚**，WAL 日志保证断电可恢复
- **零第三方运行时依赖**（纯 Python 标准库 + tkinter）

## 快速开始

```powershell
cd C:\Users\HY\Desktop\Projects\Desktop_Cleaner
$env:PYTHONPATH = "src"

# 1. 只读扫描（不会改动任何文件）
python -m desktop_organizer scan --root "C:\Users\HY\Desktop" --depth 1

# 2. 生成整理计划预览（仍然不动文件）
python -m desktop_organizer plan --root "C:\Users\HY\Desktop"

# 3. 执行（默认 dry-run；真正执行需要两个开关）
python -m desktop_organizer apply --root "C:\Users\HY\Desktop"                       # dry-run
python -m desktop_organizer apply --root "C:\Users\HY\Desktop" --no-dry-run --yes     # 真正写盘

# 4. 回滚
python -m desktop_organizer rollback            # 回滚最近一次
python -m desktop_organizer journals            # 查看历史

# 5. 图形界面
python -m desktop_organizer gui
```

## 安全模型

三道闸门：

1. **`guard.py` 硬拦截**：判定顺序为「系统目录黑名单 → 项目根 allowlist → 用户数据目录黑名单」。
   - 无条件拒绝：`C:\Windows`、`Program Files`、`AppData`、`ProgramData`、回收站、系统盘根、UNC 路径、保留设备名
   - 默认拒绝：`Desktop` / `Documents` / `Downloads` / `OneDrive`（写入）
   - 允许：项目根目录及其子目录（只用于受控测试）
2. **默认 dry-run**：`DEFAULT_DRY_RUN = True`，CLI 需要 `--no-dry-run` **和** `--yes` 同时给才真正执行。
3. **WAL journal**：每条移动先写 `start` 再执行，成功后写 `done`。崩溃后能判断哪些"可能已执行"并回滚。

## 目录结构

```
Desktop_Cleaner/
├── src/desktop_organizer/
│   ├── guard.py        # 路径守卫（安全核心）
│   ├── model.py        # 数据契约
│   ├── constants.py    # 常量与置信度分档
│   ├── scanner.py      # 只读扫描
│   ├── classify.py     # 扩展名/关键词分类
│   ├── rules.py        # 规则引擎
│   ├── store.py        # 改判偏好持久化
│   ├── planner.py      # 生成移动计划
│   ├── executor.py     # 执行 + 回滚
│   ├── journal.py      # WAL 日志
│   ├── cli.py          # 命令行入口
│   └── ui/app.py       # tkinter 界面
├── tests/              # pytest
├── docs/               # 需求/架构/契约/测试计划
├── sandbox/            # 测试样本（gitignore）
└── evidence/           # 实测证据
```

## 测试

```powershell
cd C:\Users\HY\Desktop\Projects\Desktop_Cleaner
$env:PYTHONPATH = "src"
python -m pytest tests/ -q
```

## 文档

- [需求与验收标准](docs/01-requirements.md)
- [架构与接口契约](docs/02-architecture.md)
- [决策记录](decisions.md)
- [卡点记录](blockers.md)
- [进度](progress.md)

## 许可

个人自用，未授权分发。
