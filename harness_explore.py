from __future__ import annotations

import numpy as np


def run_input_exploration_from_reset(rt) -> str:
    """Auto-probe every available input from a reset baseline."""
    rt.run_arc_repl({"action": "reset_level", "game_id": rt.args.game_id})
    status_result, status_stdout, status_rc = rt.run_arc_repl(
        {"action": "status", "game_id": rt.args.game_id}
    )
    if status_rc != 0 or not status_result:
        detail = status_stdout.strip() if status_stdout.strip() else "status unavailable"
        return (
            "## Input Exploration Results (auto)\n\n"
            "Auto exploration failed before probes.\n\n"
            f"Detail: {detail}\n"
        )

    available = status_result.get("available_actions", [])
    action_ids: list[int] = []
    if isinstance(available, list):
        for action in available:
            try:
                action_ids.append(int(action))
            except Exception:
                continue
    action_ids = sorted(set(a for a in action_ids if a != 0))

    base_pixels = rt.load_current_pixels()
    motion_palette: set[int] = set()
    diff_sections: list[str] = []
    no_effect: list[str] = []

    for action_id in action_ids:
        if action_id == 6 and base_pixels is not None:
            targets = rt.deps.find_click_targets(base_pixels)
            for x, y, color_id, size in targets:
                color_name = rt.deps.COLOR_NAMES.get(color_id, f"color-{color_id}")
                label = (
                    f"ACTION6 click ({x},{y}) on {color_name} "
                    f"(id={color_id:X}, size={size})"
                )
                script = f"env.step(6, data={{'x': {x}, 'y': {y}}})"
                before_pixels = rt.load_current_pixels()
                before_status, _, before_status_rc = rt.run_arc_repl(
                    {"action": "status", "game_id": rt.args.game_id}
                )
                _, stdout, rc = rt.run_arc_repl(
                    {"action": "exec", "game_id": rt.args.game_id, "script": script}
                )
                after_status, after_stdout, after_status_rc = rt.run_arc_repl(
                    {"action": "status", "game_id": rt.args.game_id}
                )
                after_pixels = rt.load_current_pixels()
                if rc == 0 and before_pixels is not None and after_pixels is not None:
                    before_level = (
                        int(before_status.get("levels_completed", 0))
                        if isinstance(before_status, dict)
                        else None
                    )
                    after_level = (
                        int(after_status.get("levels_completed", 0))
                        if isinstance(after_status, dict)
                        else None
                    )
                    if (
                        before_status_rc == 0
                        and after_status_rc == 0
                        and before_level is not None
                        and after_level is not None
                        and after_level > before_level
                    ):
                        no_effect.append(f"{label} (diff suppressed: level transition)")
                    else:
                        changes = rt.deps.diff_change_records(before_pixels, after_pixels)
                        changed_pixels = len(changes)
                        if changed_pixels > 0:
                            motion_palette.update(rt.deps.collect_palette_from_change_records(changes))
                            diff_text = rt.deps.format_change_records(changes)
                            diff_sections.append(f"### {label}\n```\n{diff_text}\n```")
                        else:
                            no_effect.append(label)
                else:
                    status_detail = (
                        after_stdout.strip()
                        if after_status_rc != 0 and after_stdout.strip()
                        else ""
                    )
                    detail = status_detail or stdout.strip() or "exec failed"
                    no_effect.append(f"{label} (error: {detail})")
                rt.run_arc_repl({"action": "reset_level", "game_id": rt.args.game_id})
            continue

        label = f"ACTION{action_id}"
        script = f"env.step({action_id})"
        before_pixels = rt.load_current_pixels()
        before_status, _, before_status_rc = rt.run_arc_repl(
            {"action": "status", "game_id": rt.args.game_id}
        )
        _, stdout, rc = rt.run_arc_repl(
            {"action": "exec", "game_id": rt.args.game_id, "script": script}
        )
        after_status, after_stdout, after_status_rc = rt.run_arc_repl(
            {"action": "status", "game_id": rt.args.game_id}
        )
        after_pixels = rt.load_current_pixels()
        if rc == 0 and before_pixels is not None and after_pixels is not None:
            before_level = (
                int(before_status.get("levels_completed", 0))
                if isinstance(before_status, dict)
                else None
            )
            after_level = (
                int(after_status.get("levels_completed", 0))
                if isinstance(after_status, dict)
                else None
            )
            if (
                before_status_rc == 0
                and after_status_rc == 0
                and before_level is not None
                and after_level is not None
                and after_level > before_level
            ):
                no_effect.append(f"{label} (diff suppressed: level transition)")
            else:
                changes = rt.deps.diff_change_records(before_pixels, after_pixels)
                changed_pixels = len(changes)
                if changed_pixels > 0:
                    motion_palette.update(rt.deps.collect_palette_from_change_records(changes))
                    diff_text = rt.deps.format_change_records(changes)
                    diff_sections.append(f"### {label}\n```\n{diff_text}\n```")
                else:
                    no_effect.append(label)
        else:
            status_detail = (
                after_stdout.strip()
                if after_status_rc != 0 and after_stdout.strip()
                else ""
            )
            detail = status_detail or stdout.strip() or "exec failed"
            no_effect.append(f"{label} (error: {detail})")
        rt.run_arc_repl({"action": "reset_level", "game_id": rt.args.game_id})

    parts = [
        "## Input Exploration Results (auto)",
        "",
        "Harness auto-tested each available input from reset baseline and reset between attempts.",
        "Interpretation note: these are control-baseline diffs; do not treat them as proof of win-condition mechanics.",
    ]
    if base_pixels is not None:
        values, counts = np.unique(base_pixels, return_counts=True)
        background_color = int(values[int(np.argmax(counts))]) if len(values) else 0
        excluded = set(motion_palette)
        excluded.add(background_color)
        feature_lines = rt.deps.summarize_static_features(
            base_pixels,
            excluded_colors=excluded,
        )
        parts.append("")
        parts.append("### Static feature inventory (reset frame)")
        parts.append(
            "Use this inventory for direct feature-contact probes; avoid treating actor trail colors as objective features."
        )
        parts.append(
            "Excluded colors (background + motion palette): "
            + ", ".join(f"{c:X}" for c in sorted(excluded))
        )
        if feature_lines:
            for line in feature_lines:
                parts.append(f"- {line}")
        else:
            parts.append("- (no static components found after exclusions)")
    if diff_sections:
        parts.append("")
        parts.extend(diff_sections)
    if no_effect:
        parts.append("")
        parts.append("### No effect / failed probes")
        parts.append(", ".join(no_effect))
    return "\n".join(parts)
