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
    assert rc == 5
    assert "安全守卫拒绝" in capsys.readouterr().err


def test_scan_rejects_real_desktop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """真实桌面是只读允许的（产品功能），但这里测的是它不会被 guard 当成系统目录误拦。"""
    desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    result = guard.check_read_path(desktop)
    # 只读通道应当允许（产品要能扫描桌面）
    assert result.allowed is True
    # 但写入通道必须拒绝
    assert guard.check_path(desktop).allowed is False


def test_scan_json_output(sandbox_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_files(sandbox_root, ["a.png", "b.txt", "c.zip"])
    rc = cli.main(["scan", "--root", str(sandbox_root), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] >= 3
    names = {i["name"] for i in payload["items"]}
    assert {"a.png", "b.txt", "c.zip"} <= names


def test_plan_json_output(sandbox_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_files(sandbox_root, ["a.png", "b.docx"])
    rc = cli.main(["plan", "--root", str(sandbox_root), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "actions" in payload
    assert "plan_id" in payload
    for action in payload["actions"]:
        assert action["kind"] == "move"
        assert str(sandbox_root) in action["src"]


def test_apply_without_yes_is_rejected(sandbox_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_files(sandbox_root, ["a.png"])
    cli.main(["plan", "--root", str(sandbox_root), "--save", str(sandbox_root / "plan.json")])
    capsys.readouterr()
    rc = cli.main(["apply", "--plan-file", str(sandbox_root / "plan.json"), "--no-dry-run"])
    assert rc == 4
    assert "--yes" in capsys.readouterr().err


def test_plan_save_and_load_roundtrip(sandbox_root: Path) -> None:
    _make_files(sandbox_root, ["a.png", "b.pdf"])
    plan_file = sandbox_root / "plan.json"
    cli.main(["plan", "--root", str(sandbox_root), "--save", str(plan_file)])
    assert plan_file.is_file()
    raw = json.loads(plan_file.read_text(encoding="utf-8"))
    assert raw["root"]
    assert isinstance(raw["actions"], list)


def test_journals_empty(sandbox_root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DESKTOP_ORGANIZER_JOURNAL_DIR", str(sandbox_root / "journals"))
    rc = cli.main(["journals"])
    assert rc == 0
