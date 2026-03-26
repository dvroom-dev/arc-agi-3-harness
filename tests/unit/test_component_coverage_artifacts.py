from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


def _load_template_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_component_coverage_writes_active_analysis_surface(tmp_path: Path) -> None:
    workspace = tmp_path / "game_ls20"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "analysis_state.json").write_text(
        json.dumps(
            {
                "schema_version": "arc.analysis_state.v2",
                "analysis_scope": "wrapup",
                "analysis_level": 1,
                "frontier_level": 2,
                "analysis_level_dir": "analysis_level",
                "level_current_dir": "level_current",
            },
            indent=2,
        )
        + "\n"
    )
    analysis_level = workspace / "analysis_level"
    analysis_level.mkdir(parents=True, exist_ok=True)
    (analysis_level / "meta.json").write_text(
        json.dumps({"level": 1, "analysis_level_pinned": True}, indent=2) + "\n"
    )
    (analysis_level / "initial_state.hex").write_text("00\n00\n", encoding="utf-8")
    level_current = workspace / "level_current"
    level_current.mkdir(parents=True, exist_ok=True)
    (level_current / "meta.json").write_text(
        json.dumps({"level": 2, "analysis_level_pinned": False}, indent=2) + "\n"
    )
    (workspace / "components.py").write_text(
        "\n".join(
            [
                "def iter_components(grid):",
                "    rows, cols = grid.shape",
                "    cells = [(r, c) for r in range(rows) for c in range(cols)]",
                "    yield {'kind': 'full', 'cells': cells}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    helpers_path = Path("/home/dvroom/projs/arc-agi-harness/templates/agent_workspace/artifact_helpers.py")
    inspect_path = Path("/home/dvroom/projs/arc-agi-harness/templates/agent_workspace/inspect_components.py")
    _load_template_module("artifact_helpers", helpers_path)
    inspect_components = _load_template_module("inspect_components_under_test", inspect_path)

    payload, code = inspect_components.run_component_coverage(workspace, level=1)

    assert code == 0
    assert payload["status"] == "pass"
    assert payload["level"] == 1
    root_payload = json.loads((workspace / "component_coverage.json").read_text())
    analysis_payload = json.loads((analysis_level / "component_coverage.json").read_text())
    assert root_payload["level"] == 1
    assert analysis_payload["level"] == 1
    assert (workspace / "component_coverage.md").exists()
    assert (analysis_level / "component_coverage.md").exists()
