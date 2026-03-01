from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from harness_runtime_cleanup import (
    cleanup_repl_daemons_impl,
    close_scorecard_if_needed_impl,
)
from harness_scorecard_helpers import (
    build_scorecard_client,
    export_scorecard_cookies_json,
    resolve_arc_api_key,
)


class HarnessRuntime:
    def __init__(
        self,
        deps,
        args,
        *,
        operation_mode_name: str,
        arc_base_url: str,
    ) -> None:
        self.deps = deps
        self.args = args
        self.operation_mode_name = operation_mode_name
        self.arc_base_url = arc_base_url
        self.offline_mode = operation_mode_name == "OFFLINE"

        self.session_name = args.session_name or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = deps.CTXS / self.session_name
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.session_dir / "session.md"
        self.tmp_session = self.session_dir / "session.next.md"

        self.run_dir = deps.PROJECT_ROOT / "runs" / self.session_name
        cleanup_stats = deps.cleanup_orphan_repl_daemons(
            deps.PROJECT_ROOT,
            preserve_run_ids={self.session_name},
        )
        if cleanup_stats["killed"] or cleanup_stats["stale_files_removed"]:
            self.log(
                "[harness] cleaned stale repl daemons: "
                f"killed={cleanup_stats['killed']} "
                f"stale_pid_files_removed={cleanup_stats['stale_files_removed']} "
                f"skipped_active={cleanup_stats['skipped_active']}"
            )

        self.agent_dir = self.run_dir / "agent"
        self.supervisor_dir = self.run_dir / "supervisor"
        self.run_config_dir = self.run_dir / "config"
        deps.setup_run_dir(
            self.run_dir,
            self.agent_dir,
            self.supervisor_dir,
            self.log,
            game_id=str(args.game_id),
        )
        self.run_bin_dir, self.run_tools_dir = deps.setup_run_config_dir(self.run_config_dir)
        deps.assert_no_game_files_in_agent_dir(self.agent_dir)
        self.run_super_config = self.run_dir / "super.yaml"
        self.run_super_config.write_text((deps.PROJECT_ROOT / "super.yaml").read_text())
        self.super_config = self.run_super_config

        if not deps.PROJECT_VENV_PYTHON.exists():
            self.log(f"[harness] missing python runtime: {deps.PROJECT_VENV_PYTHON}")
            self.log("[harness] run `uv sync` in project root and retry")
            deps.sys.exit(1)

        self.run_arc_repl_tool = self.run_tools_dir / "arc_repl.py"
        if not self.run_arc_repl_tool.exists():
            self.log(f"[harness] missing tool script: {self.run_arc_repl_tool}")
            deps.sys.exit(1)

        self.arc_state_dir = self.supervisor_dir / "arc"
        self.arc_env_dir = Path("/tmp/arc-agi-env-cache") / self.session_name
        self.arc_env_dir.mkdir(parents=True, exist_ok=True)
        self.state_json = self.arc_state_dir / "state.json"
        self.history_json = self.arc_state_dir / "tool-engine-history.json"
        self.completions_md = self.arc_state_dir / "level_completions.md"
        self.auto_explore_once_marker = self.arc_state_dir / "auto_explore_once.done"
        self.cycle_limit = 1
        self.scorecard_meta_path = self.session_dir / "scorecard.json"
        self.arc_api_key = resolve_arc_api_key()
        self.arc_api_key_prefix = self.arc_api_key[:8] if self.arc_api_key else None

        self.active_scorecard_id = str(args.scorecard_id or "").strip() or None
        self.scorecard_cookies_json = str(getattr(args, "scorecard_cookies_json", "") or "").strip() or None
        self.scorecard_created_here = False
        self.scorecard_api_url: str | None = None
        self.scorecard_web_url: str | None = None
        self.scorecard_client: Any | None = None

        if args.open_scorecard or self.active_scorecard_id:
            if self.operation_mode_name != "ONLINE":
                raise RuntimeError(
                    "Scorecards require ONLINE mode. Re-run with --operation-mode ONLINE."
                )
            if not self.arc_api_key:
                raise RuntimeError(
                    "ARC_API_KEY is required for scored runs. "
                    "Refusing to run with an anonymous key."
                )
            self.scorecard_client = self._build_scorecard_client()
            if self.active_scorecard_id:
                skip_get_validation = bool(getattr(args, "skip_scorecard_get_validation", False))
                if not skip_get_validation:
                    self.scorecard_client.get_scorecard(self.active_scorecard_id)
            else:
                tags = ["arc-agi-harness", "tool-driven", f"game:{args.game_id}"]
                opaque = {
                    "session_name": self.session_name,
                    "game_id": str(args.game_id),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
                self.active_scorecard_id = str(self.scorecard_client.open_scorecard(tags=tags, opaque=opaque))
                self.scorecard_created_here = True
            if not self.scorecard_cookies_json:
                self.scorecard_cookies_json = export_scorecard_cookies_json(self.scorecard_client)
            self.scorecard_api_url = f"{self.arc_base_url.rstrip('/')}/api/scorecard/{self.active_scorecard_id}"
            self.scorecard_web_url = f"{self.arc_base_url.rstrip('/')}/scorecards/{self.active_scorecard_id}"
            self.scorecard_meta_path.write_text(
                json.dumps(
                    {
                        "scorecard_id": self.active_scorecard_id,
                        "api_url": self.scorecard_api_url,
                        "web_url": self.scorecard_web_url,
                        "created_here": self.scorecard_created_here,
                        "operation_mode": self.operation_mode_name,
                        "arc_base_url": self.arc_base_url,
                        "api_key_prefix": self.arc_api_key_prefix,
                        "scorecard_cookies_present": bool(self.scorecard_cookies_json),
                    },
                    indent=2,
                )
                + "\n"
            )

        self.active_game_id = str(args.game_id).strip()
        self.repl_session_key = f"{self.session_name}__{(re.sub(r'[^A-Za-z0-9_.-]+', '_', self.active_game_id).strip('._') or 'game')}"
        self.active_repl_session_key = self.repl_session_key
        self.active_conversation_id = "harness_bootstrap"
        self.active_actual_conversation_id: str | None = None
        self.conversation_aliases: dict[str, str] = {}
        self.last_repl_daemon_pid: int | None = None

        self.prompt_file_counter = 0
        self.enable_level_start_images = False
        self.last_prompted_image_level: int | None = None
        self.level_start_images_dir = self.supervisor_dir / "arc" / "level-start-images"
        self.level_start_images_dir.mkdir(parents=True, exist_ok=True)
        self.current_level_start_image = self.supervisor_dir / "arc" / "current-level-start.png"

        self.super_env = dict(os.environ)
        self.super_env["ARC_OPERATION_MODE"] = self.operation_mode_name
        self.super_env["ARC_BASE_URL"] = self.arc_base_url
        self.super_env.setdefault("ARC_ENVIRONMENTS_DIR", str(self.arc_env_dir))
        self.super_env["ARC_STATE_DIR"] = str(self.arc_state_dir)
        self.super_env["ONLY_RESET_LEVELS"] = "true"
        if self.arc_api_key:
            self.super_env["ARC_API_KEY"] = self.arc_api_key
        if self.active_scorecard_id:
            self.super_env["ARC_SCORECARD_ID"] = self.active_scorecard_id
        if self.scorecard_cookies_json:
            self.super_env["ARC_SCORECARD_COOKIES"] = self.scorecard_cookies_json
        self.super_env["ARC_REPL_SESSION_KEY"] = self.active_repl_session_key
        self.super_env["ARC_ACTIVE_GAME_ID"] = self.active_game_id
        self.super_env["PATH"] = f"{self.run_bin_dir}:{os.environ.get('PATH', '')}"

    def log(self, msg: str) -> None:
        print(msg, file=self.deps.sys.stderr, flush=True)

    def _build_scorecard_client(self):
        return build_scorecard_client(
            operation_mode_name=self.operation_mode_name,
            arc_base_url=self.arc_base_url,
            environments_dir=self.arc_env_dir,
            arc_api_key=self.arc_api_key,
            scorecard_cookies_json=self.scorecard_cookies_json,
        )

    def provider_args(self) -> list[str]:
        return ["--provider", self.args.provider] if self.args.provider else []

    def supervisor_args(self) -> list[str]:
        return ["--no-supervisor"] if self.args.no_supervisor else []

    def load_state(self) -> dict | None:
        if not self.state_json.exists():
            return None
        try:
            data = json.loads(self.state_json.read_text())
            if not isinstance(data, dict):
                raise RuntimeError("state.json must contain a JSON object")
            return data
        except Exception as exc:
            raise RuntimeError(f"Failed to parse state JSON: {self.state_json}: {exc}") from exc

    def load_engine_turn(self) -> int:
        if not self.history_json.exists():
            return 0
        try:
            data = json.loads(self.history_json.read_text())
            if not isinstance(data, dict):
                raise RuntimeError("tool-engine-history.json must contain a JSON object")
            turn = data.get("turn", 0)
            if not isinstance(turn, int):
                raise RuntimeError("tool-engine-history.json turn must be an integer")
            return int(turn)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to parse engine history JSON: {self.history_json}: {exc}"
            ) from exc

    def load_conversation_id(self, doc_path: Path) -> str | None:
        if not doc_path.exists():
            return None
        try:
            text = doc_path.read_text()
        except Exception:
            return None
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return None
        for line in lines[1:80]:
            if line.strip() == "---":
                break
            m = re.match(r"^\s*conversation_id\s*:\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip()
        return None

    def format_state_summary(self, state: dict | None) -> str:
        if not state:
            return "State unavailable."
        telemetry = state.get("telemetry") if isinstance(state.get("telemetry"), dict) else {}
        steps_since_reset = telemetry.get("steps_since_last_reset", "n/a")
        action_input = state.get("action_input_name", "?")
        full_reset = state.get("full_reset", False)
        return (
            f"state={state.get('state','?')} level={state.get('current_level','?')} "
            f"levels={state.get('levels_completed','?')}/{state.get('win_levels','?')} "
            f"last_action={state.get('last_action','?')} "
            f"action_input={action_input} full_reset={full_reset} "
            f"tool_turn={self.load_engine_turn()} steps_since_last_reset={steps_since_reset}"
        )

    def run_arc_repl(self, payload: dict) -> tuple[dict | None, str, int]:
        request = dict(payload)
        action_name = str(request.get("action", "")).strip()
        requested_game_id = str(request.get("game_id", "")).strip()
        if requested_game_id:
            if (
                self.active_game_id
                and requested_game_id == str(self.args.game_id).strip()
                and self.active_game_id != requested_game_id
            ):
                request["game_id"] = self.active_game_id
        elif self.active_game_id:
            request["game_id"] = self.active_game_id

        cmd = [
            str(self.deps.PROJECT_VENV_PYTHON),
            str(self.run_arc_repl_tool),
        ]
        child_env = dict(os.environ)
        child_env["ARC_OPERATION_MODE"] = str(self.args.operation_mode).strip().upper()
        child_env["ARC_BASE_URL"] = self.arc_base_url
        child_env.setdefault("ARC_ENVIRONMENTS_DIR", str(self.arc_env_dir))
        child_env["ARC_STATE_DIR"] = str(self.arc_state_dir)
        child_env["ONLY_RESET_LEVELS"] = "true"
        if self.arc_api_key:
            child_env["ARC_API_KEY"] = self.arc_api_key
        child_env["ARC_CONVERSATION_ID"] = self.active_conversation_id
        child_env["ARC_ACTIVE_GAME_ID"] = self.active_game_id or str(self.args.game_id).strip()
        if self.active_scorecard_id:
            child_env["ARC_SCORECARD_ID"] = self.active_scorecard_id
        if self.scorecard_cookies_json:
            child_env["ARC_SCORECARD_COOKIES"] = self.scorecard_cookies_json
        child_env["ARC_REPL_SESSION_KEY"] = self.active_repl_session_key

        proc = self.deps.subprocess.run(
            cmd,
            input=json.dumps(request),
            text=True,
            capture_output=True,
            cwd=str(self.agent_dir),
            env=child_env,
        )
        if proc.stderr.strip():
            for line in proc.stderr.strip().splitlines():
                self.log(f"[arc_repl] {line}")

        stdout = proc.stdout.strip()
        parsed: dict | None = None
        allow_raw_stdout = action_name == "exec"
        if allow_raw_stdout:
            return None, stdout, proc.returncode

        if stdout:
            try:
                maybe = json.loads(stdout)
            except Exception as exc:
                if proc.returncode == 0:
                    preview = stdout[:800].replace("\n", "\\n")
                    raise RuntimeError(
                        "arc_repl returned non-JSON stdout despite success status: "
                        f"{exc}. stdout_preview={preview}"
                    ) from exc
            else:
                if isinstance(maybe, dict):
                    parsed = maybe
                    if (
                        self.active_scorecard_id
                        and action_name == "status"
                        and proc.returncode == 0
                    ):
                        echoed_scorecard_id = str(parsed.get("scorecard_id", "") or "").strip()
                        if echoed_scorecard_id != self.active_scorecard_id:
                            raise RuntimeError(
                                "arc_repl status did not echo expected scorecard_id: "
                                f"expected={self.active_scorecard_id!r} "
                                f"got={echoed_scorecard_id!r}"
                            )
                    resolved_game_id = str(parsed.get("game_id", "")).strip()
                    if resolved_game_id:
                        self.active_game_id = resolved_game_id
                        self.super_env["ARC_ACTIVE_GAME_ID"] = self.active_game_id
                    repl_meta = parsed.get("repl")
                    if isinstance(repl_meta, dict):
                        daemon_pid_raw = repl_meta.get("daemon_pid")
                        daemon_pid: int | None = None
                        try:
                            daemon_pid = int(daemon_pid_raw)
                        except Exception:
                            daemon_pid = None
                        if daemon_pid is not None:
                            session_created = bool(repl_meta.get("session_created", False))
                            if self.last_repl_daemon_pid is None:
                                self.log(
                                    "[harness] arc_repl daemon active: "
                                    f"pid={daemon_pid} session_key={self.active_repl_session_key} "
                                    f"session_created={session_created}"
                                )
                            elif daemon_pid != self.last_repl_daemon_pid:
                                daemon_dir = (
                                    self.arc_state_dir
                                    / "repl-sessions"
                                    / self.active_repl_session_key
                                )
                                self.log(
                                    "[harness] WARNING: arc_repl daemon pid changed: "
                                    f"old={self.last_repl_daemon_pid} new={daemon_pid} "
                                    f"action={action_name} session_created={session_created}. "
                                    f"Inspect {daemon_dir / 'daemon.log'} and "
                                    f"{daemon_dir / 'daemon.lifecycle.jsonl'}."
                                )
                            self.last_repl_daemon_pid = daemon_pid
                elif proc.returncode == 0:
                    raise RuntimeError(
                        "arc_repl returned JSON that is not an object on success."
                    )
        elif proc.returncode == 0:
            raise RuntimeError("arc_repl returned empty stdout on success.")

        return parsed, stdout, proc.returncode

    def sync_active_conversation_id_from_session(self) -> None:
        parsed = self.load_conversation_id(self.session_file)
        if not parsed:
            return
        alias = self.conversation_aliases.get(parsed)
        if alias is None:
            if (
                self.active_actual_conversation_id is None
                and self.active_conversation_id == "harness_bootstrap"
            ):
                alias = self.active_conversation_id
            else:
                alias = parsed
            self.conversation_aliases[parsed] = alias
        if parsed != self.active_actual_conversation_id:
            self.log(
                "[harness] conversation update: "
                f"actual={parsed} repl_session={alias}"
            )
        self.active_actual_conversation_id = parsed
        self.active_conversation_id = alias

    def load_current_pixels(self) -> np.ndarray | None:
        grid_path = self.arc_state_dir / "current_grid.npy"
        if not grid_path.exists():
            return None
        try:
            return np.load(grid_path)
        except Exception as exc:
            raise RuntimeError(f"Failed to load current grid file: {grid_path}: {exc}") from exc

    def prompt_args(
        self,
        prompt_text: str,
        *,
        prompt_kind: str,
        image_paths: list[Path] | None = None,
    ) -> list[str]:
        if image_paths:
            self.prompt_file_counter += 1
            prompt_file = self.session_dir / f"{prompt_kind}.prompt.{self.prompt_file_counter:04d}.yaml"
            self.deps.write_prompt_file(prompt_file, prompt_text, image_paths=image_paths)
            return ["--prompt-file", str(prompt_file)]
        return ["--prompt", prompt_text]

    def level_start_prompt_images(self, state: dict | None, *, initial: bool = False) -> list[Path]:
        if not self.enable_level_start_images:
            return []
        if not state:
            raise RuntimeError(
                "Cannot determine level-start prompt image: state is unavailable."
            )
        try:
            level = int(state.get("current_level", 0) or 0)
        except Exception:
            raise RuntimeError(
                "Cannot determine level-start prompt image: invalid current_level in state."
            )
        if level <= 0:
            raise RuntimeError(
                f"Cannot determine level-start prompt image: invalid current_level={level}."
            )

        per_level_image = self.level_start_images_dir / f"level_{level:02d}-start.png"
        if not per_level_image.exists():
            pixels = self.load_current_pixels()
            if pixels is None:
                raise RuntimeError(
                    "Unable to generate level-start image: missing current grid "
                    f"at {self.arc_state_dir / 'current_grid.npy'}."
                )
            try:
                self.deps.render_grid_to_image(pixels, per_level_image, scale=8, grid_lines=False)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to render level-start image for level {level}: {exc}"
                ) from exc
            if not per_level_image.exists():
                raise RuntimeError(
                    f"Level-start image generation failed for level {level}: "
                    f"{per_level_image} was not created."
                )

        if (
            (not self.current_level_start_image.exists())
            or self.current_level_start_image.read_bytes() != per_level_image.read_bytes()
        ):
            shutil.copyfile(per_level_image, self.current_level_start_image)

        should_attach = initial or (self.last_prompted_image_level != level)
        self.last_prompted_image_level = level
        return [self.current_level_start_image] if should_attach else []

    def resume_super(self, prompt: str | None = None, *, image_paths: list[Path] | None = None) -> str:
        self.super_env["ARC_CONVERSATION_ID"] = self.active_conversation_id
        self.super_env["ARC_ACTIVE_GAME_ID"] = self.active_game_id
        resume_args: list[str] = [
            "resume",
            str(self.session_file),
            "--config", str(self.super_config),
            "--workspace", str(self.run_dir),
            "--config-dir", str(self.run_config_dir),
            "--agent-dir", str(self.agent_dir),
            "--supervisor-dir", str(self.supervisor_dir),
            *self.provider_args(),
            *self.supervisor_args(),
            "--cycle-limit", str(self.cycle_limit),
        ]
        if prompt:
            resume_args += self.prompt_args(prompt, prompt_kind="resume", image_paths=image_paths)
        if self.args.verbose:
            resume_args += ["--output", str(self.session_file)]
            return self.deps.run_super(resume_args, stream=True, cwd=self.run_dir, env=self.super_env)

        resume_args += ["--output", str(self.tmp_session)]
        stdout = self.deps.run_super(resume_args, cwd=self.run_dir, env=self.super_env)
        shutil.move(str(self.tmp_session), str(self.session_file))
        return stdout

    def cleanup_repl_daemons(self) -> None:
        cleanup_repl_daemons_impl(self)

    def close_scorecard_if_needed(self) -> None:
        close_scorecard_if_needed_impl(self)
