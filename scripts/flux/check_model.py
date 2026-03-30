from __future__ import annotations

import json

from common import read_json_stdin, write_json_stdout


def main() -> None:
    payload = read_json_stdin()
    model_output = payload.get("modelOutput") if isinstance(payload.get("modelOutput"), dict) else {}
    decision = str(model_output.get("decision", "")).strip()
    accepted = decision in {"updated_model", "no_material_change"}
    message = str(model_output.get("summary", "")).strip() or "model output missing summary"
    write_json_stdout({"accepted": accepted, "message": message, "model_output": model_output})


if __name__ == "__main__":
    main()
