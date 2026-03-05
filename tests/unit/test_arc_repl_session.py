from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import arc_repl


class FakeEnv:
    def __init__(self):
        self.steps = 0
        self.current_levels = 0
        self.resets = 0

    def step(self, action, data=None, reasoning=None):
        self.steps += 1
        action_id = SimpleNamespace(name=getattr(action, "name", str(action)), value=int(action.value))
        action_input = SimpleNamespace(id=action_id, data=data or {}, reasoning=reasoning)
        frame = np.full((64, 64), self.steps % 16, dtype=np.int8)
        state = "NOT_FINISHED"
        if self.steps >= 2:
            state = "WIN"
            self.current_levels = 1
        return SimpleNamespace(
            game_id="ls20-cb3b57cc",
            guid="g",
            state=SimpleNamespace(value=state),
            levels_completed=self.current_levels,
            win_levels=7,
            available_actions=[0, 1, 2, 3, 4],
            full_reset=False,
            action_input=action_input,
            frame=[frame],
        )

    def reset(self):
        self.resets += 1
        self.steps = 0
        self.current_levels = 0
        action_id = SimpleNamespace(name="RESET", value=0)
        action_input = SimpleNamespace(id=action_id, data={}, reasoning=None)
        return SimpleNamespace(
            game_id="ls20-cb3b57cc",
            guid="g",
            state=SimpleNamespace(value="NOT_FINISHED"),
            levels_completed=0,
            win_levels=7,
            available_actions=[0, 1, 2, 3, 4],
            full_reset=False,
            action_input=action_input,
            frame=[np.zeros((64, 64), dtype=np.int8)],
        )


class FakeRegressingEnv(FakeEnv):
    def __init__(self):
        super().__init__()
        self.current_levels = 2

    def reset(self):
        self.resets += 1
        self.steps = 0
        action_id = SimpleNamespace(name="RESET", value=0)
        action_input = SimpleNamespace(id=action_id, data={}, reasoning=None)
        return SimpleNamespace(
            game_id="ls20-cb3b57cc",
            guid="g",
            state=SimpleNamespace(value="NOT_FINISHED"),
            levels_completed=2,
            win_levels=7,
            available_actions=[0, 1, 2, 3, 4],
            full_reset=False,
            action_input=action_input,
            frame=[np.zeros((64, 64), dtype=np.int8)],
        )

    def step(self, action, data=None, reasoning=None):
        self.steps += 1
        action_id = SimpleNamespace(name=getattr(action, "name", str(action)), value=int(action.value))
        action_input = SimpleNamespace(id=action_id, data=data or {}, reasoning=reasoning)
        # Simulate unexpected server-side regression without GAME_OVER.
        frame = np.full((64, 64), self.steps % 16, dtype=np.int8)
        return SimpleNamespace(
            game_id="ls20-cb3b57cc",
            guid="g",
            state=SimpleNamespace(value="NOT_FINISHED"),
            levels_completed=0,
            win_levels=7,
            available_actions=[0, 1, 2, 3, 4],
            full_reset=False,
            action_input=action_input,
            frame=[frame],
        )


