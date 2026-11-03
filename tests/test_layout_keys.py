"""排版策略的组合键与身份识别：系统图标优先、快捷方式识别、写完回读校验。"""

from pathlib import Path

from desktop_organizer import layout
from desktop_organizer.layout import DesktopIconInfo


def icon(
    name: str,
    *,
    special: bool = False,
    system: bool = False,
    shortcut: bool = False,
    directory: bool = False,
    ext: str = "",
    mtime: float = 0.0,
) -> DesktopIconInfo:
    return DesktopIconInfo(
        name=name,
        current_x=0,
        current_y=0,
        is_special=special,
        is_shortcut=shortcut,
        is_directory=directory,
        ext=ext,
        mtime=mtime,
        is_system=system,
    )


# ---------------------------------------------------------------- 组合键


def test_sort_keys_are_listed_with_ids_and_descriptions() -> None:
    keys = layout.sort_keys()
    ids = {k["id"] for k in keys}
    # by_usage 是 2026-11-03 用户要求「按使用频次，最常用的排最右」后新增的键
    assert ids == {
        "system_first",
        "shortcuts_first",
        "by_type",
        "by_category",
        "by_time",
        "by_usage",
        "by_name",
    }
    assert all(k["name"] and k["desc"] for k in keys)


def test_default_keys_put_system_icons_first() -> None:
    keys = layout.normalize_sort_keys(None)
    assert keys[0] == "system_first"
    assert "by_name" in keys


def test_normalize_sort_keys_drops_unknown_and_dedupes() -> None:
    keys = layout.normalize_sort_keys(["by_name", "bogus", "by_name", "system_first"])
    assert keys == ["by_name", "system_first"]


def test_normalize_sort_keys_falls_back_when_all_unknown() -> None:
    assert layout.normalize_sort_keys(["nope"]) == layout.normalize_sort_keys(None)


def test_system_first_puts_shell_icons_at_the_top() -> None:
    items = [
        icon("b.txt", ext=".txt"),
        icon("此电脑", special=True, system=True),
        icon("a.lnk", shortcut=True),
        icon("回收站", special=True, system=True),
    ]
    out = layout.sort_by_keys(items, ["system_first", "shortcuts_first", "by_name"])
    assert [i.name for i in out] == ["回收站", "此电脑", "a.lnk", "b.txt"]


def test_without_system_first_shell_icons_are_not_privileged() -> None:
    items = [icon("b.txt", ext=".txt"), icon("Zeta", special=True, system=True)]
    out = layout.sort_by_keys(items, ["by_name"])
    assert [i.name for i in out] == ["b.txt", "Zeta"]


def test_shortcuts_first_ranks_shortcuts_above_plain_files() -> None:
    items = [icon("a.txt", ext=".txt"), icon("z.lnk", shortcut=True)]
    out = layout.sort_by_keys(items, ["shortcuts_first", "by_name"])
    assert [i.name for i in out] == ["z.lnk", "a.txt"]


def test_by_type_orders_system_shortcut_file_directory() -> None:
    items = [
        icon("dir", directory=True),
        icon("file.txt", ext=".txt"),
        icon("s.lnk", shortcut=True),
        icon("此电脑", special=True, system=True),
    ]
    out = layout.sort_by_keys(items, ["by_type", "by_name"])
    assert [i.name for i in out] == ["此电脑", "s.lnk", "file.txt", "dir"]


def test_by_category_groups_same_category_together() -> None:
    items = [
        icon("b.docx", ext=".docx"),
        icon("a.png", ext=".png"),
        icon("c.png", ext=".png"),
    ]
    out = layout.sort_by_keys(items, ["by_category", "by_name"])
    cats = [layout.category_of(i) for i in out]
    # 同类必须相邻，且桶内按名称
    assert cats == sorted(cats, key=cats.index)
    png = [i.name for i in out if i.ext == ".png"]
    assert png == ["a.png", "c.png"]


def test_by_time_puts_newest_first_within_same_rank() -> None:
    items = [
        icon("old.txt", ext=".txt", mtime=100.0),
        icon("new.txt", ext=".txt", mtime=900.0),
        icon("mid.txt", ext=".txt", mtime=500.0),
    ]
    out = layout.sort_by_keys(items, ["by_time"])
    assert [i.name for i in out] == ["new.txt", "mid.txt", "old.txt"]


