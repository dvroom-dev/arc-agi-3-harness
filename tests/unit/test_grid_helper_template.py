from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.unit.test_model_template import _copy_model_templates, _write_hex


def test_inspect_grid_slice_reports_requested_rows_and_cols(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(
        game_dir / "level_current" / "current_state.hex",
        [
            "0123456789",
            "ABCDEF0123",
            "456789ABCD",
        ],
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(game_dir / "inspect_grid_slice.py"),
            "--file",
            "level_current/current_state.hex",
            "--rows",
            "1:2",
            "--cols",
            "2:5",
        ],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "row 1 cols 2-5: CDEF" in proc.stdout
    assert "row 2 cols 2-5: 6789" in proc.stdout


def test_inspect_grid_values_reports_counts_and_bbox(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(
        game_dir / "level_current" / "current_state.hex",
        [
            "00CC0",
            "00990",
            "00990",
            "00000",
        ],
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(game_dir / "inspect_grid_values.py"),
            "--file",
            "level_current/current_state.hex",
            "--value",
            "C",
            "--value",
            "9",
            "--json",
        ],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["shape"] == [4, 5]
    by_value = {item["value"]: item for item in payload["values"]}
    assert by_value["C"]["count"] == 2
    assert by_value["C"]["bbox"] == [0, 2, 0, 3]
    assert by_value["9"]["count"] == 4
    assert by_value["9"]["bbox"] == [1, 2, 2, 3]


def test_inspect_grid_slice_accepts_full_span_end_equal_to_size(tmp_path: Path) -> None:
    game_dir = tmp_path / "game_ls20"
    _copy_model_templates(game_dir)
    _write_hex(
        game_dir / "level_current" / "current_state.hex",
        [
            "0123",
            "4567",
            "89AB",
        ],
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(game_dir / "inspect_grid_slice.py"),
            "--file",
            "level_current/current_state.hex",
            "--rows",
            "0:3",
            "--cols",
            "0:4",
            "--json",
        ],
        cwd=game_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["row_range"] == [0, 2]
    assert payload["col_range"] == [0, 3]
    assert [row["slice"] for row in payload["rows"]] == ["0123", "4567", "89AB"]
