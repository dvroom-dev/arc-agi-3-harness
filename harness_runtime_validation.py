from __future__ import annotations


def validate_run_super_config_text(text: str) -> None:
    legacy_markers = [
        "--wrapup-certified",
        "--wrapup-level",
        "mode_payload.wrapup_certified",
        "mode_payload.wrapup_level",
    ]
    found = [marker for marker in legacy_markers if marker in text]
    if found:
        raise RuntimeError(
            "run-local super.yaml still contains legacy solved-level wrap-up contract markers: "
            + ", ".join(found)
            + ". Wrap-up release must be carried by supervisor transition_payload, not switch_mode mode_payload."
        )