def test_sort_by_keys_is_stable_for_equal_keys() -> None:
    items = [icon("b.txt", ext=".txt"), icon("a.txt", ext=".txt")]
    out = layout.sort_by_keys(items, ["by_time"])
    assert [i.name for i in out] == ["b.txt", "a.txt"]


def test_legacy_strategy_id_still_works() -> None:
    items = [icon("a.txt", ext=".txt"), icon("a.lnk", shortcut=True)]
    out = layout.sort_icons(items, "shortcuts_first")
    assert out[0].name == "a.lnk"


# ---------------------------------------------------------------- 快捷方式识别


def test_resolve_icon_path_finds_hidden_lnk_suffix(tmp_path: Path) -> None:
    (tmp_path / "Addictive Drums 2.lnk").write_text("x", encoding="utf-8")
    resolved = layout.resolve_icon_path(str(tmp_path), "Addictive Drums 2")
    assert resolved is not None
    assert resolved.name == "Addictive Drums 2.lnk"


def test_resolve_icon_path_finds_url_suffix(tmp_path: Path) -> None:
    (tmp_path / "B站.url").write_text("x", encoding="utf-8")
    assert layout.resolve_icon_path(str(tmp_path), "B站") is not None


def test_resolve_icon_path_prefers_exact_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "a.txt.lnk").write_text("x", encoding="utf-8")
    resolved = layout.resolve_icon_path(str(tmp_path), "a.txt")
    assert resolved is not None and resolved.name == "a.txt"


def test_resolve_icon_path_returns_none_for_shell_namespace(tmp_path: Path) -> None:
    assert layout.resolve_icon_path(str(tmp_path), "此电脑") is None


def test_icon_info_from_display_name_marks_hidden_lnk_as_shortcut(tmp_path: Path) -> None:
    (tmp_path / "PotPlayer 64 bit.lnk").write_text("x", encoding="utf-8")
    info = layout.describe_icon(str(tmp_path), "PotPlayer 64 bit")
    assert info.is_shortcut is True
    assert info.is_special is False
    assert info.ext == ".lnk"


def test_icon_info_from_display_name_marks_shell_namespace_as_system(tmp_path: Path) -> None:
    info = layout.describe_icon(str(tmp_path), "此电脑")
    assert info.is_special is True
    assert info.is_system is True
    assert info.is_shortcut is False


def test_real_user_folder_is_treated_as_system_icon(tmp_path: Path) -> None:
    """桌面上的「用户名」文件夹其实是 %USERPROFILE%，Explorer 显示成用户目录图标。"""
    info = layout.describe_icon(str(tmp_path), Path.home().name, home_exists=True)
    assert info.is_system is True


# ---------------------------------------------------------------- 写完回读校验


def _plan_items() -> list[DesktopIconInfo]:
    return [icon("a.png", ext=".png"), icon("b.txt", ext=".txt")]


def test_apply_layout_reports_misfits_as_error(tmp_path: Path) -> None:
    """Explorer 异步重排把图标挪走后，必须如实报告，而不是假报成功。"""
    items = _plan_items()
    written: dict[str, tuple[int, int]] = {}

    def writer() -> object:
        def _write(name: str, x: int, y: int) -> None:
            written[name] = (x, y)

        return _write

    def reader() -> dict[str, tuple[int, int]]:
        # 第一个图标永远被 Explorer 挪走一格，模拟重排
        out = dict(written)
        first = items[0].name if items else None
        if first and first in out:
            out[first] = (out[first][0], out[first][1] + 104)
        return out

    res = layout.apply_layout(
        "shortcuts_first",
        collect=lambda: items,
        measure=lambda: layout.ScreenWorkArea(0, 0, 1000, 1000, 75, 104),
        snapshot=lambda: {"items": {}, "count": 0},
        save=lambda payload, path: path,
        get_autoarrange=lambda: False,
        set_autoarrange=lambda v: None,
        make_writer=writer,
        read_positions=reader,
        sleep=lambda s: None,
        undo_path=tmp_path / "undo.json",
    )
    assert res["ok"] is True
    assert res["misfit"] >= 1
    assert any("未就位" in e for e in res["errors"])


