from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import harness_runtime_arc_repl


def test_resume_super_supports_image_only_prompt_file(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def run_super(args, *, stream, cwd, env):
        captured["args"] = list(args)
        return ""

    runtime = SimpleNamespace(
        run_dir=tmp_path,
        super_config=tmp_path / "super.yaml",
        run_config_dir=tmp_path / "config",
        supervisor_dir=tmp_path / "supervisor",
        session_file=tmp_path / "session.md",
        cycle_limit=1,
        super_env={},
        deps=SimpleNamespace(run_super=run_super),
        refresh_dynamic_super_env=lambda: None,
        recover_session_file_from_workspace=lambda **kwargs: None,
        active_agent_dir=lambda: tmp_path / "agent",
        provider_args=lambda: [],
        supervisor_args=lambda: [],
        prompt_args=lambda prompt_text, *, prompt_kind, image_paths=None: ["--prompt-file", "resume.prompt.yaml"],
        log=lambda *args, **kwargs: None,
        phase_scope=lambda **kwargs: _NoopPhase(),
    )

    image_path = tmp_path / "level_001_initial.png"
    image_path.write_bytes(b"png")
    harness_runtime_arc_repl.resume_super_impl(runtime, image_paths=[image_path])

    args = captured["args"]
    assert "--prompt-file" in args
    assert "resume.prompt.yaml" in args


class _NoopPhase:
    def __enter__(self):
        return {}

    def __exit__(self, exc_type, exc, tb):
        return False
