"""持久化设置测试。

核心诉求：写盘许可默认必须关（deny by default），只有用户显式打开才放行，
且这个选择要跨进程记住 —— 否则每次开界面都得重开一次，等于没有开关。
"""

from __future__ import annotations

import json
from pathlib import Path

from desktop_organizer import constants, settings


def test_deny_by_default(tmp_path: Path) -> None:
    """没有任何设置文件时，必须是拒绝。"""
    assert settings.allow_user_dirs(path=tmp_path / "settings.json") is False


def test_enable_persists_across_loads(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    assert settings.set_allow_user_dirs(True, path=path) is True
    assert path.is_file()
    # 模拟"下次启动"：从磁盘重新读
    assert settings.allow_user_dirs(path=path) is True


def test_can_turn_it_back_off(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings.set_allow_user_dirs(True, path=path)
    assert settings.set_allow_user_dirs(False, path=path) is False
    assert settings.allow_user_dirs(path=path) is False


def test_corrupt_file_falls_back_to_deny(tmp_path: Path) -> None:
    """文件坏了必须退回安全侧，不能因为解析失败就放行。"""
    path = tmp_path / "settings.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert settings.allow_user_dirs(path=path) is False


def test_non_bool_value_falls_back_to_deny(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"allow_user_dirs": "yes"}), encoding="utf-8")
    assert settings.allow_user_dirs(path=path) is False


def test_write_is_atomic_no_tmp_left(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings.set_allow_user_dirs(True, path=path)
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_default_path_lives_under_data_dir() -> None:
    """默认路径必须落在 DATA_DIR（已被 .gitignore 排除）。"""
    default = settings.settings_path()
    assert default.parent == constants.DATA_DIR
    assert default.name == "settings.json"
