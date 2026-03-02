from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import arc_repl


def test_conversation_id_sanitization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARC_CONVERSATION_ID", "  bad id/with:chars  ")
    cid = arc_repl._conversation_id()
    assert cid == "bad_id_with_chars"


def test_session_key_prefers_arc_repl_session_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARC_CONVERSATION_ID", "conv-raw")
    monkeypatch.setenv("ARC_REPL_SESSION_KEY", "  run key/with:chars  ")
    skey = arc_repl._session_key()
    assert skey == "run_key_with_chars"


def test_session_key_falls_back_to_conversation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARC_REPL_SESSION_KEY", raising=False)
    monkeypatch.setenv("ARC_CONVERSATION_ID", "conv x")
    skey = arc_repl._session_key()
    assert skey == "conv_x"


def test_same_game_lineage() -> None:
    assert arc_repl._same_game_lineage("ls20", "ls20-cb3b57cc")
    assert arc_repl._same_game_lineage("ls20-cb3b57cc", "ls20")
    assert not arc_repl._same_game_lineage("ls20", "ft09")


def test_socket_path_stays_inside_cwd(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd = tmp_path / "agent"
    cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARC_STATE_DIR", str(tmp_path / "state"))
    sock = arc_repl._socket_path(cwd, "conv-1")
    assert str(sock).endswith("/repl-sessions/conv-1/daemon.ready")


def test_ipc_paths_resolve_under_session_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd = tmp_path / "agent"
    cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARC_STATE_DIR", str(tmp_path / "state"))
    req, resp = arc_repl._ipc_paths(cwd, "conv-1")
    assert str(req).endswith("/repl-sessions/conv-1/ipc/requests")
    assert str(resp).endswith("/repl-sessions/conv-1/ipc/responses")


def test_grid_from_hex_rows_and_chunk() -> None:
    grid = arc_repl._grid_from_hex_rows(["0A", "F1"])
    assert grid.shape == (2, 2)
    assert int(grid[0, 1]) == 10
    chunk = arc_repl._chunk_for_bbox(
        grid,
        {"min_row": 0, "max_row": 0, "min_col": 1, "max_col": 1},
        pad=1,
    )
    assert chunk["bbox"] == {"min_row": 0, "max_row": 1, "min_col": 0, "max_col": 1}
    assert chunk["rows_hex"] == ["0A", "F1"]
    assert arc_repl._chunk_for_bbox(grid, None) == {"bbox": None, "rows_hex": []}


def test_coerce_grid_from_multiple_shapes() -> None:
    current = np.array([[1, 2], [3, 4]], dtype=np.int16)
    assert np.array_equal(arc_repl._coerce_grid(None, current), current)
    assert np.array_equal(arc_repl._coerce_grid(["0A", "F1"]), np.array([[0, 10], [15, 1]]))
    assert np.array_equal(
        arc_repl._coerce_grid({"grid_hex_rows": ["01", "23"]}),
        np.array([[0, 1], [2, 3]]),
    )

    frame_like = SimpleNamespace(frame=[np.array([[9, 9], [9, 9]], dtype=np.int16)])
    assert np.array_equal(arc_repl._coerce_grid(frame_like), np.array([[9, 9], [9, 9]]))

    with pytest.raises(RuntimeError):
        arc_repl._coerce_grid("unsupported")


def test_parse_daemon_args() -> None:
    ns = arc_repl._parse_daemon_args(
        ["--daemon", "--cwd", "/tmp", "--conversation-id", "c1", "--game-id", "ls20"]
    )
    assert ns.daemon is True
    assert ns.cwd == "/tmp"
    assert ns.conversation_id == "c1"
    assert ns.game_id == "ls20"


def test_error_and_read_args_validation(monkeypatch) -> None:
    payload = arc_repl._error(
        action="status",
        requested_game_id="ls20",
        message="boom",
        error_type="x",
    )
    assert payload["ok"] is False
    assert payload["schema_version"] == arc_repl.SCHEMA_VERSION

    monkeypatch.setattr(arc_repl.sys, "stdin", type("S", (), {"read": lambda self: "{", "isatty": lambda self: False})())
    parsed = arc_repl._read_args()
    assert "_error" in parsed
