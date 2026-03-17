from __future__ import annotations

from arcengine import GameAction


class ModelHooks:
    """Agent-owned mechanics hooks implemented by model.py."""

    def init_level(self, env: "ModelEnv", level: int) -> None:  # pragma: no cover - hook default
        _ = env, level

    def apply_action(  # pragma: no cover - hook default
        self,
        env: "ModelEnv",
        action: GameAction,
        *,
        data: dict | None = None,
        reasoning: str | None = None,
    ) -> None:
        _ = env, action, data, reasoning

    def is_level_complete(self, env: "ModelEnv") -> bool:  # pragma: no cover - hook default
        _ = env
        return False

    def is_game_over(self, env: "ModelEnv") -> bool:  # pragma: no cover - hook default
        _ = env
        return False
