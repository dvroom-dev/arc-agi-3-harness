from __future__ import annotations

import io
import json
import sys

import arc_repl


def test_arc_repl_main_missing_action(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["arc_repl"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    rc = arc_repl.main()
    assert rc == 1
    payload = json.loads(out.getvalue())
    assert payload["ok"] is False
    assert payload["error"]["type"] == "missing_action"


def test_arc_repl_main_exec_requires_script(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["arc_repl"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"action": "exec"})))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    rc = arc_repl.main()
    assert rc == 1
    payload = json.loads(out.getvalue())
    assert payload["error"]["type"] == "invalid_exec_args"
