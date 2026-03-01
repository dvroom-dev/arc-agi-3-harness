from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

import arc_action


def _frame(levels_completed=0):
    action_id = SimpleNamespace(name="ACTION1", value=1)
    action_input = SimpleNamespace(id=action_id, data={}, reasoning=None)
    return SimpleNamespace(
        game_id="ls20-cb3b57cc",
        guid="g",
        state=SimpleNamespace(value="NOT_FINISHED"),
        levels_completed=levels_completed,
        win_levels=7,
        available_actions=[0, 1, 2, 3, 4],
        full_reset=False,
        action_input=action_input,
        frame=[np.zeros((64, 64), dtype=np.int8)],
    )


def _patch_common(monkeypatch, tmp_path: Path, args: dict):
    arc_dir = tmp_path / "arc"
    arc_dir.mkdir()
    monkeypatch.setenv("ARC_STATE_DIR", str(arc_dir))
    monkeypatch.setenv("ARC_ACTIVE_GAME_ID", "ls20")
    monkeypatch.chdir(tmp_path)
    game_dir = tmp_path / "game_ls20"
    game_dir.mkdir()
    (game_dir / "play_lib.py").write_text("x=1\n")
    monkeypatch.setattr(arc_action, "_read_args", lambda: args)
    monkeypatch.setattr(arc_action, "_ensure_play_lib_file", lambda cwd: game_dir / "play_lib.py")
    monkeypatch.setattr(arc_action, "_load_history", lambda cwd, gid: {"game_id": gid, "events": [], "turn": 0})
    monkeypatch.setattr(arc_action, "_make_env", lambda gid: SimpleNamespace(reset=lambda: _frame()))
    monkeypatch.setattr(arc_action, "_reset_env_with_retry", lambda env, **kwargs: _frame())
    monkeypatch.setattr(arc_action, "_get_pixels", lambda env, frame=None: np.zeros((64, 64), dtype=np.int8))
    monkeypatch.setattr(arc_action, "_save_history", lambda cwd, h: None)
    monkeypatch.setattr(arc_action, "write_game_state", lambda *a, **k: None)
    monkeypatch.setattr(arc_action, "write_machine_state", lambda *a, **k: None)
    monkeypatch.setattr(arc_action, "_write_turn_trace", lambda **k: arc_dir / "trace.md")


def test_main_args_error_branch(monkeypatch, tmp_path: Path) -> None:
    _patch_common(monkeypatch, tmp_path, {"_error": "bad"})
    out = []
    monkeypatch.setattr(arc_action, "_emit_json", lambda payload: out.append(payload))
    rc = arc_action.main()
    assert rc == 1
    assert out[-1]["error"]["type"] == "invalid_args"


def test_main_unknown_action_branch(monkeypatch, tmp_path: Path) -> None:
    _patch_common(monkeypatch, tmp_path, {"action": "unknown", "game_id": "ls20"})
    out = []
    monkeypatch.setattr(arc_action, "_emit_json", lambda payload: out.append(payload))
    rc = arc_action.main()
    assert rc == 1
    assert out[-1]["error"]["type"] == "unknown_action"


def test_main_run_script_invalid_script_path(monkeypatch, tmp_path: Path) -> None:
    _patch_common(
        monkeypatch,
        tmp_path,
        {"action": "run_script", "game_id": "ls20", "script_path": "foo.py", "script": "print(1)"},
    )
    out = []
    monkeypatch.setattr(arc_action, "_emit_json", lambda payload: out.append(payload))
    rc = arc_action.main()
    assert rc == 1
    assert out[-1]["error"]["type"] == "invalid_run_script_args"


def test_main_run_script_missing_inline_script(monkeypatch, tmp_path: Path) -> None:
    _patch_common(monkeypatch, tmp_path, {"action": "run_script", "game_id": "ls20"})
    out = []
    monkeypatch.setattr(arc_action, "_emit_json", lambda payload: out.append(payload))
    rc = arc_action.main()
    assert rc == 1
    assert out[-1]["error"]["type"] == "invalid_run_script_args"


def test_main_reset_level_branch(monkeypatch, tmp_path: Path) -> None:
    _patch_common(monkeypatch, tmp_path, {"action": "reset_level", "game_id": "ls20"})
    env = SimpleNamespace(reset=lambda: _frame())
    monkeypatch.setattr(arc_action, "_make_env", lambda gid: env)
    out = []
    monkeypatch.setattr(arc_action, "_emit_json", lambda payload: out.append(payload))
    rc = arc_action.main()
    assert rc == 0
    assert out[-1]["action"] == "reset_level"
