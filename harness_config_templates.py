from __future__ import annotations


def json_cli_wrapper(tool_name: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
printf '{{"ok":true,"tool":"{tool_name}","argv":'
python3 - <<'PY' "$@"
import json
import sys
print(json.dumps(sys.argv[1:]))
PY
printf '}}\\n'
"""


def python_tool_wrapper(py: str, tool_filename: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=\"$(cd \"$(dirname \"${{BASH_SOURCE[0]}}\")\" && pwd)\"
CONFIG_DIR=\"$(cd \"${{SCRIPT_DIR}}/..\" && pwd)\"
exec \"{py}\" \"${{CONFIG_DIR}}/tools/{tool_filename}\" \"$@\"
"""


def arc_action_tool_script() -> str:
    return """#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path
TOOL = Path(__file__).resolve().parent / "arc_repl.py"
def main() -> int:
    parser = argparse.ArgumentParser(description="Run one ARC action probe")
    parser.add_argument("action_name")
    parser.add_argument("--game-id", default="")
    args = parser.parse_args()
    action_name = str(args.action_name or "").strip().upper()
    if not action_name.startswith("ACTION"):
        raise SystemExit("action_name must look like ACTION1..ACTION7")
    payload: dict[str, object] = {
        "action": "exec",
        "script": "from arcengine import GameAction\\n" + f"env.step(GameAction.{action_name})\\n",
    }
    game_id = str(args.game_id or "").strip()
    if game_id:
        payload["game_id"] = game_id
    proc = subprocess.run([sys.executable, str(TOOL)], input=json.dumps(payload), text=True, capture_output=True, cwd=".")
    if proc.stdout:
        sys.stdout.write(proc.stdout if proc.stdout.endswith("\\n") else proc.stdout + "\\n")
    if proc.stderr:
        sys.stderr.write(proc.stderr if proc.stderr.endswith("\\n") else proc.stderr + "\\n")
    return int(proc.returncode or 0)
if __name__ == "__main__":
    raise SystemExit(main())
"""
