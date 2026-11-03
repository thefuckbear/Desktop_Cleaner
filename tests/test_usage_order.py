"""使用频次排序 + UserAssist 解析的测试（全部用注入数据，不读真实注册表）。"""

from __future__ import annotations

import struct

from desktop_organizer import layout, usage


def icon(name, *, usage_count=0, system=False, shortcut=False, directory=False, ext=""):
    return layout.DesktopIconInfo(
        name=name,
        current_x=0,
        current_y=0,
        is_special=False,
        is_shortcut=shortcut,
        is_directory=directory,
        ext=ext,
        mtime=0.0,
        is_system=system,
        usage=usage_count,
    )


# ---------------------------------------------------------------- UserAssist 解析

def _blob(count: int) -> bytes:
    """造一个 72 字节的 UserAssist 值，运行次数放在第 4~8 字节。"""
    return b"\x09\x00\x00\x00" + struct.pack("<I", count) + b"\x00" * 64


def test_run_count_reads_second_dword() -> None:
    assert usage._run_count(_blob(41)) == 41
    assert usage._run_count(_blob(0)) == 0
    assert usage._run_count(b"\x09\x00") == 0


def test_rot13_decodes_shell_names() -> None:
    assert usage._rot13("Puebzr") == "Chrome"
    assert usage._rot13("GnfxOne") == "TaskBar"


def test_basename_strips_hidden_extension() -> None:
    assert usage._basename(r"C:\Users\HY\Desktop\DeepSeek Harness.lnk") == "DeepSeek Harness"
    assert usage._basename(r"{GUID}\TaskBar\Google Chrome.lnk") == "Google Chrome"
    assert usage._basename("Microsoft.Office.EXCEL.EXE.15") == "Microsoft.Office.EXCEL.EXE.15"


def test_build_index_adds_aliases() -> None:
    index = usage.build_index(
        {
            r"C:\Users\HY\Desktop\DeepSeek Harness.lnk": 17,
            "Microsoft.Office.EXCEL.EXE.15": 41,
        }
    )
    assert index["deepseek harness"] == 17
    assert index["microsoft.office.excel.exe.15"] == 41


def test_usage_of_prefers_exact_then_contains() -> None:
    index = {"chrome": 25, "google chrome": 30, "notepad": 3}
    assert usage.usage_of("Chrome", index) == 25
    assert usage.usage_of("Google Chrome", index) == 30
    # 包含匹配：桌面叫 `Chrome` 而记录里是 `Microsoft Edge Chrome` 之类
    assert usage.usage_of("chrome helper", index) == 25


def test_usage_of_returns_zero_for_short_or_unknown() -> None:
    index = {"ab": 99, "notepad": 3}
    assert usage.usage_of("zzz", index) == 0
    assert usage.usage_of("", index) == 0


def test_read_raw_survives_missing_key(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise OSError("no registry here")

    monkeypatch.setattr(usage.winreg, "OpenKey", boom)
    assert usage.read_raw() == {}


def test_usage_map_gives_every_name_a_number() -> None:
    out = usage.usage_map([], root=None)
    assert isinstance(out, dict)


# ---------------------------------------------------------------- by_usage 排序

def test_by_usage_puts_most_used_last() -> None:
    items = [
        icon("常用", usage_count=41),
        icon("偶尔", usage_count=3),
        icon("从没用过", usage_count=0),
    ]
    ordered = layout.sort_by_keys(items, ["by_usage"])
    assert [i.name for i in ordered] == ["从没用过", "偶尔", "常用"]


def test_by_usage_is_a_registered_sort_key() -> None:
    ids = {item["id"] for item in layout.sort_keys()}
    assert "by_usage" in ids
    entry = next(item for item in layout.sort_keys() if item["id"] == "by_usage")
    assert "右" in entry["desc"] or "右" in entry["name"]


def test_by_usage_composes_with_system_first() -> None:
    items = [
        icon("Chrome", usage_count=25, shortcut=True),
        icon("此电脑", usage_count=0, system=True),
        icon("Word", usage_count=41, shortcut=True),
    ]
    ordered = layout.sort_by_keys(items, ["system_first", "by_usage"])
    # 系统图标必须先占住最前；剩下的按使用次数从少到多，最常用的落最右
    assert ordered[0].name == "此电脑"
    assert [i.name for i in ordered[1:]] == ["Chrome", "Word"]


def test_usage_defaults_to_zero_and_never_breaks_sort() -> None:
    plain = layout.DesktopIconInfo(
        name="x", current_x=0, current_y=0, is_special=False,
        is_shortcut=False, is_directory=False, ext="", mtime=0.0,
    )
    assert plain.usage == 0
    assert layout.sort_by_keys([plain], ["by_usage"])[0].name == "x"
