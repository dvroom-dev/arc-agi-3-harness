from __future__ import annotations

import json

import pytest

import arc_repl_cli


def test_arc_repl_cli_parse_error_emits_json(capsys) -> None:
    parser = arc_repl_cli.JsonArgumentParser(prog="arc_repl")
    with pytest.raises(SystemExit):
        parser.error("bad args")
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["error"]["type"] == "cli_parse_error"