def test_apply_layout_retries_until_positions_stick(tmp_path: Path) -> None:
    items = _plan_items()
    written: dict[str, tuple[int, int]] = {}
    rounds = {"n": 0}

    def writer() -> object:
        rounds["n"] += 1
        current = rounds["n"]

        def _write(name: str, x: int, y: int) -> None:
            written[name] = (x, y)

        return _write

    reads = {"n": 0}

    def reader() -> dict[str, tuple[int, int]]:
        reads["n"] += 1
        out = dict(written)
        # 前两轮把第一个图标挪走，第三轮起稳定
        first = items[0].name
        if reads["n"] <= 2 and first in out:
            out[first] = (out[first][0], out[first][1] + 104)
        return out

    res = layout.apply_layout(
        "shortcuts_first",
        collect=lambda: items,
        measure=lambda: layout.ScreenWorkArea(0, 0, 1000, 1000, 75, 104),
        snapshot=lambda: {"items": {}, "count": 0},
        save=lambda payload, path: path,
        get_autoarrange=lambda: False,
        set_autoarrange=lambda v: None,
        make_writer=writer,
        read_positions=reader,
        sleep=lambda s: None,
        undo_path=tmp_path / "undo.json",
        attempts=4,
    )
    assert res["misfit"] == 0
    assert res["attempts_used"] >= 2


def test_apply_layout_accepts_composable_keys(tmp_path: Path) -> None:
    items = [
        icon("b.txt", ext=".txt"),
        icon("此电脑", special=True, system=True),
        icon("a.lnk", shortcut=True),
    ]
    written: dict[str, tuple[int, int]] = {}

    def writer() -> object:
        def _write(name: str, x: int, y: int) -> None:
            written[name] = (x, y)

        return _write

    res = layout.apply_layout(
        sort_keys=["system_first", "shortcuts_first", "by_name"],
        collect=lambda: items,
        measure=lambda: layout.ScreenWorkArea(0, 0, 1000, 1000, 75, 104),
        snapshot=lambda: {"items": {}, "count": 0},
        save=lambda payload, path: path,
        get_autoarrange=lambda: False,
        set_autoarrange=lambda v: None,
        make_writer=writer,
        read_positions=lambda: dict(written),
        sleep=lambda s: None,
        undo_path=tmp_path / "undo.json",
    )
    assert res["ok"] is True
    # 系统图标必须占住左上角第一格
    assert written["此电脑"] == (12, 12)


def test_apply_layout_groups_columns_when_asked(tmp_path: Path) -> None:
    items = [
        icon("f.txt", ext=".txt"),
        icon("s.lnk", shortcut=True),
        icon("此电脑", special=True, system=True),
    ]
    written: dict[str, tuple[int, int]] = {}

    def writer() -> object:
        def _write(name: str, x: int, y: int) -> None:
            written[name] = (x, y)

        return _write

    res = layout.apply_layout(
        sort_keys=["by_type", "by_name"],
        group_columns=True,
        collect=lambda: items,
        measure=lambda: layout.ScreenWorkArea(0, 0, 1000, 1000, 75, 104),
        snapshot=lambda: {"items": {}, "count": 0},
        save=lambda payload, path: path,
        get_autoarrange=lambda: False,
        set_autoarrange=lambda v: None,
        make_writer=writer,
        read_positions=lambda: dict(written),
        sleep=lambda s: None,
        undo_path=tmp_path / "undo.json",
    )
    assert res["ok"] is True
    # 三组各不相同 → 各占一列，x 递增而 y 都从顶开始
    assert written["此电脑"] == (12, 12)
    assert written["s.lnk"] == (87, 12)
    assert written["f.txt"] == (162, 12)


# ------------------------------------------------ 桌面其实有两个根（用户 + 公共）


def test_desktop_roots_covers_user_and_public_desktop() -> None:
    roots = layout.desktop_roots()
    assert len(roots) >= 2
    names = {p.name.lower() for p in roots}
    assert "desktop" in names
    # 公共桌面也在其中（否则公共快捷方式会被误判成 shell 系统图标）
    assert any("public" in str(p).lower() for p in roots)


def test_resolve_icon_path_searches_every_root(tmp_path: Path) -> None:
    user = tmp_path / "user"
    public = tmp_path / "public"
    user.mkdir()
    public.mkdir()
    (public / "BilibiliDown.lnk").write_text("x", encoding="utf-8")
    found = layout.resolve_icon_path([user, public], "BilibiliDown")
    assert found is not None
    assert found.name == "BilibiliDown.lnk"


