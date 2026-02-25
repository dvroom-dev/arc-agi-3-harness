"""Level solver entrypoint shared by simulator and real game.

Run order for solve mode:
1) Dry-run in simulator:
   ./game_<id>/simulate.py exec_file ./game_<id>/play.py
2) Real execution:
   arc_repl exec_file ./game_<id>/play.py

This file should stay thin: dispatch by level and call helpers from play_lib.py.
"""

import json


def _is_simulator(state: dict) -> bool:
    guid = str(state.get("guid", "") or "")
    return guid.startswith("sim-") or guid == "sim-guid"


def _run_actions(actions):
    for i, action in enumerate(actions, 1):
        frame = env.step(action)
        print(
            json.dumps(
                {
                    "step": i,
                    "action": int(action),
                    "state": frame.state.value,
                    "current_level": int(frame.levels_completed) + 1,
                }
            )
        )


def solve_level_default(state: dict):
    """Fallback when no level-specific solver is implemented yet."""
    _ = state
    return []


def solve_level_1(state: dict):
    """Level 1 solver placeholder."""
    planner = globals().get("plan_level_actions")
    if callable(planner):
        return list(planner(state, level=1))
    return []


SOLVERS = {
    1: solve_level_1,
}


def main():
    state = get_state()
    level = int(state.get("current_level", 1))
    mode = "simulate-dry-run" if _is_simulator(state) else "real"
    print(json.dumps({"mode": mode, "level": level, "state": state.get("state")}))

    solver = SOLVERS.get(level, solve_level_default)
    actions = list(solver(state))
    print(json.dumps({"planned_actions": len(actions), "level": level}))
    _run_actions(actions)


main()