def _patch_session_dependencies(monkeypatch, tmp_path: Path):
    arc_dir = tmp_path / "arc"
    arc_dir.mkdir()
    monkeypatch.setenv("ARC_ACTIVE_GAME_ID", "ls20")
    play_lib = tmp_path / "game_ls20" / "play_lib.py"
    play_lib.parent.mkdir(parents=True, exist_ok=True)
    play_lib.write_text("def helper():\n    return 1\n")
    completions = arc_dir / "level_completions.md"
    completions.write_text("# Level Completions\n")
    history = {"game_id": "ls20-cb3b57cc", "events": [], "turn": 0}

    monkeypatch.setenv("ARC_STATE_DIR", str(arc_dir))
    monkeypatch.setattr(arc_repl, "_arc_dir", lambda cwd: arc_dir)
    monkeypatch.setattr(arc_repl, "_ensure_play_lib_file", lambda cwd: play_lib)
    monkeypatch.setattr(arc_repl, "_ensure_level_completions_file", lambda cwd: completions)
    monkeypatch.setattr(arc_repl, "_load_history", lambda cwd, gid: dict(history))
    monkeypatch.setattr(arc_repl, "_save_history", lambda cwd, h: history.update(h))
    monkeypatch.setattr(arc_repl, "_make_env", lambda gid: FakeEnv())
    monkeypatch.setattr(arc_repl, "_reset_env_with_retry", lambda env, **kwargs: env.reset())
    monkeypatch.setattr(arc_repl, "_get_pixels", lambda env, frame=None: frame.frame[-1])
    monkeypatch.setattr(arc_repl, "write_game_state", lambda *a, **k: None)
    monkeypatch.setattr(arc_repl, "write_machine_state", lambda *a, **k: None)
    monkeypatch.setattr(arc_repl, "_write_turn_trace", lambda **k: arc_dir / "trace.md")
    monkeypatch.setattr(arc_repl, "_append_level_completion", lambda **k: None)


def test_repl_session_status_reset_exec(monkeypatch, tmp_path: Path) -> None:
    _patch_session_dependencies(monkeypatch, tmp_path)
    session = arc_repl.ReplSession(
        cwd=tmp_path,
        conversation_id="conv-1",
        requested_game_id="ls20",
    )
    assert "get_action_history" not in session.globals
    assert "get_action_record" not in session.globals

    status = session.do_status("ls20", session_created=True)
    assert status["ok"] is True
    assert status["action"] == "status"
    assert status["current_level"] == 1

    reset = session.do_reset_level("ls20", session_created=False)
    assert reset["ok"] is True
    assert reset["action"] == "reset_level"

    result = session.do_exec(
        "ls20",
        "print('hello')\nenv.step(GameAction.ACTION1)\nenv.step(GameAction.ACTION2)\n",
        session_created=False,
    )
    assert result["action"] == "exec"
    assert result["ok"] is True
    assert result["steps_executed"] >= 1
    assert result["state"] in {"NOT_FINISHED", "WIN"}


def test_repl_history_helpers_can_be_enabled(monkeypatch, tmp_path: Path) -> None:
    _patch_session_dependencies(monkeypatch, tmp_path)
    session = arc_repl.ReplSession(
        cwd=tmp_path,
        conversation_id="conv-1",
        requested_game_id="ls20",
        enable_history_functions=True,
    )
    assert "get_action_history" in session.globals
    assert "get_action_record" in session.globals

    session.set_history_helpers_enabled(False)
    assert "get_action_history" not in session.globals
    assert "get_action_record" not in session.globals

    session.set_history_helpers_enabled(True)
    assert "get_action_history" in session.globals
    assert "get_action_record" in session.globals


def test_repl_reset_level_is_noop_at_level_start(monkeypatch, tmp_path: Path) -> None:
    _patch_session_dependencies(monkeypatch, tmp_path)
    session = arc_repl.ReplSession(
        cwd=tmp_path,
        conversation_id="conv-1",
        requested_game_id="ls20",
    )
    initial_resets = session.env.resets
    result = session.do_reset_level("ls20", session_created=False)
    assert result["ok"] is True
    assert result["action"] == "reset_level"
    assert result["reset_noop"] is True
    assert result["noop_reason"] == "already_at_level_start"
    assert session.env.resets == initial_resets
    assert session.events == []


