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
from harness_runtime_cleanup import cleanup_repl_daemons_impl, close_scorecard_if_needed_impl
from harness_runtime_conversation import load_conversation_id_impl
from harness_runtime_arc_repl import run_arc_repl_impl, resume_super_impl
from harness_runtime_prompting import (
    load_current_pixels_impl,
    prompt_args_impl,
    update_prompt_game_vars_impl,
)
from harness_runtime_images import (
    ensure_level_start_prompt_image_impl,
    level_start_prompt_images_impl,
)
from harness_runtime_scorecard import open_scorecard_now_impl
from harness_runtime_session import (
    discover_workspace_conversation_id_impl,
    load_conversation_head_metadata_impl,
    recover_session_file_from_workspace_impl,
    session_frontmatter_impl,
    sync_active_conversation_id_from_session_impl,
)
from harness_runtime_validation import validate_run_super_config_text
from harness_runtime_telemetry import append_phase_timing_impl, phase_scope_impl
from harness_scorecard_helpers import build_scorecard_client, export_scorecard_cookies_json, resolve_arc_api_key
from tools.proc_utils import read_proc_start_ticks
from harness_wrapup import (
    certify_or_block_wrapup_transition_impl,
    force_recover_mode_impl,
    repair_stale_wrapup_mode_impl,
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
        self.run_dir = deps.PROJECT_ROOT / "runs" / self.session_name
        self.telemetry_dir = self.run_dir / "telemetry"
        self.phase_timings_path = self.telemetry_dir / "harness_phases.ndjson"
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
        orphan_run_process_stats = deps.cleanup_orphan_run_processes(
            deps.PROJECT_ROOT,
            preserve_run_ids={self.session_name},
        )
        if orphan_run_process_stats["killed"]:
            self.log(
                "[harness] cleaned orphan run processes: "
                f"killed={orphan_run_process_stats['killed']} "
                f"skipped_active={orphan_run_process_stats['skipped_active']}"
            )

        self.agent_dir = self.run_dir / "agent"
        self.supervisor_dir = self.run_dir / "supervisor"
        self.run_config_dir = self.run_dir / "config"
        with self.phase_scope(category="setup", name="setup_run_dir"):
            deps.setup_run_dir(
                self.run_dir,
                self.agent_dir,
                self.supervisor_dir,
                self.log,
                game_id=str(args.game_id),
            )
        with self.phase_scope(category="setup", name="setup_run_config_dir"):
            self.run_bin_dir, self.run_tools_dir = deps.setup_run_config_dir(self.run_config_dir)
        if bool(getattr(args, "continue_run", False)):
            deps.assert_existing_run_agent_dir_is_safe(self.agent_dir)
        else:
            deps.assert_no_game_files_in_agent_dir(self.agent_dir)
        self.run_super_config = self.run_dir / "super.yaml"
        with self.phase_scope(category="setup", name="render_super_config"):
            rendered_super_config = (deps.PROJECT_ROOT / "super.yaml").read_text()
            validate_run_super_config_text(rendered_super_config)
            self.run_super_config.write_text(rendered_super_config)
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
            with self.phase_scope(category="setup", name="seed_offline_env_cache") as phase:
                seeded = deps.seed_arc_environment_cache(
                    self.arc_env_dir,
                    requested_game_id=str(args.game_id),
                )
                phase["seeded_path"] = str(seeded)
                self.log(
                    "[harness] seeded offline env cache: "
                    f"{seeded}"
                )
        self.state_json = self.arc_state_dir / "state.json"
        self.history_json = self.arc_state_dir / "tool-engine-history.json"
        self.completions_md = self.arc_state_dir / "level_completions.md"
        self.auto_explore_once_marker = self.arc_state_dir / "auto_explore_once.done"
        self.cycle_limit: int | None = 1
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
                    with self.phase_scope(category="scorecard", name="get_scorecard") as phase:
                        self.scorecard_client.get_scorecard(self.active_scorecard_id)
                        phase["scorecard_id"] = self.active_scorecard_id
            else:
                tags = ["arc-agi-harness", "tool-driven", f"game:{args.game_id}"]
                opaque = {
                    "session_name": self.session_name,
                    "game_id": str(args.game_id),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
                with self.phase_scope(category="scorecard", name="open_scorecard") as phase:
                    self.active_scorecard_id = str(
                        self.scorecard_client.open_scorecard(tags=tags, opaque=opaque)
                    )
                    phase["scorecard_id"] = self.active_scorecard_id
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
        self.prompt_image_dir = self.run_dir / "prompt_images"
        self.prompt_image_attached_levels: set[int] = set()
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

    def open_scorecard_now(self) -> str:
        with self.phase_scope(category="scorecard", name="open_scorecard_now"):
            return open_scorecard_now_impl(self)

    def log(self, msg: str) -> None: print(msg, file=self.deps.sys.stderr, flush=True)

    def append_phase_timing(
        self,
        *,
        category: str,
        name: str,
        elapsed_ms: int,
        ok: bool,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        append_phase_timing_impl(
            self,
            category=category,
            name=name,
            elapsed_ms=elapsed_ms,
            ok=ok,
            metadata=metadata,
            error=error,
        )

    def phase_scope(
        self,
        *,
        category: str,
        name: str,
        metadata: dict[str, Any] | None = None,
    ):
        return phase_scope_impl(self, category=category, name=name, metadata=metadata)

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
        with self.phase_scope(category="state", name="monitor_snapshot"):
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
        return run_arc_repl_impl(self, payload)

    def sync_active_conversation_id_from_session(self) -> None: sync_active_conversation_id_from_session_impl(self)

    def certify_or_block_wrapup_transition(self) -> None:
        with self.phase_scope(category="wrapup", name="certify_or_block_transition"):
            certify_or_block_wrapup_transition_impl(self)

    def repair_stale_wrapup_mode(self) -> str | None:
        return repair_stale_wrapup_mode_impl(self)

    def force_recover_mode(
        self,
        *,
        reason: str,
        frontier_level: int | None,
        levels_completed: int | None,
    ) -> None:
        return force_recover_mode_impl(
            self,
            reason=reason,
            frontier_level=frontier_level,
            levels_completed=levels_completed,
        )

    def session_frontmatter(self) -> dict[str, str]: return session_frontmatter_impl(self)

    def discover_workspace_conversation_id(self) -> str | None: return discover_workspace_conversation_id_impl(self)

    def recover_session_file_from_workspace(
        self,
        *,
        reason: str,
        force: bool = False,
    ) -> None:
        with self.phase_scope(
            category="sync",
            name="recover_session_file",
            metadata={"reason": reason, "force": force},
        ):
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
        return resume_super_impl(self, prompt, image_paths=image_paths)

    def cleanup_repl_daemons(self) -> None:
        with self.phase_scope(category="cleanup", name="cleanup_repl_daemons"):
            cleanup_repl_daemons_impl(self)

    def close_scorecard_if_needed(self) -> None:
        with self.phase_scope(category="scorecard", name="close_scorecard_if_needed"):
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

    def ensure_level_start_prompt_image(self, *, level: int | None = None) -> Path:
        return ensure_level_start_prompt_image_impl(self, level=level)

    def level_start_prompt_images(self, state: dict | None) -> list[Path]:
        return level_start_prompt_images_impl(self, state)

    def active_agent_dir(self) -> Path:
        """Return the current game-scoped agent directory for super --agent-dir."""
        if self.prompt_game_dir:
            return Path(self.prompt_game_dir)
        return self.agent_dir
