from harness import completion_action_windows_by_level


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
