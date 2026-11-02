"""常量与路径解析。

重点：``PROJECT_ROOT`` 同时是**写盘白名单**。PyInstaller 打包后
``__file__`` 指向解压出来的临时目录，若不做特殊处理，白名单会指向
临时目录，日志和偏好也会写进 temp 然后随进程消失。
"""

from __future__ import annotations

from pathlib import Path

from desktop_organizer import constants


def test_project_root_in_source_mode_is_repo_root(tmp_path):
    """源码运行：src/desktop_organizer/constants.py → 往上两级 = 仓库根。"""
    fake_file = tmp_path / "repo" / "src" / "desktop_organizer" / "constants.py"
    root = constants.resolve_project_root(frozen=False, exe_path=None, file_path=fake_file)
    assert root == (tmp_path / "repo").resolve()


def test_project_root_in_frozen_mode_follows_the_exe(tmp_path):
    """打包后：可写目录必须是 exe 所在目录，不能是 _MEIPASS 临时目录。"""
    fake_file = tmp_path / "_MEI123" / "desktop_organizer" / "constants.py"
    exe = tmp_path / "apps" / "DesktopOrganizer.exe"
    root = constants.resolve_project_root(frozen=True, exe_path=exe, file_path=fake_file)
    assert root == (tmp_path / "apps").resolve()


def test_frozen_root_never_lands_inside_temp_extraction_dir(tmp_path):
    fake_file = tmp_path / "_MEI999" / "desktop_organizer" / "constants.py"
    exe = tmp_path / "Dist" / "DesktopOrganizer.exe"
    root = constants.resolve_project_root(frozen=True, exe_path=exe, file_path=fake_file)
    assert "_MEI" not in str(root)


def test_runtime_dirs_hang_off_project_root():
    assert constants.SANDBOX_DIR.parent == constants.PROJECT_ROOT
    assert constants.LOG_DIR.parent == constants.PROJECT_ROOT
    assert constants.DATA_DIR.parent == constants.PROJECT_ROOT
