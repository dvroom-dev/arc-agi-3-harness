from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import harness


def test_harness_main_offline_seeds_env_cache_before_status(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "proj"
    cache_root = tmp_path / "env-cache"
    source_variant = cache_root / "source-run" / "ls20" / "cb3b57cc"
    (root / "tools").mkdir(parents=True)
    (root / "prompts").mkdir(parents=True)
    (root / "runs").mkdir(parents=True)
    (root / "arc_model_runtime").mkdir(parents=True)
    (root / "super.yaml").write_text("runtime_defaults: {}\n")
    (root / "arc_model_runtime" / "__init__.py").write_text("# runtime\n")
    for f in ("arc_repl.py", "arc_repl_cli.py", "arc_repl_daemon.py", "arc_level.py"):
        (root / "tools" / f).write_text("#!/usr/bin/env python3\n")
    (root / "prompts" / "new_game_auto_explore.py").write_text("print('x')\n")
    source_variant.mkdir(parents=True)
    (source_variant / "ls20.py").write_text("# env\n")
    (source_variant / "metadata.json").write_text(
        json.dumps({"game_id": "ls20-cb3b57cc", "local_dir": str(source_variant)}) + "\n"
    )

    args = Namespace(
        game_id="ls20",
        max_turns=0,
        operation_mode="OFFLINE",
        session_name="t-offline",
        verbose=False,
        open_scorecard=False,
        scorecard_id=None,
        provider="mock",
        no_supervisor=True,
        explore_inputs=False,
        max_game_over_resets=1,
        arc_backend="api",
        arc_base_url="http://example.test",
    )
    observed_env_dir = {"path": None}

    def fake_subprocess_run(cmd, **kwargs):
        text_input = kwargs.get("input")
        env = kwargs.get("env") or {}
        if isinstance(text_input, str):
            req = json.loads(text_input)
            if req.get("action") == "status":
                env_dir = Path(env["ARC_ENVIRONMENTS_DIR"])
                observed_env_dir["path"] = env_dir
                copied_metadata = json.loads(
                    (env_dir / "ls20" / "cb3b57cc" / "metadata.json").read_text()
                )
                assert copied_metadata["local_dir"] == str(env_dir / "ls20" / "cb3b57cc")
                payload = {
                    "ok": True,
                    "game_id": "ls20-cb3b57cc",
                    "state": "NOT_FINISHED",
                    "current_level": 1,
                    "levels_completed": 0,
                    "win_levels": 7,
                    "available_actions": [0, 1, 2, 3, 4],
                }
            elif req.get("action") == "shutdown":
                payload = {"ok": True, "action": "shutdown"}
            else:
                payload = {"ok": True}
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_run_super(args, **kwargs):
        out = Path(args[args.index("--output") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "---\nconversation_id: conv-1\nfork_id: fork-1\n---\n```chat role=assistant\nok\n```\n"
        )
        return ""

    monkeypatch.setattr(harness, "PROJECT_ROOT", root)
    monkeypatch.setattr(harness, "CTXS", root / ".ctxs")
    monkeypatch.setattr(harness, "PROJECT_VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(harness, "ARC_ENV_CACHE_ROOT", cache_root)
    monkeypatch.setattr(harness, "parse_args", lambda: args)
    monkeypatch.setattr(
        harness,
        "cleanup_orphan_repl_daemons",
        lambda *a, **k: {"killed": 0, "stale_files_removed": 0, "skipped_active": 0},
    )
    monkeypatch.setattr(harness, "run_super", fake_run_super)
    monkeypatch.setattr(harness.subprocess, "run", fake_subprocess_run)

    harness.main()

    assert observed_env_dir["path"] == cache_root / "t-offline"
