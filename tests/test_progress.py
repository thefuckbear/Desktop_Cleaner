"""进度事件与进度回调的测试。

两层：
- 纯数据层：ProgressEvent 的百分比计算与 JSON 安全；
- 接线层：scanner / executor 的回调被调用、且回调抛异常时不打断业务。
"""

from __future__ import annotations

import json

from desktop_organizer import executor, scanner
from desktop_organizer.model import Plan, PlanAction
from desktop_organizer.progress import ProgressEvent


# ------------------------------------------------------------------ 数据层


def test_percent_is_zero_when_total_is_zero() -> None:
    assert ProgressEvent.create("scan", 0, 0).percent == 0.0


def test_percent_rounds_to_one_decimal() -> None:
    assert ProgressEvent.create("scan", 1, 3).percent == 33.3


def test_percent_is_capped_at_hundred() -> None:
    assert ProgressEvent.create("apply", 200, 100).percent == 100.0


def test_negative_numbers_are_clamped_to_zero() -> None:
    ev = ProgressEvent.create("apply", -5, 10)
    assert ev.current == 0
    assert ev.percent == 0.0


def test_to_dict_is_json_safe_and_complete() -> None:
    ev = ProgressEvent.create("apply", 5, 10, current_item="a.txt", message="正在移动")
    payload = ev.to_dict()
    assert set(payload) == {"stage", "current", "total", "current_item", "percent", "message"}
    assert payload["current_item"] == "a.txt"
    json.dumps(payload)


def test_stage_rejects_unknown_value() -> None:
    try:
        ProgressEvent.create("bogus", 0, 1)  # type: ignore[arg-type]
    except ValueError as exc:
        assert "bogus" in str(exc)
    else:  # pragma: no cover - 只有实现退化时才会走到
        raise AssertionError("未知阶段必须报错")


# ------------------------------------------------------------------ 接线层


def _fake_plan(tmp_path, count: int) -> Plan:
    actions = []
    for i in range(count):
        src = tmp_path / f"f{i}.txt"
        src.write_text("x", encoding="utf-8")
        actions.append(
            PlanAction(
                action_id=f"a{i}",
                src=str(src),
                dst=str(tmp_path / "out" / f"f{i}.txt"),
            )
        )
    return Plan(plan_id="p", root=str(tmp_path), created_at="now", actions=actions)


def test_scan_reports_progress_for_every_item(tmp_path) -> None:
    for i in range(3):
        (tmp_path / f"a{i}.txt").write_text("x", encoding="utf-8")

    seen: list[tuple[int, int]] = []
    scanner.scan(str(tmp_path), max_depth=1, on_progress=lambda d, t, s: seen.append((d, t)))

    assert seen, "扫描必须上报进度"
    assert seen[-1][0] == seen[-1][1], "最后一次上报的 done 必须等于 total"
    assert all(total == seen[-1][1] for _done, total in seen), "total 必须全程一致"


def test_scan_without_callback_still_works(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert scanner.scan(str(tmp_path), max_depth=1)


def test_scan_progress_label_is_the_file_name(tmp_path) -> None:
    (tmp_path / "就要这个.txt").write_text("x", encoding="utf-8")
    labels: list[str] = []
    scanner.scan(str(tmp_path), max_depth=1, on_progress=lambda d, t, s: labels.append(s))
    assert any("就要这个" in label for label in labels)


def test_progress_callback_exception_does_not_break_scan(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")

    def boom(_done: int, _total: int, _label: str) -> None:
        raise RuntimeError("前端炸了")

    assert scanner.scan(str(tmp_path), max_depth=1, on_progress=boom)


def test_execute_reports_progress_per_action(tmp_path) -> None:
    plan = _fake_plan(tmp_path, 3)
    seen: list[tuple[int, int]] = []
    executor.execute(
        plan,
        dry_run=False,
        allow_user_dirs=True,
        progress_cb=lambda d, t, s: seen.append((d, t)),
    )
    assert seen[-1] == (3, 3)
    assert len(seen) == 3


def test_execute_progress_label_is_the_file_name(tmp_path) -> None:
    plan = _fake_plan(tmp_path, 1)
    labels: list[str] = []
    executor.execute(
        plan,
        dry_run=False,
        allow_user_dirs=True,
        progress_cb=lambda d, t, s: labels.append(s),
    )
    assert labels and "f0.txt" in labels[0]


def test_progress_callback_exception_does_not_break_execute(tmp_path) -> None:
    plan = _fake_plan(tmp_path, 2)

    def boom(_done: int, _total: int, _label: str) -> None:
        raise RuntimeError("前端炸了")

    result = executor.execute(plan, dry_run=False, allow_user_dirs=True, progress_cb=boom)
    assert result.applied == 2


def test_rollback_reports_progress(tmp_path) -> None:
    plan = _fake_plan(tmp_path, 2)
    done = executor.execute(plan, dry_run=False, allow_user_dirs=True)

    seen: list[tuple[int, int]] = []
    executor.rollback(
        done.journal_id,
        allow_user_dirs=True,
        restore_icons=False,
        progress_cb=lambda d, t, s: seen.append((d, t)),
    )
    assert seen[-1][0] == seen[-1][1]
    assert seen[-1][1] == 2


def test_execute_without_callback_keeps_old_behaviour(tmp_path) -> None:
    plan = _fake_plan(tmp_path, 2)
    result = executor.execute(plan, dry_run=False, allow_user_dirs=True)
    assert result.applied == 2
    assert result.failed == 0
