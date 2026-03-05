#!/usr/bin/env python3
"""Agent-owned model entrypoint.

Keep this file small:
- generic action receiver
- level dispatch (starts with level 1 stub)
- delegates runtime/CLI/state handling to arc_model_runtime
"""

from __future__ import annotations

from pathlib import Path
import sys

from arcengine import GameAction

# Runtime is copied by harness into agent/_runtime/arc_model_runtime.
GAME_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = GAME_DIR.parent / "_runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from arc_model_runtime import ModelHooks, run_model_cli  # noqa: E402

import model_lib  # noqa: E402


class Hooks(ModelHooks):
    def init_level(self, env, level: int) -> None:
        cfg = model_lib.get_level_config(level)
        env.turn_budget = int(getattr(cfg, "turn_budget", 100))
        env.grid = env.initial_grid_for_level(level)

    def apply_action(
        self,
        env,
        action: GameAction,
        *,
        data: dict | None = None,
        reasoning: str | None = None,
    ) -> None:
        # Generic action receiver (all levels).
        env.turn += 1
        env.turn_budget -= 1

        level_handler = getattr(self, f"_apply_level_{int(env.current_level)}", None)
        if callable(level_handler):
            level_handler(env, action, data=data, reasoning=reasoning)

    def _apply_level_1(
        self,
        env,
        action: GameAction,
        *,
        data: dict | None = None,
        reasoning: str | None = None,
    ) -> None:
        """Stub level-1 mechanics entrypoint.

        Fill this using evidence from real game + sequence files.
        """
        _ = env, action, data, reasoning

    def is_level_complete(self, env) -> bool:
        # Delegate completion condition to model_lib for easy iteration.
        checker = getattr(model_lib, "is_level_complete", None)
        if callable(checker):
            return bool(checker(env))
        return False


def main() -> int:
    return run_model_cli(Hooks(), game_dir=GAME_DIR)


if __name__ == "__main__":
    raise SystemExit(main())

