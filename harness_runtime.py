from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness_runtime_monitor import (
    format_model_status_summary as format_model_status_summary_impl,
    format_state_summary as format_state_summary_impl,
    load_engine_turn as load_engine_turn_impl,
    load_history_events as load_history_events_impl,
    load_history_payload as load_history_payload_impl,
    load_state_json as load_state_json_impl,
    monitor_snapshot as monitor_snapshot_impl,
    resolve_raw_events_path as resolve_raw_events_path_impl,
)
from harness_runtime_env import (
    clear_idle_keepalive_marker_impl,
    has_idle_keepalive_marker_impl,
    idle_keepalive_enabled_impl,
    read_idle_keepalive_marker_impl,
    provider_args_impl,
    refresh_dynamic_super_env_impl,
    supervisor_args_impl,
    write_idle_keepalive_marker_impl,
)
from harness_runtime_cleanup import (
    cleanup_repl_daemons_impl,
    close_scorecard_if_needed_impl,
)
from harness_runtime_conversation import load_conversation_id_impl
from harness_runtime_prompting import (
    load_current_pixels_impl,
    prompt_args_impl,
    update_prompt_game_vars_impl,
)
from harness_runtime_scorecard import open_scorecard_now_impl
from harness_runtime_session import (
    discover_workspace_conversation_id_impl,
    load_conversation_head_metadata_impl,
    recover_session_file_from_workspace_impl,
    session_frontmatter_impl,
    sync_active_conversation_id_from_session_impl,
)
from harness_scorecard_helpers import (
    build_scorecard_client,
    export_scorecard_cookies_json,
    resolve_arc_api_key,
)
from tools.proc_utils import read_proc_start_ticks
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
        self.arc_env_dir = deps.ARC_ENV_CACHE_ROOT / self.session_name
        self.arc_env_dir.mkdir(parents=True, exist_ok=True)
        if self.offline_mode:
            self.log(
                "[harness] seeded offline env cache: "
                f"{deps.seed_arc_environment_cache(self.arc_env_dir, requested_game_id=str(args.game_id))}"
            )
        self.state_json = self.arc_state_dir / "state.json"
        self.history_json = self.arc_state_dir / "tool-engine-history.json"
        self.completions_md = self.arc_state_dir / "level_completions.md"
        self.auto_explore_once_marker = self.arc_state_dir / "auto_explore_once.done"
        self.cycle_limit: int | None = None
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

        self.active_game_id = self.prompt_game_id = str(args.game_id).strip()
        self.prompt_game_slug = self.prompt_game_dir = self.prompt_actions_block = ""
        self.prompt_available_actions: list[int] = []
        self.prompt_actions_game_id: str | None = None
        self.repl_session_key = f"{self.session_name}__{(re.sub(r'[^A-Za-z0-9_.-]+', '_', self.active_game_id).strip('._') or 'game')}"
        self.active_repl_session_key = self.repl_session_key
        self.active_conversation_id = "harness_bootstrap"
        self.active_actual_conversation_id: str | None = None
        self.conversation_aliases: dict[str, str] = {}
        self.last_repl_daemon_pid: int | None = None
        self.update_prompt_game_vars()

        self.prompt_file_counter = 0
        self.repl_parent_pid = int(os.getpid())
        self.repl_parent_start_ticks = read_proc_start_ticks(self.repl_parent_pid)

        self.super_env = dict(os.environ)
        self.super_env["ARC_OPERATION_MODE"] = self.operation_mode_name
        self.super_env["ARC_BACKEND"] = str(getattr(self.args, "arc_backend", "") or "")
        self.super_env["ARC_BASE_URL"] = self.arc_base_url
        self.super_env.setdefault("ARC_ENVIRONMENTS_DIR", str(self.arc_env_dir))
        self.super_env["ARC_STATE_DIR"] = str(self.arc_state_dir)
        self.super_env["ARC_CONFIG_DIR"] = str(self.run_config_dir)
        self.super_env["ONLY_RESET_LEVELS"] = "true"
        if self.arc_api_key:
            self.super_env["ARC_API_KEY"] = self.arc_api_key
        if self.active_scorecard_id:
            self.super_env["ARC_SCORECARD_ID"] = self.active_scorecard_id
        if self.scorecard_cookies_json:
            self.super_env["ARC_SCORECARD_COOKIES"] = self.scorecard_cookies_json
        self.super_env["ARC_REPL_SESSION_KEY"] = self.active_repl_session_key
        self.super_env["ARC_ACTIVE_GAME_ID"] = self.active_game_id
        self.super_env["ARC_PROMPT_GAME_ID"] = self.prompt_game_id
        self.super_env["ARC_PROMPT_GAME_SLUG"] = self.prompt_game_slug
        self.super_env["ARC_PROMPT_GAME_DIR"] = self.prompt_game_dir
        self.super_env["ARC_PROMPT_AVAILABLE_ACTIONS"] = ",".join(str(action) for action in self.prompt_available_actions)
        self.super_env["ARC_PROMPT_ACTIONS_BLOCK"] = self.prompt_actions_block
        self.super_env["ARC_REPL_PARENT_PID"] = str(self.repl_parent_pid)
        if self.repl_parent_start_ticks is not None:
            self.super_env["ARC_REPL_PARENT_START_TICKS"] = str(self.repl_parent_start_ticks)
        self.super_env["PATH"] = f"{self.run_bin_dir}:{os.environ.get('PATH', '')}"

        self.idle_keepalive_marker_path = self.arc_state_dir / "intercepts" / "idle_keepalive.flag"
        self.idle_keepalive_marker_path.parent.mkdir(parents=True, exist_ok=True)
        if self.idle_keepalive_marker_path.exists():
            try:
                self.idle_keepalive_marker_path.unlink()
            except Exception:
                pass
        self.api_idle_keepalive_base_enabled = self.operation_mode_name == "ONLINE" and str(
            getattr(self.args, "arc_backend", "") or ""
        ).strip().lower() == "api"

    def open_scorecard_now(self) -> str: return open_scorecard_now_impl(self)

    def log(self, msg: str) -> None: print(msg, file=self.deps.sys.stderr, flush=True)

    def _build_scorecard_client(self):
        return build_scorecard_client(
            operation_mode_name=self.operation_mode_name, arc_base_url=self.arc_base_url,
            environments_dir=self.arc_env_dir, arc_api_key=self.arc_api_key,
            scorecard_cookies_json=self.scorecard_cookies_json,
        )

    def provider_args(self) -> list[str]: return provider_args_impl(self)

    def supervisor_args(self) -> list[str]: return supervisor_args_impl(self)

    def load_state(self) -> dict | None: return load_state_json_impl(self.state_json)

    def _load_history_payload(self) -> dict[str, Any]: return load_history_payload_impl(self.history_json)

    def load_engine_turn(self) -> int: return load_engine_turn_impl(self.history_json)

    def load_history_events(self) -> list[dict[str, Any]]: return load_history_events_impl(self.history_json)

    def resolve_raw_events_path(self) -> Path | None:
        return resolve_raw_events_path_impl(
            run_dir=self.run_dir, session_file=self.session_file,
            active_actual_conversation_id=self.active_actual_conversation_id,
            active_conversation_id=self.active_conversation_id, load_conversation_id=self.load_conversation_id,
        )

    def monitor_snapshot(self) -> dict[str, Any]:
        return monitor_snapshot_impl(
            state_path=self.state_json,
            history_path=self.history_json,
            model_status_path=self.active_agent_dir() / "model_status.json",
            run_dir=self.run_dir,
            session_file=self.session_file,
            active_actual_conversation_id=self.active_actual_conversation_id,
            active_conversation_id=self.active_conversation_id,
            load_conversation_id=self.load_conversation_id,
        )

    def load_conversation_id(self, doc_path: Path) -> str | None:
        return load_conversation_id_impl(doc_path)

    def format_state_summary(self, state: dict | None, *, history_turn: int | None = None) -> str:
        turn = self.load_engine_turn() if history_turn is None else int(history_turn)
        return format_state_summary_impl(state, history_turn=turn)

    def format_model_status_summary(self, model_status: dict | None) -> str:
        return format_model_status_summary_impl(model_status)

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
        child_env["ARC_BACKEND"] = str(getattr(self.args, "arc_backend", "") or "")
        child_env["ARC_BASE_URL"] = self.arc_base_url
        child_env.setdefault("ARC_ENVIRONMENTS_DIR", str(self.arc_env_dir))
        child_env["ARC_STATE_DIR"] = str(self.arc_state_dir)
        child_env["ARC_CONFIG_DIR"] = str(self.run_config_dir)
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
        child_env["ARC_REPL_PARENT_PID"] = str(self.repl_parent_pid)
        if self.repl_parent_start_ticks is not None:
            child_env["ARC_REPL_PARENT_START_TICKS"] = str(self.repl_parent_start_ticks)

        proc = self.deps.subprocess.run(
            cmd,
            input=json.dumps(request),
            text=True,
            capture_output=True,
            cwd=str(self.active_agent_dir()),
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
                        self.update_prompt_game_vars()
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

    def sync_active_conversation_id_from_session(self) -> None: sync_active_conversation_id_from_session_impl(self)

    def session_frontmatter(self) -> dict[str, str]: return session_frontmatter_impl(self)

    def discover_workspace_conversation_id(self) -> str | None: return discover_workspace_conversation_id_impl(self)

    def recover_session_file_from_workspace(
        self,
        *,
        reason: str,
        force: bool = False,
    ) -> None:
        recover_session_file_from_workspace_impl(self, reason=reason, force=force)

    def load_conversation_head_metadata(self) -> dict[str, str | int | None] | None: return load_conversation_head_metadata_impl(self)

    def load_current_pixels(self):
        return load_current_pixels_impl(self)

    def prompt_args(
        self,
        prompt_text: str,
        *,
        prompt_kind: str,
        image_paths: list[Path] | None = None,
    ) -> list[str]:
        return prompt_args_impl(
            self,
            prompt_text,
            prompt_kind=prompt_kind,
            image_paths=image_paths,
        )

    def refresh_dynamic_super_env(self) -> None:
        self.update_prompt_game_vars()
        refresh_dynamic_super_env_impl(self)

    def resume_super(self, prompt: str | None = None, *, image_paths: list[Path] | None = None) -> str:
        self.refresh_dynamic_super_env()
        self.recover_session_file_from_workspace(reason="pre-resume")
        self.log(f"[harness] super agent-dir: {self.active_agent_dir()}")
        resume_args: list[str] = [
            "resume",
            "--workspace", str(self.run_dir),
            "--config", str(self.super_config),
            "--config-dir", str(self.run_config_dir),
            "--agent-dir", str(self.active_agent_dir()),
            "--supervisor-dir", str(self.supervisor_dir),
            *self.provider_args(),
            *self.supervisor_args(),
        ]
        if self.cycle_limit is not None:
            resume_args += ["--cycle-limit", str(self.cycle_limit)]
        if prompt:
            resume_args += self.prompt_args(prompt, prompt_kind="resume", image_paths=image_paths)
        resume_args += ["--output", str(self.session_file)]
        stdout = self.deps.run_super(resume_args, stream=True, cwd=self.run_dir, env=self.super_env)
        self.recover_session_file_from_workspace(reason="post-resume", force=True)
        return stdout

    def cleanup_repl_daemons(self) -> None:
        cleanup_repl_daemons_impl(self)

    def close_scorecard_if_needed(self) -> None:
        close_scorecard_if_needed_impl(self)

    def has_idle_keepalive_marker(self) -> bool:
        return has_idle_keepalive_marker_impl(self)

    def read_idle_keepalive_marker(self) -> str | None:
        return read_idle_keepalive_marker_impl(self)

    def idle_keepalive_enabled(self) -> bool:
        return idle_keepalive_enabled_impl(self)

    def write_idle_keepalive_marker(self, *, marker: str, details: str = "") -> None:
        write_idle_keepalive_marker_impl(self, marker=marker, details=details)

    def clear_idle_keepalive_marker(self) -> None:
        clear_idle_keepalive_marker_impl(self)

    def update_prompt_game_vars(self) -> None:
        update_prompt_game_vars_impl(self)

    def active_agent_dir(self) -> Path:
        """Return the current game-scoped agent directory for super --agent-dir."""
        if self.prompt_game_dir:
            return Path(self.prompt_game_dir)
        return self.agent_dir