def test_repl_reset_level_executes_after_step_in_level(monkeypatch, tmp_path: Path) -> None:
    _patch_session_dependencies(monkeypatch, tmp_path)
    session = arc_repl.ReplSession(
        cwd=tmp_path,
        conversation_id="conv-1",
        requested_game_id="ls20",
    )
    initial_resets = session.env.resets
    _ = session.do_exec(
        "ls20",
        "env.step(GameAction.ACTION1)\n",
        session_created=False,
    )
    result = session.do_reset_level("ls20", session_created=False)
    assert result["ok"] is True
    assert result["action"] == "reset_level"
    assert result["reset_noop"] is False
    assert session.env.resets == initial_resets + 1
    assert any(str(e.get("kind", "")).strip() == "reset" for e in session.events)


def test_repl_reset_level_consecutive_guard_with_stale_events(monkeypatch, tmp_path: Path) -> None:
    _patch_session_dependencies(monkeypatch, tmp_path)
    session = arc_repl.ReplSession(
        cwd=tmp_path,
        conversation_id="conv-1",
        requested_game_id="ls20",
    )
    _ = session.do_exec(
        "ls20",
        "env.step(GameAction.ACTION1)\n",
        session_created=False,
    )
    _ = session.do_reset_level("ls20", session_created=False)
    resets_after_first = session.env.resets

    # Simulate stale local step bookkeeping after an out-of-band reset event:
    # event counter says there was activity, but action history says last action
    # already reset this level snapshot.
    session.events.append({"kind": "step", "levels_completed": int(session.frame.levels_completed)})

    result = session.do_reset_level("ls20", session_created=False)
    assert result["ok"] is True
    assert result["action"] == "reset_level"
    assert result["reset_noop"] is True
    assert result["noop_reason"] == "consecutive_reset_guard"
    assert session.env.resets == resets_after_first


def test_repl_main_status_via_send_request(monkeypatch, capsys) -> None:
    monkeypatch.setattr(arc_repl.sys, "argv", ["arc_repl"])
    monkeypatch.setattr(
        arc_repl,
        "_read_args",
        lambda: {"action": "status", "game_id": "ls20"},
    )
    monkeypatch.setattr(
        arc_repl,
        "_send_request",
        lambda cwd, conversation_id, request: (
            {
                "ok": True,
                "action": "status",
                "game_id": "ls20-cb3b57cc",
            },
            True,
        ),
    )
    rc = arc_repl.main()
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["repl"]["session_created"] is True


def test_repl_action_history_contains_before_after_and_diff(monkeypatch, tmp_path: Path) -> None:
    _patch_session_dependencies(monkeypatch, tmp_path)
    session = arc_repl.ReplSession(
        cwd=tmp_path,
        conversation_id="conv-1",
        requested_game_id="ls20",
    )

    _ = session.do_exec(
        "ls20",
        "env.step(GameAction.ACTION1)\nenv.step(GameAction.ACTION2)\n",
        session_created=False,
    )

    history_records = session.get_action_history()
    assert len(history_records) >= 1
    first = history_records[0]
    assert first["action_index"] == 1
    assert first["action_name"].startswith("ACTION")
    assert "state_before" in first
    assert "state_after" in first
    assert "diff" in first
    assert isinstance(first["state_before"]["grid_hex_rows"], list)
    assert isinstance(first["state_after"]["grid_hex_rows"], list)

    from_lookup = session.get_action_record(1)
    assert from_lookup is not None
    assert from_lookup["action_index"] == 1

    history_file = tmp_path / "arc" / "action-history.json"
    assert history_file.exists()
    payload = json.loads(history_file.read_text())
    assert isinstance(payload.get("records"), list)
    assert len(payload["records"]) >= 1


def test_repl_exec_stops_on_unexpected_level_regression(monkeypatch, tmp_path: Path) -> None:
    _patch_session_dependencies(monkeypatch, tmp_path)
    monkeypatch.setattr(arc_repl, "_make_env", lambda gid: FakeRegressingEnv())

    session = arc_repl.ReplSession(
        cwd=tmp_path,
        conversation_id="conv-1",
        requested_game_id="ls20",
    )

    result = session.do_exec(
        "ls20",
        "env.step(GameAction.ACTION1)\nenv.step(GameAction.ACTION2)\n",
        session_created=False,
    )
    assert result["ok"] is False
    assert result["steps_executed"] == 1
    assert "unexpected level regression" in (result.get("script_error") or "")

    history_records = session.get_action_history()
    assert len(history_records) == 1


