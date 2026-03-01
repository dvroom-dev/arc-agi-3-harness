from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import harness


def test_format_change_records_and_palette_collection() -> None:
    changes = [
        {"row": 1, "col": 2, "before": "A", "after": "F"},
        {"row": 3, "col": 4, "before": "0", "after": "1"},
    ]
    text = harness.format_change_records(changes)
    assert "changed_pixels=2" in text
    assert "(1,2): A->F" in text
    assert harness.collect_palette_from_change_records(changes) == {0, 1, 10, 15}


def test_diff_change_records_shape_mismatch_raises() -> None:
    before = np.zeros((2, 2), dtype=np.int8)
    after = np.zeros((3, 3), dtype=np.int8)
    with pytest.raises(RuntimeError):
        harness.diff_change_records(before, after)


def test_diff_change_records_returns_hex_values() -> None:
    before = np.array([[0, 1], [2, 3]], dtype=np.int8)
    after = np.array([[0, 10], [2, 15]], dtype=np.int8)
    out = harness.diff_change_records(before, after)
    assert out == [
        {"row": 0, "col": 1, "before": "1", "after": "A"},
        {"row": 1, "col": 1, "before": "3", "after": "F"},
    ]


def test_find_click_targets_returns_sorted_regions() -> None:
    pixels = np.zeros((5, 5), dtype=np.int8)
    pixels[0:2, 0:2] = 3  # size 4
    pixels[3:5, 3:5] = 7  # size 4
    pixels[2, 2] = 5  # size 1
    targets = harness.find_click_targets(pixels)
    assert len(targets) == 3
    assert targets[0][3] >= targets[-1][3]


def test_parse_color_id() -> None:
    assert harness._parse_color_id("A") == 10
    assert harness._parse_color_id(15) == 15
    assert harness._parse_color_id(None) is None
    assert harness._parse_color_id("not-hex") is None


def test_summarize_static_features_excludes_colors() -> None:
    pixels = np.array(
        [
            [0, 0, 1, 1],
            [0, 0, 1, 1],
            [2, 2, 0, 0],
            [2, 2, 0, 0],
        ],
        dtype=np.int8,
    )
    lines = harness.summarize_static_features(pixels, excluded_colors={0, 1})
    assert len(lines) == 1
    assert "id=2" in lines[0]


def test_extract_last_assistant_message() -> None:
    transcript = """```chat role=assistant
first
```
```chat role=user
u
```
```chat role=assistant
second
```
"""
    assert harness.extract_last_assistant_message(transcript) == "second"


def test_completion_action_windows_by_level_splits_on_level_gain() -> None:
    events = [
        {"kind": "step", "action": "ACTION3", "levels_completed": 0},
        {"kind": "step", "action": "ACTION1", "levels_completed": 0},
        {"kind": "step", "action": "ACTION4", "levels_completed": 1},
        {"kind": "step", "action": "ACTION2", "levels_completed": 1},
        {"kind": "step", "action": "ACTION2", "levels_completed": 2},
    ]
    windows = harness.completion_action_windows_by_level(events)
    assert windows[1] == ["ACTION3", "ACTION1", "ACTION4"]
    assert windows[2] == ["ACTION2", "ACTION2"]


def test_level_completion_record_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "level_completions.md"
    path.write_text("# Level Completions\n")
    harness.append_level_completion_record(
        completions_file=path,
        completed_level=2,
        actions=["ACTION1", "ACTION2"],
        harness_turn=9,
        tool_turn=42,
        winning_script_relpath="runs/x/script.py",
    )
    text = path.read_text()
    assert "## Level 2 Completion" in text
    assert "ACTION1, ACTION2" in text
    assert harness.read_max_recorded_completion_level(path) == 2


def test_write_prompt_file_with_image(tmp_path: Path) -> None:
    out = tmp_path / "prompt.yaml"
    harness.write_prompt_file(out, "hello\nworld", image_paths=["a.png"])
    content = out.read_text()
    assert "operation: append" in content
    assert "literal: |" in content
    assert "- image: a.png" in content


def test_assert_no_game_files_in_agent_dir(tmp_path: Path) -> None:
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "ok.py").write_text("print('ok')\n")
    harness.assert_no_game_files_in_agent_dir(agent)
    forbidden = agent / "environment_files"
    forbidden.mkdir()
    with pytest.raises(RuntimeError):
        harness.assert_no_game_files_in_agent_dir(agent)


def test_setup_run_dir_seeds_expected_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    agent_dir = run_dir / "agent"
    supervisor_dir = run_dir / "supervisor"
    harness.setup_run_dir(
        run_dir,
        agent_dir,
        supervisor_dir,
        log=lambda _m: None,
        game_id="ls20",
    )
    assert not (agent_dir / "play_lib.py").exists()
    assert (supervisor_dir / "arc" / "level_completions.md").exists()
    assert (agent_dir / "game_ls20" / "play_lib.py").exists()
    assert (agent_dir / "game_ls20" / "theory.md").exists()
    assert (agent_dir / "game_ls20" / "simulate.py").exists()
    assert (agent_dir / "game_ls20" / "play.py").exists()


def test_setup_run_config_dir_creates_wrappers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_root = tmp_path / "root"
    (fake_root / "tools").mkdir(parents=True)
    (fake_root / "prompts").mkdir(parents=True)
    for f in ("arc_repl.py", "arc_repl_cli.py", "arc_repl_daemon.py"):
        (fake_root / "tools" / f).write_text("# tool\n")
    (fake_root / "prompts" / "new_game_auto_explore.py").write_text("print('x')\n")

    monkeypatch.setattr(harness, "PROJECT_ROOT", fake_root)
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", fake_root / ".venv" / "bin" / "python")

    run_config = tmp_path / "cfg"
    bin_dir, tools_dir = harness.setup_run_config_dir(run_config)
    assert (bin_dir / "arc_repl").exists()
    assert (tools_dir / "arc_repl.py").exists()
    assert not (tools_dir / "arc_action.py").exists()
    assert (run_config / "prompts" / "new_game_auto_explore.py").exists()


def test_run_super_batch_success(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="assistant output\n", stderr="warn\n")

    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    out = harness._run_super_batch(["super", "x"], cwd=".")
    assert out == "assistant output"
    err = capsys.readouterr().err
    assert "[super][stdout] assistant output" in err
    assert "[super][stderr] warn" in err


def test_run_super_batch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=7, stdout="", stderr="")

    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        harness._run_super_batch(["super", "x"], cwd=".")


def test_run_super_streaming_extracts_last_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    transcript = """```chat role=assistant
alpha
```
```chat role=assistant
beta
```
"""

    class FakeProc:
        def __init__(self):
            self.stdout = io.StringIO(transcript)
            self.stderr = io.StringIO("")
            self.returncode = 0

        def wait(self):
            return 0

    monkeypatch.setattr(harness.subprocess, "Popen", lambda *a, **k: FakeProc())
    out_path = tmp_path / "session.md"
    last = harness._run_super_streaming(["super"], out_path, cwd=".")
    assert last == "beta"
    assert out_path.read_text() == transcript
    _ = capsys.readouterr().err
