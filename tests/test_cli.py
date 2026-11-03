"""CLI 集成测试：子命令可跑、dry-run 默认、双开关防误操作。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from desktop_organizer import cli, guard
from desktop_organizer.constants import DEFAULT_DRY_RUN


def _make_files(root: Path, names: list[str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for n in names:
        (root / n).write_bytes(b"x" * 16)


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "Desktop Organizer" in capsys.readouterr().out


def test_default_dry_run_constant() -> None:
    assert DEFAULT_DRY_RUN is True


def test_scan_rejects_system_dir(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["scan", "--root", r"C:\Windows\System32"])
    captured = capsys.readouterr()
    assert rc == 5
    assert captured.err.strip() != ""


def test_guard_allows_read_but_denies_write_on_real_desktop() -> None:
    """真实桌面必须可只读枚举（产品功能），但写入必须被硬拒绝。"""
    desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    if not os.path.isdir(desktop):
        pytest.skip("no desktop dir")
    assert guard.check_read_path(desktop).allowed is True
    assert guard.check_path(desktop).allowed is False


def test_scan_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_files(tmp_path, ["a.png", "b.txt", "c.zip"])
    rc = cli.main(["scan", "--root", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] >= 3
    names = {i["name"] for i in payload["items"]}
    assert {"a.png", "b.txt", "c.zip"} <= names


def test_plan_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_files(tmp_path, ["a.png", "b.docx"])
    rc = cli.main(["plan", "--root", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "actions" in payload and "plan_id" in payload
    root_norm = os.path.normcase(os.path.abspath(tmp_path))
    for action in payload["actions"]:
        assert action["kind"] == "move"
        assert os.path.normcase(action["src"]).startswith(root_norm)


def test_apply_without_yes_is_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_files(tmp_path, ["a.png"])
    cli.main(["plan", "--root", str(tmp_path), "--save", str(tmp_path / "plan.json")])
    capsys.readouterr()
    rc = cli.main(["apply", "--plan-file", str(tmp_path / "plan.json"), "--no-dry-run"])
    captured = capsys.readouterr()
    assert rc == 4
    assert "--yes" in captured.err


def test_plan_save_and_load_roundtrip(tmp_path: Path) -> None:
    _make_files(tmp_path, ["a.png", "b.pdf"])
    plan_file = tmp_path / "plan.json"
    cli.main(["plan", "--root", str(tmp_path), "--save", str(plan_file)])
    assert plan_file.is_file()
    raw = json.loads(plan_file.read_text(encoding="utf-8"))
    assert raw["root"]
    assert isinstance(raw["actions"], list)


def test_journals_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DESKTOP_ORGANIZER_JOURNAL_DIR", str(tmp_path / "journals"))
    rc = cli.main(["journals"])
    assert rc == 0


def test_allow_user_dirs_flag_is_parsed() -> None:
    args = cli.build_parser().parse_args(["apply", "--allow-user-dirs"])
    assert args.allow_user_dirs is True
    assert cli._permitted(args) is True


def test_permission_falls_back_to_persisted_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from desktop_organizer import settings

    pref = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "settings_path", lambda path=None: pref)

    args = cli.build_parser().parse_args(["apply"])
    assert args.allow_user_dirs is False
    assert cli._permitted(args) is False  # 默认拒绝

    settings.set_allow_user_dirs(True)
    assert cli._permitted(args) is True  # 界面里打开过 -> 自动生效


def test_rollback_accepts_journal_and_icon_opt_out() -> None:
    """`rollback --journal X` 与 `--no-restore-icons` 都必须能被解析。

    历史坑：曾有人把 journal id 当位置参数传给 rollback，argparse 直接
    `unrecognized arguments` 退出，看起来像"回滚没生效"。
    """
    args = cli.build_parser().parse_args(
        ["rollback", "--journal", "j-20260101-000000-abcdef12", "--no-restore-icons"]
    )
    assert args.journal == "j-20260101-000000-abcdef12"
    assert args.no_restore_icons is True

    plain = cli.build_parser().parse_args(["rollback"])
    assert plain.no_restore_icons is False
