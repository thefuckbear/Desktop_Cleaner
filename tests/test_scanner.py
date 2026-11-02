"""scanner.scan 的只读扫描行为测试。

所有样本都在 sandbox（tmp_path 已被 conftest 钉到项目 sandbox 内）自建，
绝不枚举真实桌面/用户目录。
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

import pytest

from desktop_organizer import scanner
from desktop_organizer.model import GuardError

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000


def _touch(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _set_attrs(path: Path, attrs: int) -> None:
    """仅对沙箱内的自建样本改属性，用于模拟隐藏/系统文件。"""
    kernel32 = ctypes.windll.kernel32
    ok = kernel32.SetFileAttributesW(str(path), attrs)
    if not ok:
        raise OSError(f"SetFileAttributesW 失败: {path} attrs={attrs}")


def test_scan_lists_root_files_only_by_default(tmp_path):
    _touch(tmp_path / "b.txt", "bb")
    _touch(tmp_path / "A.PNG", "aa")
    _touch(tmp_path / "nested" / "deep.txt")

    items = scanner.scan(str(tmp_path))

    names = [i.name for i in items]
    assert "nested" in names          # 子目录本身可见
    assert "deep.txt" not in names    # 默认只看一层
    assert names.index("A.PNG") < names.index("b.txt")  # name 排序


def test_file_metadata_is_populated_without_touching_content(tmp_path):
    target = _touch(tmp_path / "photo.JPG", "12345")

    item = next(i for i in scanner.scan(str(tmp_path)) if i.name == "photo.JPG")

    assert item.path == str(target)
    assert item.ext == ".jpg"
    assert item.size == 5
    assert item.is_dir is False
    assert item.skipped is False
    assert item.mtime > 0
    assert item.cloud_placeholder is False


def test_subdirectories_are_marked_skipped_and_never_descended(tmp_path):
    (tmp_path / "folder").mkdir()

    items = scanner.scan(str(tmp_path))
    folder = next(i for i in items if i.name == "folder")

    assert folder.is_dir is True
    assert folder.skipped_reason == "directory"


def test_max_depth_recurses_only_that_deep(tmp_path):
    _touch(tmp_path / "lvl1.txt")
    _touch(tmp_path / "d1" / "lvl2.txt")
    _touch(tmp_path / "d1" / "d2" / "lvl3.txt")

    names = {i.name for i in scanner.scan(str(tmp_path), max_depth=2)}

    assert {"lvl1.txt", "lvl2.txt"} <= names
    assert "lvl3.txt" not in names


def test_hidden_and_system_files_are_skipped(tmp_path):
    hidden = _touch(tmp_path / "hidden.txt")
    system = _touch(tmp_path / "system.txt")
    _set_attrs(hidden, FILE_ATTRIBUTE_HIDDEN)
    _set_attrs(system, FILE_ATTRIBUTE_SYSTEM)

    by_name = {i.name: i for i in scanner.scan(str(tmp_path))}

    assert by_name["hidden.txt"].skipped_reason == "hidden"
    assert by_name["system.txt"].skipped_reason == "system"


def test_protected_system_file_names_are_skipped(tmp_path):
    _touch(tmp_path / "desktop.ini")
    _touch(tmp_path / "pagefile.sys")

    by_name = {i.name: i for i in scanner.scan(str(tmp_path))}

    assert by_name["desktop.ini"].skipped_reason == "protected_name"
    assert by_name["pagefile.sys"].skipped_reason == "protected_name"


def test_symlink_or_reparse_point_is_skipped(tmp_path):
    target = _touch(tmp_path / "real.txt")
    link = tmp_path / "link.txt"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接（需开发者模式）")

    by_name = {i.name: i for i in scanner.scan(str(tmp_path))}

    assert by_name["link.txt"].skipped_reason in ("reparse_point", "symlink")


@pytest.mark.parametrize("attrs", [FILE_ATTRIBUTE_OFFLINE,
                                   FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS,
                                   FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS])
def test_cloud_placeholder_attributes_are_detected(attrs):
    # 占位符文件无法在本地凭空造出来，直接验证属性判别逻辑（这是真实分支）。
    assert scanner._skip_reason("cloud.docx", attrs, is_dir=False, is_reparse=False) == "cloud_placeholder"


def test_plain_file_has_no_skip_reason():
    assert scanner._skip_reason("normal.txt", 0x80, is_dir=False, is_reparse=False) is None


def test_scan_refuses_system_directory(tmp_path):
    with pytest.raises(GuardError):
        scanner.scan(r"C:\Windows")


def test_scan_uses_read_only_guard_not_write_guard(tmp_path, monkeypatch):
    """扫描必须走 assert_readable：真实桌面允许只读枚举，但绝不复用写权限判定。"""
    calls: list[str] = []
    real_readable = scanner.guard.assert_readable
    real_safe = scanner.guard.assert_safe

    monkeypatch.setattr(scanner.guard, "assert_readable",
                        lambda p: calls.append("read") or real_readable(p))
    monkeypatch.setattr(scanner.guard, "assert_safe",
                        lambda p, **kw: calls.append("write") or real_safe(p, **kw))

    scanner.scan(str(tmp_path))

    assert "read" in calls
    assert "write" not in calls


def test_single_entry_failure_does_not_break_whole_scan(tmp_path, monkeypatch):
    _touch(tmp_path / "ok.txt")
    _touch(tmp_path / "bad.txt")

    real_stat = os.DirEntry.stat

    def flaky(self, *, follow_symlinks=True):
        if self.name == "bad.txt":
            raise PermissionError("拒绝访问")
        return real_stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(os.DirEntry, "stat", flaky)

    by_name = {i.name: i for i in scanner.scan(str(tmp_path))}

    assert by_name["ok.txt"].skipped is False
    assert by_name["bad.txt"].skipped_reason == "permission_denied"


def test_long_path_over_260_chars_is_scanned(tmp_path):
    deep = tmp_path
    while len(str(deep)) <= 280:
        deep = deep / ("d" * 40)
    deep.mkdir(parents=True, exist_ok=True)
    (deep / "far.txt").write_text("z", encoding="utf-8")

    items = scanner.scan(str(tmp_path), max_depth=2)

    assert len(str(deep)) > 260
    assert all(not i.path.startswith("\\\\?\\") for i in items)
    assert any(i.name == "far.txt" for i in scanner.scan(str(deep), max_depth=1))


def test_scan_does_not_modify_the_directory(tmp_path):
    _touch(tmp_path / "a.txt")
    _touch(tmp_path / "sub" / "b.txt")
    before = {(p.name, p.stat().st_mtime_ns) for p in tmp_path.rglob("*")}

    scanner.scan(str(tmp_path), max_depth=2)

    after = {(p.name, p.stat().st_mtime_ns) for p in tmp_path.rglob("*")}
    assert before == after