def test_describe_icon_exposes_public_desktop_shortcut(tmp_path: Path) -> None:
    user = tmp_path / "user"
    public = tmp_path / "public"
    user.mkdir()
    public.mkdir()
    (public / "Clash Verge.lnk").write_text("x", encoding="utf-8")
    info = layout.describe_icon([user, public], "Clash Verge")
    assert info.is_shortcut is True
    assert info.is_special is False
    assert info.is_system is False
    assert info.ext == ".lnk"


def test_shortcuts_from_public_desktop_are_not_promoted_as_system(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir()
    (public / "BilibiliDown.lnk").write_text("x", encoding="utf-8")
    shell = layout.describe_icon([public], "此电脑")
    pub_shortcut = layout.describe_icon([public], "BilibiliDown")
    assert shell.is_system is True
    assert pub_shortcut.is_system is False


# ------------------------------------------------- 写完回读：按格子比，不按像素比


def test_apply_layout_treats_snapped_position_as_landed(tmp_path: Path) -> None:
    """Explorer 会把 (12,12) 吸附到 (11,2)。像素不等但同格，不能算未就位。"""
    items = [icon("a.txt", ext=".txt"), icon("b.txt", ext=".txt")]
    written: dict[str, tuple[int, int]] = {}

    def writer() -> object:
        def _write(name: str, x: int, y: int) -> None:
            written[name] = (x, y)

        return _write

    def reader() -> dict[str, tuple[int, int]]:
        # 模拟 Explorer 的网格吸附：x-1、y-10
        return {name: (x - 1, y - 10) for name, (x, y) in written.items()}

    res = layout.apply_layout(
        sort_keys=["by_name"],
        collect=lambda: items,
        measure=lambda: layout.ScreenWorkArea(0, 0, 1000, 1000, 75, 104),
        snapshot=lambda: {"items": {}, "count": 0},
        save=lambda payload, path: path,
        get_autoarrange=lambda: False,
        set_autoarrange=lambda v: None,
        make_writer=writer,
        read_positions=reader,
        sleep=lambda s: None,
        attempts=3,
        undo_path=tmp_path / "undo.json",
    )
    assert res["misfit"] == 0
    assert res["attempts_used"] == 1
    assert res["ok"] is True



# ---------------------------------------------------------------- 撤销的多轮重试


def _undo_fixture(tmp_path: Path):
    from desktop_organizer import iconpos

    snap = iconpos.build_snapshot([('a.txt', 12, 12), ('b.txt', 12, 116)])
    path = tmp_path / 'layout_undo.json'
    iconpos.save_snapshot(snap, path)
    return path


def test_undo_retries_until_shell_settles(tmp_path) -> None:
    path = _undo_fixture(tmp_path)
    reads = iter([
        {'a.txt': (900, 900), 'b.txt': (900, 1000)},  # 第一轮：Shell 还在重排
        {'a.txt': (12, 12), 'b.txt': (12, 116)},      # 第二轮：稳了
    ])
    calls = {'n': 0}

    def reader():
        calls['n'] += 1
        return next(reads, {'a.txt': (12, 12), 'b.txt': (12, 116)})

    result = layout.undo_layout(
        undo_path=path,
        write_position=lambda name, x, y: None,
        make_writer=lambda: (lambda name, x, y: None),
        read_positions=reader,
        get_autoarrange=lambda: False,
        set_autoarrange=lambda value: None,
        sleep=lambda seconds: None,
    )
    assert result['ok'] is True
    assert result['verified'] is True
    assert calls['n'] >= 2


def test_undo_gives_up_after_attempts_and_reports_failure(tmp_path) -> None:
    path = _undo_fixture(tmp_path)
    result = layout.undo_layout(
        undo_path=path,
        write_position=lambda name, x, y: None,
        make_writer=lambda: (lambda name, x, y: None),
        read_positions=lambda: {'a.txt': (900, 900), 'b.txt': (900, 1000)},
        get_autoarrange=lambda: False,
        set_autoarrange=lambda value: None,
        sleep=lambda seconds: None,
        attempts=2,
    )
    assert result['ok'] is False
    assert result['verified'] is False
