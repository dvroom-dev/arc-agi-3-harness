# new_game auto-explore bootstrap (game-agnostic)
#
# Purpose:
# - Probe each available non-reset action from the same baseline.
# - For ACTION6, click each contiguous non-background component centroid.
# - Print ONLY which probes changed state by default (no verbose cell diffs).
#
# Usage (example):
#   arc_repl exec --game-id <id> <<'PY'
#   <paste/edit script>
#   PY

import json
from collections import deque


def _grid(state_obj):
    rows = state_obj["grid_hex_rows"]
    return [[int(ch, 16) for ch in row] for row in rows]


def _connected_components_8(mask):
    h = len(mask)
    w = len(mask[0]) if h else 0
    seen = [[False] * w for _ in range(h)]
    comps = []
    dirs = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    ]
    for r in range(h):
        for c in range(w):
            if not mask[r][c] or seen[r][c]:
                continue
            q = deque([(r, c)])
            seen[r][c] = True
            comp = []
            while q:
                rr, cc = q.popleft()
                comp.append((rr, cc))
                for dr, dc in dirs:
                    nr, nc = rr + dr, cc + dc
                    if nr < 0 or nc < 0 or nr >= h or nc >= w:
                        continue
                    if seen[nr][nc] or not mask[nr][nc]:
                        continue
                    seen[nr][nc] = True
                    q.append((nr, nc))
            comps.append(comp)
    return comps


def _centroid(points):
    n = max(1, len(points))
    ry = int(round(sum(r for r, _ in points) / n))
    cx = int(round(sum(c for _, c in points) / n))
    return cx, ry


def _diff_count(a, b):
    h = len(a)
    w = len(a[0]) if h else 0
    cnt = 0
    for r in range(h):
        for c in range(w):
            if a[r][c] != b[r][c]:
                cnt += 1
    return cnt


base_state = get_state()
base_grid = _grid(base_state)
base_level = int(base_state.get("levels_completed", 0))
available = [int(x) for x in base_state.get("available_actions", [])]

changed = []
no_change = []

for action_id in sorted(set(available)):
    if action_id == 0:
        continue

    if action_id == 6:
        # Probe all contiguous non-background components by centroid click.
        counts = {}
        for row in base_grid:
            for v in row:
                counts[v] = counts.get(v, 0) + 1
        bg = max(counts, key=counts.get) if counts else 0

        seen_centroids = set()
        for color_id in sorted(counts.keys()):
            if color_id == bg:
                continue
            mask = [[(cell == color_id) for cell in row] for row in base_grid]
            for comp in _connected_components_8(mask):
                if not comp:
                    continue
                x, y = _centroid(comp)
                if (x, y) in seen_centroids:
                    continue
                seen_centroids.add((x, y))

                before = _grid(get_state())
                before_level_now = int(get_state().get("levels_completed", 0))
                env.step(6, data={"x": x, "y": y})
                after_state = get_state()
                after = _grid(after_state)
                after_level_now = int(after_state.get("levels_completed", 0))

                if after_level_now > before_level_now:
                    no_change.append(f"ACTION6 click ({x},{y}) color={color_id:X} size={len(comp)} [transition diff suppressed]")
                else:
                    dc = _diff_count(before, after)
                    label = f"ACTION6 click ({x},{y}) color={color_id:X} size={len(comp)}"
                    if dc > 0:
                        changed.append({"probe": label, "changed_pixels": dc})
                    else:
                        no_change.append(label)

                env.step(0)
        continue

    before = _grid(get_state())
    before_level_now = int(get_state().get("levels_completed", 0))
    env.step(action_id)
    after_state = get_state()
    after = _grid(after_state)
    after_level_now = int(after_state.get("levels_completed", 0))

    if after_level_now > before_level_now:
        no_change.append(f"ACTION{action_id} [transition diff suppressed]")
    else:
        dc = _diff_count(before, after)
        if dc > 0:
            changed.append({"probe": f"ACTION{action_id}", "changed_pixels": dc})
        else:
            no_change.append(f"ACTION{action_id}")

    env.step(0)

# Default output: only probes that changed state.
print(json.dumps({
    "summary": {
        "level": base_level + 1,
        "probes_with_state_change": len(changed),
        "probes_without_state_change": len(no_change),
    },
    "changed_probes": changed,
}, indent=2))
