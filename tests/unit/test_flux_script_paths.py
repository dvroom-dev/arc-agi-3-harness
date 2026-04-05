from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path


def _load_module(name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[2] / relative_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_rehearse_seed_on_model_resolves_agent_prefixed_paths(tmp_path: Path) -> None:
    _load_module("common", "scripts/flux/common.py")
    rehearse = _load_module("flux_rehearse_seed_test", "scripts/flux/rehearse_seed_on_model.py")
    model_workspace = tmp_path / "game_ls20"
    target = model_workspace / "level_1" / "sequences" / "seq_0007.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"ok":true}\n', encoding="utf-8")

    resolved = rehearse._resolve_rehearsal_path(
        model_workspace,
        "agent/game_ls20/level_1/sequences/seq_0007.json",
    )
    assert resolved == target.resolve()


def test_replay_seed_on_real_game_resolves_agent_prefixed_paths(tmp_path: Path) -> None:
    _load_module("common", "scripts/flux/common.py")
    replay = _load_module("flux_replay_seed_real_test", "scripts/flux/replay_seed_on_real_game.py")
    working_directory = tmp_path / "game_ls20"
    target = working_directory / "level_1" / "sequences" / "seq_0001.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"ok":true}\n', encoding="utf-8")

    resolved = replay._resolve_replay_path(
        working_directory,
        "agent/game_ls20/level_1/sequences/seq_0001.json",
    )
    assert resolved == target.resolve()


def test_validate_replay_shell_cmd_rejects_shell_snippet_array() -> None:
    common = _load_module("flux_common_replay_shell_test", "scripts/flux/common.py")

    try:
        common.validate_replay_shell_cmd(["cd agent/game_ls20 && python - <<'PY'"])
    except RuntimeError as exc:
        assert "direct program token, not a shell snippet" in str(exc)
    else:
        raise AssertionError("expected replay shell validation to reject shell snippet array")


def test_validate_replay_shell_cmd_rejects_non_replayable_program() -> None:
    common = _load_module("flux_common_replay_shell_allowlist_test", "scripts/flux/common.py")

    try:
        common.validate_replay_shell_cmd(["python3", "-c", "print('hi')"])
    except RuntimeError as exc:
        assert "must be one of arc_action, arc_level, arc_repl" in str(exc)
    else:
        raise AssertionError("expected replay shell validation to reject non-replayable program")


def test_copy_model_workspace_ignores_transient_flux_artifacts(tmp_path: Path) -> None:
    common = _load_module("flux_common_snapshot_test", "scripts/flux/common.py")
    source = tmp_path / "agent" / "game_ls20"
    destination = tmp_path / "snapshot" / "game_ls20"
    (source / "level_1").mkdir(parents=True, exist_ok=True)
    (source / "level_1" / "meta.json").write_text("{}\n", encoding="utf-8")
    (source / ".level_6.flux-prev-deadbeef").mkdir(parents=True, exist_ok=True)
    (source / ".level_current.tmp").mkdir(parents=True, exist_ok=True)
    (source / ".workspace-tree.lock").write_text("", encoding="utf-8")
    meta = {"model_workspace_dir": str(source)}

    common.copy_model_workspace(meta, destination)

    assert (destination / "level_1" / "meta.json").exists()
    assert not (destination / ".level_6.flux-prev-deadbeef").exists()
    assert not (destination / ".level_current.tmp").exists()
    assert not (destination / ".workspace-tree.lock").exists()


def test_sync_latest_attempt_to_model_workspace_preserves_richer_level_sequences(tmp_path: Path) -> None:
    common = _load_module("flux_common_latest_instance_test", "scripts/flux/common.py")
    workspace_root = tmp_path / "run"
    attempts_root = workspace_root / "flux_instances"
    solver_name = "game_ls20"

    rich_attempt = attempts_root / "attempt_older"
    sparse_seed = attempts_root / "seed_rev_newer"
    rich_solver = rich_attempt / "agent" / solver_name
    sparse_solver = sparse_seed / "agent" / solver_name
    rich_level = rich_solver / "level_1"
    sparse_level = sparse_solver / "level_1"
    rich_sequences = rich_level / "sequences"
    rich_sequences.mkdir(parents=True, exist_ok=True)
    (rich_sequences / "seq_0001.json").write_text("{}\n", encoding="utf-8")
    (rich_level / "initial_state.hex").write_text("0\n", encoding="utf-8")
    (rich_level / "initial_state.meta.json").write_text("{}\n", encoding="utf-8")

    sparse_level.mkdir(parents=True, exist_ok=True)
    (sparse_level / "initial_state.hex").write_text("0\n", encoding="utf-8")
    (sparse_level / "initial_state.meta.json").write_text("{}\n", encoding="utf-8")
    (sparse_solver / "level_current").mkdir(parents=True, exist_ok=True)
    (sparse_solver / "level_current" / "meta.json").write_text(json.dumps({"level": 1}), encoding="utf-8")
    (sparse_solver / "level_current" / "initial_state.hex").write_text("0\n", encoding="utf-8")
    (sparse_solver / "level_current" / "initial_state.meta.json").write_text("{}\n", encoding="utf-8")

    model_workspace = workspace_root / "agent" / solver_name
    meta = {
        "model_workspace_dir": str(model_workspace),
        "solver_template_dir": str(workspace_root / "flux_seed" / "agent" / solver_name),
    }

    rich_mtime = time.time() - 10
    sparse_mtime = time.time()
    os.utime(rich_attempt, (rich_mtime, rich_mtime))
    os.utime(sparse_seed, (sparse_mtime, sparse_mtime))

    common.sync_latest_attempt_to_model_workspace(str(workspace_root), meta)

    assert (model_workspace / "level_1" / "sequences" / "seq_0001.json").exists()
