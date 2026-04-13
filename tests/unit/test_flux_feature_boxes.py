from __future__ import annotations

import json
from pathlib import Path

from scripts.flux.feature_boxes import generate_feature_boxes


def _write_hex(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_feature_boxes_skip_whole_board_transitions_and_cluster_local_regions(tmp_path: Path) -> None:
    level_dir = tmp_path / "level_1"
    (level_dir / "sequences").mkdir(parents=True, exist_ok=True)

    rows0 = ["0" * 20 for _ in range(20)]
    rows1 = rows0.copy()
    rows1[5] = rows1[5][:5] + "AAAA" + rows1[5][9:]
    rows1[6] = rows1[6][:5] + "AAAA" + rows1[6][9:]
    rows2 = rows1.copy()
    rows2[5] = rows2[5][:7] + "AAAA" + rows2[5][11:]
    rows2[6] = rows2[6][:7] + "AAAA" + rows2[6][11:]
    rows3 = ["F" * 20 for _ in range(20)]

    _write_hex(level_dir / "initial_state.hex", rows0)
    (level_dir / "initial_state.meta.json").write_text("{}\n", encoding="utf-8")
    _write_hex(level_dir / "sequences" / "seq_0001" / "actions" / "step_0001_action_000001_action1" / "before_state.hex", rows0)
    _write_hex(level_dir / "sequences" / "seq_0001" / "actions" / "step_0001_action_000001_action1" / "after_state.hex", rows1)
    _write_hex(level_dir / "sequences" / "seq_0001" / "actions" / "step_0002_action_000002_action1" / "before_state.hex", rows1)
    _write_hex(level_dir / "sequences" / "seq_0001" / "actions" / "step_0002_action_000002_action1" / "after_state.hex", rows2)
    _write_hex(level_dir / "sequences" / "seq_0001" / "actions" / "step_0003_action_000003_action1" / "before_state.hex", rows2)
    _write_hex(level_dir / "sequences" / "seq_0001" / "actions" / "step_0003_action_000003_action1" / "after_state.hex", rows3)
    for step in (1, 2, 3):
        (level_dir / "sequences" / "seq_0001" / "actions" / f"step_000{step}_action_00000{step}_action1" / "meta.json").write_text("{}\n", encoding="utf-8")
    (level_dir / "sequences" / "seq_0001.json").write_text(
        json.dumps(
            {
                "level": 1,
                "sequence_id": "seq_0001",
                "actions": [
                    {
                        "local_step": 1,
                        "action_name": "ACTION1",
                        "files": {
                            "before_state_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/before_state.hex",
                            "after_state_hex": "sequences/seq_0001/actions/step_0001_action_000001_action1/after_state.hex",
                        },
                    },
                    {
                        "local_step": 2,
                        "action_name": "ACTION1",
                        "files": {
                            "before_state_hex": "sequences/seq_0001/actions/step_0002_action_000002_action1/before_state.hex",
                            "after_state_hex": "sequences/seq_0001/actions/step_0002_action_000002_action1/after_state.hex",
                        },
                    },
                    {
                        "local_step": 3,
                        "action_name": "ACTION1",
                        "files": {
                            "before_state_hex": "sequences/seq_0001/actions/step_0003_action_000003_action1/before_state.hex",
                            "after_state_hex": "sequences/seq_0001/actions/step_0003_action_000003_action1/after_state.hex",
                        },
                    },
                ],
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    payload = generate_feature_boxes(level_dir)
    assert len(payload["boxes"]) == 1
    assert payload["boxes"][0]["bbox"] == [3, 3, 8, 12]


def test_feature_boxes_use_real_level1_artifacts_when_available() -> None:
    runs_root = Path("/home/dvroom/projs/arc-agi-harness/runs")
    candidates = sorted(runs_root.glob("flux-ui-*"), reverse=True)
    level_dir: Path | None = None
    for run in candidates[:8]:
        drafts_root = run / "flux" / "model" / "drafts"
        for draft in sorted(drafts_root.glob("q_*"), reverse=True)[:8]:
            candidate = draft / "game_ls20" / "level_1"
            if candidate.exists() and (candidate / "sequences").exists():
                level_dir = candidate
                break
        if level_dir is not None:
            break
    if level_dir is None:
        return
    payload = generate_feature_boxes(level_dir)
    giant = [
        box
        for box in payload["boxes"]
        if (box["bbox"][2] - box["bbox"][0] + 1) * (box["bbox"][3] - box["bbox"][1] + 1) > int(64 * 64 * 0.8)
    ]
    assert not giant
    assert len(payload["boxes"]) <= 12
