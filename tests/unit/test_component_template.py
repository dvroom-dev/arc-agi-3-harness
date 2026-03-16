from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def _write_hex(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n")


def _copy_model_templates(game_dir: Path) -> None:
    src_dir = Path(__file__).resolve().parents[2] / "templates" / "agent_workspace"
    runtime_src = Path(__file__).resolve().parents[2] / "arc_model_runtime"
    game_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "model.py",
        "components.py",
        "model_lib.py",
        "play_lib.py",
        "play.py",
        "artifact_helpers.py",
        "inspect_sequence.py",
        "inspect_components.py",
        "inspect_grid_slice.py",
        "inspect_grid_values.py",
    ):
        shutil.copy2(src_dir / name, game_dir / name)
    runtime_dst = game_dir.parent / "config" / "tools" / "arc_model_runtime"
    runtime_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(runtime_src, runtime_dst)


def _run_helper(game_dir: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["ARC_CONFIG_DIR"] = str((game_dir.parent / "config").resolve())
    return subprocess.run(
        [sys.executable, str(game_dir / "inspect_components.py"), *args],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_component_coverage_helper_reports_uncovered_pixels(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0123", "4567"])

    proc = _run_helper(game_dir, ["--coverage", "--level", "1"])
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "fail"
    assert payload["observed_shapes"] == ["2x4"]
    assert payload["first_failure"]["label"] == "level_1:initial_state"
    assert payload["first_failure"]["shape"] == "2x4"
    assert payload["first_failure"]["uncovered_pixel_count"] == 8
    assert (game_dir / "component_coverage.json").exists()
    assert (game_dir / "component_coverage.md").exists()


def test_component_coverage_does_not_advance_analysis_level_pin_phase(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0000", "0000", "0000", "0000"])
    (game_dir / "components.py").write_text(
        "from dataclasses import dataclass, field\n"
        "from typing import Callable\n"
        "import numpy as np\n"
        "GridCell = tuple[int, int]\n"
        "@dataclass(frozen=True)\n"
        "class ComponentShape:\n"
        "    kind: str\n"
        "    cells: tuple[GridCell, ...]\n"
        "    attrs: dict[str, object] = field(default_factory=dict)\n"
        "ComponentDetector = Callable[[np.ndarray], list[ComponentShape]]\n"
        "COMPONENT_REGISTRY = {}\n"
        "def make_component(kind, *, cells, **attrs):\n"
        "    return ComponentShape(kind=kind, cells=tuple(cells), attrs=dict(attrs))\n"
        "def iter_components(grid):\n"
        "    out = []\n"
        "    for kind, detector in COMPONENT_REGISTRY.items():\n"
        "        out.extend(detector(grid))\n"
        "    return out\n"
        "def find_all_bg(grid):\n"
        "    cells = [(int(r), int(c)) for r, c in np.argwhere(grid == 0)]\n"
        "    return [make_component('bg', cells=cells)] if cells else []\n"
        "COMPONENT_REGISTRY['bg'] = find_all_bg\n"
    )
    (game_dir / ".analysis_level_pin.json").write_text(
        json.dumps({"level": 1, "phase": "pending_theory"}, indent=2)
    )

    proc = _run_helper(game_dir, ["--coverage", "--level", "1"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["observed_shapes"] == ["4x4"]
    pin = json.loads((game_dir / ".analysis_level_pin.json").read_text())
    assert pin["phase"] == "pending_theory"
    assert "coverage_checked_level" not in pin


def test_component_coverage_rejects_static_coordinate_detectors(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0000", "0110", "0110", "0000"])
    (game_dir / "components.py").write_text(
        "from dataclasses import dataclass, field\n"
        "from typing import Callable\n"
        "import numpy as np\n"
        "GridCell = tuple[int, int]\n"
        "@dataclass(frozen=True)\n"
        "class ComponentShape:\n"
        "    kind: str\n"
        "    cells: tuple[GridCell, ...]\n"
        "    attrs: dict[str, object] = field(default_factory=dict)\n"
        "ComponentDetector = Callable[[np.ndarray], list[ComponentShape]]\n"
        "COMPONENT_REGISTRY = {}\n"
        "def make_component(kind, *, cells, **attrs):\n"
        "    return ComponentShape(kind=kind, cells=tuple(cells), attrs=dict(attrs))\n"
        "def find_all_box(grid):\n"
        "    cells = [(r, c) for r in range(4) for c in range(4)]\n"
        "    return [make_component('box', cells=cells)]\n"
        "COMPONENT_REGISTRY['box'] = find_all_box\n"
    )

    proc = _run_helper(game_dir, ["--coverage", "--level", "1"])
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "fail"
    assert payload["detector_issues"]
    assert "static-coordinate" in payload["detector_issues"][0]["message"]


def test_component_coverage_rejects_shape_only_umbrella_detectors(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0000", "0110", "0110", "0000"])
    (game_dir / "components.py").write_text(
        "from dataclasses import dataclass, field\n"
        "from typing import Callable\n"
        "import numpy as np\n"
        "GridCell = tuple[int, int]\n"
        "@dataclass(frozen=True)\n"
        "class ComponentShape:\n"
        "    kind: str\n"
        "    cells: tuple[GridCell, ...]\n"
        "    attrs: dict[str, object] = field(default_factory=dict)\n"
        "ComponentDetector = Callable[[np.ndarray], list[ComponentShape]]\n"
        "COMPONENT_REGISTRY = {}\n"
        "def make_component(kind, *, cells, **attrs):\n"
        "    return ComponentShape(kind=kind, cells=tuple(cells), attrs=dict(attrs))\n"
        "def find_all_box(grid):\n"
        "    rows, cols = grid.shape\n"
        "    cells = [(r, c) for r in range(rows) for c in range(cols)]\n"
        "    return [make_component('box', cells=cells)]\n"
        "COMPONENT_REGISTRY['box'] = find_all_box\n"
    )

    proc = _run_helper(game_dir, ["--coverage", "--level", "1"])
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "fail"
    assert payload["detector_issues"]
    assert "shape-only" in payload["detector_issues"][0]["message"] or "static-coordinate" in payload["detector_issues"][0]["message"]


def test_component_coverage_rejects_bbox_only_component_output(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0000", "0110", "0110", "0000"])
    (game_dir / "components.py").write_text(
        "from dataclasses import dataclass, field\n"
        "from typing import Callable\n"
        "import numpy as np\n"
        "@dataclass(frozen=True)\n"
        "class ComponentBox:\n"
        "    kind: str\n"
        "    bbox: tuple[int, int, int, int]\n"
        "    attrs: dict[str, object] = field(default_factory=dict)\n"
        "ComponentDetector = Callable[[np.ndarray], list[ComponentBox]]\n"
        "COMPONENT_REGISTRY = {}\n"
        "def find_all_zero_region(grid):\n"
        "    rows, cols = np.where(grid == 0)\n"
        "    return [ComponentBox(kind='zero_region', bbox=(int(rows.min()), int(cols.min()), int(rows.max()), int(cols.max())))]\n"
        "COMPONENT_REGISTRY['zero_region'] = find_all_zero_region\n"
    )

    proc = _run_helper(game_dir, ["--coverage", "--level", "1"])
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "fail"
    assert payload["geometry_issues"]
    assert "exact geometry" in payload["geometry_issues"][0]["message"]
    markdown = (game_dir / "component_coverage.md").read_text()
    assert "Coverage validation failed before uncovered-pixel analysis." in markdown
    assert "All seen states for this level are covered by exact component geometry." not in markdown


def test_component_coverage_accepts_mask_geometry(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(game_dir / "level_1" / "initial_state.hex", ["0000", "0110", "0110", "0000"])
    (game_dir / "components.py").write_text(
        "from dataclasses import dataclass, field\n"
        "from typing import Callable\n"
        "import numpy as np\n"
        "@dataclass(frozen=True)\n"
        "class ComponentMask:\n"
        "    kind: str\n"
        "    mask: np.ndarray\n"
        "    attrs: dict[str, object] = field(default_factory=dict)\n"
        "ComponentDetector = Callable[[np.ndarray], list[ComponentMask]]\n"
        "COMPONENT_REGISTRY = {}\n"
        "def find_all_nonzero(grid):\n"
        "    return [ComponentMask(kind='nonzero', mask=(grid != 0))]\n"
        "def find_all_zero(grid):\n"
        "    return [ComponentMask(kind='zero', mask=(grid == 0))]\n"
        "COMPONENT_REGISTRY['nonzero'] = find_all_nonzero\n"
        "COMPONENT_REGISTRY['zero'] = find_all_zero\n"
    )

    proc = _run_helper(game_dir, ["--coverage", "--level", "1"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "pass"
    assert payload["geometry_issues"] == []
