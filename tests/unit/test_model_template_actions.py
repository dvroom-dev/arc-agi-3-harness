from __future__ import annotations

import sys
from pathlib import Path

from tests.unit.test_model_template import _copy_model_templates


def test_model_lib_action_name_normalizes_common_action_shapes(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    sys.path.insert(0, str(game_dir))
    try:
        import importlib

        model_lib = importlib.import_module("model_lib")

        class ActionLike:
            name = "action1"

        assert model_lib.action_name(ActionLike()) == "ACTION1"
        assert model_lib.action_name("GameAction.ACTION2") == "ACTION2"
        assert model_lib.action_name("action3") == "ACTION3"
    finally:
        sys.path = [entry for entry in sys.path if entry != str(game_dir)]
