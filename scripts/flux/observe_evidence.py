from __future__ import annotations

from pathlib import Path

from common import read_json_stdin, summarize_instance_state, write_json_stdout


def main() -> None:
    payload = read_json_stdin()
    instance = payload.get("instance") if isinstance(payload.get("instance"), dict) else {}
    state_dir = Path(str(instance.get("metadata", {}).get("state_dir", "")))
    summary = summarize_instance_state(state_dir) if state_dir.exists() else {"summary": "missing state dir"}
    write_json_stdout({"evidence": [summary]})


if __name__ == "__main__":
    main()
