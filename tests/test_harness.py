from harness import (
    HarnessSubprocessError,
    _extract_process_error_detail,
    completion_action_windows_by_level,
)


def test_completion_action_windows_by_level_splits_on_level_gain() -> None:
    events = [
        {"kind": "step", "action": "ACTION3", "levels_completed": 0},
        {"kind": "step", "action": "ACTION1", "levels_completed": 0},
        {"kind": "step", "action": "ACTION4", "levels_completed": 1},
        {"kind": "step", "action": "ACTION2", "levels_completed": 1},
        {"kind": "step", "action": "ACTION2", "levels_completed": 2},
    ]

    windows = completion_action_windows_by_level(events)

    assert windows[1] == ["ACTION3", "ACTION1", "ACTION4"]
    assert windows[2] == ["ACTION2", "ACTION2"]


def test_extract_process_error_detail_prefers_super_error_line() -> None:
    detail = _extract_process_error_detail([
        "[super] status: claude: compacting",
        "[super] Error: Supervisor recovery summary timed out after 300000ms",
    ])
    assert detail == "Supervisor recovery summary timed out after 300000ms"


def test_harness_subprocess_error_exposes_detail() -> None:
    err = HarnessSubprocessError(
        "super exited with code 1: boom",
        process_name="super",
        return_code=1,
        detail="boom",
        stderr_lines=["[super] Error: boom"],
    )
    assert err.process_name == "super"
    assert err.return_code == 1
    assert err.detail == "boom"
    assert err.stderr_lines == ["[super] Error: boom"]