def test_repl_writes_level_turn_files(monkeypatch, tmp_path: Path) -> None:
    _patch_session_dependencies(monkeypatch, tmp_path)
    session = arc_repl.ReplSession(
        cwd=tmp_path,
        conversation_id="conv-1",
        requested_game_id="ls20",
    )

    _ = session.do_status("ls20", session_created=False)
    _ = session.do_exec(
        "ls20",
        "env.step(GameAction.ACTION1)\n",
        session_created=False,
    )

    game_dir = tmp_path / "game_ls20"
    level_dir = game_dir / "level_1"
    turn_1 = level_dir / "turn_0001"
    turn_2 = level_dir / "turn_0002"

    for turn_dir in (turn_1, turn_2):
        assert (turn_dir / "before_state.hex").exists()
        assert (turn_dir / "after_state.hex").exists()
        assert (turn_dir / "diff.hex").exists()
        assert (turn_dir / "meta.json").exists()
        meta = json.loads((turn_dir / "meta.json").read_text())
        assert meta["schema_version"] == "arc_repl.level_turn_artifact.v1"
        assert meta["tool_turn"] in {1, 2}

    level_index = level_dir / "turn_index.jsonl"
    game_index = game_dir / "turn_index.jsonl"
    assert level_index.exists()
    assert game_index.exists()
    level_entries = [json.loads(line) for line in level_index.read_text().splitlines() if line.strip()]
    game_entries = [json.loads(line) for line in game_index.read_text().splitlines() if line.strip()]
    assert len(level_entries) >= 2
    assert len(game_entries) >= 2
    assert level_entries[-1]["turn_dir"].endswith("turn_0002")

    seq_file = level_dir / "sequences" / "seq_0001.json"
    assert seq_file.exists()
    seq_payload = json.loads(seq_file.read_text())
    assert seq_payload["schema_version"] == "arc_repl.level_sequence.v1"
    assert seq_payload["level"] == 1
    assert seq_payload["action_count"] >= 1
    first_action = seq_payload["actions"][0]
    files = first_action["files"]
    assert (level_dir / files["before_state_hex"]).exists()
    assert (level_dir / files["after_state_hex"]).exists()
    assert (level_dir / files["diff_hex"]).exists()
    assert (level_dir / files["meta_json"]).exists()

    assert (level_dir / "initial_state.hex").exists()
    init_meta = json.loads((level_dir / "initial_state.meta.json").read_text())
    assert init_meta["schema_version"] == "arc_repl.level_initial_state.v1"
    assert init_meta["level"] == 1


def test_repl_sequence_artifacts_split_on_reset(monkeypatch, tmp_path: Path) -> None:
    _patch_session_dependencies(monkeypatch, tmp_path)
    session = arc_repl.ReplSession(
        cwd=tmp_path,
        conversation_id="conv-1",
        requested_game_id="ls20",
    )

    _ = session.do_exec(
        "ls20",
        "env.step(GameAction.ACTION1)\n",
        session_created=False,
    )
    _ = session.do_reset_level("ls20", session_created=False)
    _ = session.do_exec(
        "ls20",
        "env.step(GameAction.ACTION2)\n",
        session_created=False,
    )

    level_dir = tmp_path / "game_ls20" / "level_1"
    seq_1 = json.loads((level_dir / "sequences" / "seq_0001.json").read_text())
    seq_2 = json.loads((level_dir / "sequences" / "seq_0002.json").read_text())
    assert seq_1["end_reason"] == "reset_level"
    assert seq_1["action_count"] == 1
    assert seq_2["action_count"] == 1
