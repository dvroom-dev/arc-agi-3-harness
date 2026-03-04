"""Reusable helpers for model.py internals.

This module is the single source of truth for model mechanics and level data.
Keep model.py thin and move almost all game-specific logic here.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import numpy as np

@dataclass
class LevelConfig:
    level_num: int
    name: str
    turn_budget: int
    player_start: tuple[int, int]
    cross_center: Optional[tuple[int, int]]
    exit_box_topleft: tuple[int, int]
    exit_box_size: tuple[int, int]
    hud_symbol: list[list[int]]
    exit_symbol: list[list[int]]
    rotations_needed: int
    initial_grid_file: str
    yellow_refill_positions: list[tuple[int, int]] = field(default_factory=list)
    rainbow_box_center: Optional[tuple[int, int]] = None
    hud_symbol_color: int = 9
    exit_symbol_color: int = 9
    has_shape_trigger: bool = False
    shape_trigger_center: Optional[tuple[int, int]] = None
    gate_box_topleft: Optional[tuple[int, int]] = None
    gate_box_size: Optional[tuple[int, int]] = None
    gate_symbol: Optional[list[list[int]]] = None
    gate_symbol_color: Optional[int] = None
LEVEL_REGISTRY: dict[int, LevelConfig] = {1: LevelConfig(level_num=1, name='level_1', turn_budget=42, player_start=(45, 39), cross_center=(32, 21), exit_box_topleft=(8, 30), exit_box_size=(9, 11), hud_symbol=[[1, 1, 1], [1, 0, 0], [1, 0, 1]], exit_symbol=[[1, 1, 1], [0, 0, 1], [1, 0, 1]], rotations_needed=1, initial_grid_file='level_1_initial.hex'), 2: LevelConfig(level_num=2, name='level_2', turn_budget=42, player_start=(40, 29), cross_center=(47, 51), exit_box_topleft=(38, 12), exit_box_size=(9, 11), hud_symbol=[[1, 1, 1], [0, 0, 1], [1, 0, 1]], exit_symbol=[[1, 1, 1], [1, 0, 0], [1, 0, 1]], rotations_needed=3, initial_grid_file='level_2_initial.hex', yellow_refill_positions=[(16, 15), (51, 30)]), 3: LevelConfig(level_num=3, name='level_3', turn_budget=42, player_start=(45, 9), cross_center=(12, 51), exit_box_topleft=(49, 53), exit_box_size=(7, 7), hud_symbol=[[1, 1, 1], [0, 0, 1], [1, 0, 1]], exit_symbol=[[1, 1, 1], [1, 0, 0], [1, 0, 1]], rotations_needed=3, initial_grid_file='level_3_initial.hex', yellow_refill_positions=[(6, 35), (31, 20), (36, 50)], rainbow_box_center=(47, 31), hud_symbol_color=12, exit_symbol_color=9), 4: LevelConfig(level_num=4, name='level_4', turn_budget=42, player_start=(5, 54), cross_center=(32, 26), exit_box_topleft=(3, 7), exit_box_size=(9, 9), hud_symbol=[[0, 1, 0], [1, 1, 0], [0, 1, 1]], exit_symbol=[[1, 1, 1], [0, 0, 1], [1, 0, 1]], rotations_needed=0, initial_grid_file='level_4_initial.hex', yellow_refill_positions=[(21, 25), (41, 35), (46, 15), (51, 55)], rainbow_box_center=(32, 36), hud_symbol_color=14, exit_symbol_color=9, has_shape_trigger=True), 5: LevelConfig(level_num=5, name='level_5', turn_budget=42, player_start=(5, 9), cross_center=(32, 51), exit_box_topleft=(49, 30), exit_box_size=(9, 9), hud_symbol=[[1, 0, 1], [1, 1, 0], [0, 1, 1]], exit_symbol=[[1, 1, 1], [0, 0, 1], [1, 0, 1]], rotations_needed=0, initial_grid_file='level_5_initial.hex', yellow_refill_positions=[(11, 15), (21, 45), (41, 25), (51, 45)], rainbow_box_center=(32, 26), hud_symbol_color=11, exit_symbol_color=9, has_shape_trigger=True)}

def get_level_config(level: int) -> LevelConfig | None:
    return LEVEL_REGISTRY.get(int(level))
FEATURE_ANCHORS_BY_LEVEL: dict[int, dict[str, tuple]] = {1: {'player_start': (45, 39), 'cross_center': (32, 21), 'exit_box': (8, 30, 16, 40), 'exit_corridor': (17, 34, 24, 38)}, 2: {'player_start': (40, 29), 'cross_center': (47, 51), 'exit_box': (38, 12, 46, 22), 'yellow_refill_1': (16, 15), 'yellow_refill_2': (51, 30)}, 3: {'player_start': (45, 9), 'cross_center': (12, 51), 'exit_box': (49, 53, 55, 59), 'rainbow_box_center': (47, 31), 'yellow_refill_1': (6, 35), 'yellow_refill_2': (31, 20), 'yellow_refill_3': (36, 50)}, 4: {'player_start': (5, 54), 'shape_trigger_center': (32, 26), 'exit_box': (3, 7, 11, 15), 'rainbow_box_center': (32, 36), 'yellow_refill_1': (21, 25), 'yellow_refill_2': (41, 35), 'yellow_refill_3': (46, 15), 'yellow_refill_4': (51, 55)}, 5: {'player_start': (5, 9), 'shape_trigger_center': (32, 51), 'exit_box': (49, 30, 57, 38), 'rainbow_box_center': (32, 26), 'yellow_refill_1': (11, 15), 'yellow_refill_2': (21, 45), 'yellow_refill_3': (41, 25), 'yellow_refill_4': (51, 45)}}

def get_anchor(level: int, name: str, default=None):
    return FEATURE_ANCHORS_BY_LEVEL.get(int(level), {}).get(str(name), default)

def get_level_anchors(level: int) -> dict:
    return dict(FEATURE_ANCHORS_BY_LEVEL.get(int(level), {}))
GRID_SIZE = 64
PLAYER_SIZE = 5
STEP_SIZE = 5
ACTION_DELTAS = {1: (-STEP_SIZE, 0), 2: (STEP_SIZE, 0), 3: (0, -STEP_SIZE), 4: (0, STEP_SIZE)}
PLAYER_COLOR_TOP = 12
PLAYER_COLOR_BOTTOM = 9
WALKABLE_COLOR = 3
WALL_COLOR = 4
BLACK_COLOR = 5
WHITE_COLOR = 0
HUD_ROW_START = 53
HUD_ROW_END = 62
HUD_COL_START = 1
HUD_COL_END = 10
HUD_BORDER_COLOR_DEFAULT = BLACK_COLOR
HUD_BORDER_COLOR_MATCH = WHITE_COLOR
HUD_SYMBOL_COLOR = 9
HUD_BG_COLOR = BLACK_COLOR
RAINBOW_COLOR_CYCLE = [12, 9, 14, 8]
BAR_ROWS = (61, 62)
BAR_COL_START = 13
BAR_COL_END = 54
BAR_COLOR = 11
BAR_EMPTY_COLOR = WALKABLE_COLOR
LIFE_ROWS = (61, 62)
LIFE_COL_START = 56
LIFE_COLOR = 8
LIFE_SEPARATOR_COLOR = BLACK_COLOR
CROSS_COLOR_CENTER = WHITE_COLOR
CROSS_COLOR_ARM = 1
REFILL_COLOR = 11
REFILL_CENTER = WALKABLE_COLOR
EXIT_BORDER_INACTIVE = WALKABLE_COLOR
EXIT_BORDER_ACTIVE = WHITE_COLOR
EXIT_INTERIOR_BG = BLACK_COLOR
EXIT_SYMBOL_COLOR = 9

def ensure_np_grid(grid):
    if isinstance(grid, np.ndarray):
        return np.array(grid, dtype=np.int8, copy=True)
    if isinstance(grid, dict):
        rows = grid.get('grid_hex_rows')
        if isinstance(rows, list):
            grid = rows
    if isinstance(grid, list):
        if grid and all((isinstance(row, str) for row in grid)):
            return np.array([[int(ch, 16) for ch in row] for row in grid], dtype=np.int8)
        return np.array(grid, dtype=np.int8)
    raise RuntimeError(f'unsupported grid type: {type(grid)}')

def grid_to_hex_rows(grid):
    arr = ensure_np_grid(grid)
    return [''.join((f'{int(v):X}' for v in row)) for row in arr]

def find_color_positions(grid, color):
    arr = ensure_np_grid(grid)
    pts = np.argwhere(arr == int(color))
    return [(int(r), int(c)) for r, c in pts]

def rotate_symbol_90cw(symbol: list[list[int]]) -> list[list[int]]:
    n = len(symbol)
    return [[symbol[n - 1 - j][i] for j in range(n)] for i in range(n)]

def symbols_match(a: list[list[int]], b: list[list[int]]) -> bool:
    return a == b

def rotations_to_match(current: list[list[int]], target: list[list[int]]) -> int:
    s = [r[:] for r in current]
    for i in range(4):
        if s == target:
            return i
        s = rotate_symbol_90cw(s)
    return -1

def render_player(grid: np.ndarray, pos: tuple[int, int]) -> None:
    r, c = pos
    grid[r:r + 2, c:c + PLAYER_SIZE] = PLAYER_COLOR_TOP
    grid[r + 2:r + PLAYER_SIZE, c:c + PLAYER_SIZE] = PLAYER_COLOR_BOTTOM

def clear_player(grid: np.ndarray, pos: tuple[int, int]) -> None:
    r, c = pos
    grid[r:r + PLAYER_SIZE, c:c + PLAYER_SIZE] = WALKABLE_COLOR

def render_hud_symbol(grid: np.ndarray, symbol: list[list[int]], matched: bool, symbol_color: int=HUD_SYMBOL_COLOR) -> None:
    border_color = HUD_BORDER_COLOR_MATCH if matched else HUD_BORDER_COLOR_DEFAULT
    for r in range(HUD_ROW_START, HUD_ROW_END + 1):
        for c in range(HUD_COL_START, HUD_COL_END + 1):
            grid[r][c] = border_color
    for r in range(HUD_ROW_START + 1, HUD_ROW_END):
        for c in range(HUD_COL_START + 1, HUD_COL_END):
            grid[r][c] = HUD_BG_COLOR
    for sr in range(3):
        for sc in range(3):
            if symbol[sr][sc]:
                gr = HUD_ROW_START + 2 + sr * 2
                gc = HUD_COL_START + 2 + sc * 2
                grid[gr][gc] = symbol_color
                grid[gr][gc + 1] = symbol_color
                grid[gr + 1][gc] = symbol_color
                grid[gr + 1][gc + 1] = symbol_color

def render_exit_box_border(grid: np.ndarray, cfg: LevelConfig, active: bool) -> None:
    color = EXIT_BORDER_ACTIVE if active else EXIT_BORDER_INACTIVE
    br, bc = cfg.exit_box_topleft
    bh, bw = cfg.exit_box_size
    for r in range(br, br + bh):
        for c in range(bc, bc + bw):
            if grid[r][c] == EXIT_BORDER_INACTIVE or grid[r][c] == EXIT_BORDER_ACTIVE:
                grid[r][c] = color

def render_cross(grid: np.ndarray, center: tuple[int, int]) -> None:
    cr, cc = center
    grid[cr - 1][cc] = CROSS_COLOR_CENTER
    grid[cr][cc - 1] = CROSS_COLOR_ARM
    grid[cr][cc] = CROSS_COLOR_CENTER
    grid[cr][cc + 1] = CROSS_COLOR_CENTER
    grid[cr + 1][cc] = CROSS_COLOR_ARM

def clear_cross(grid: np.ndarray, center: tuple[int, int]) -> None:
    cr, cc = center
    grid[cr - 1][cc] = WALKABLE_COLOR
    grid[cr][cc - 1] = WALKABLE_COLOR
    grid[cr][cc] = WALKABLE_COLOR
    grid[cr][cc + 1] = WALKABLE_COLOR
    grid[cr + 1][cc] = WALKABLE_COLOR
SHAPE_TRIGGER_OFFSETS = [(-1, -1), (0, 0), (0, 1), (1, 0)]
SHAPE_TRIGGER_CYCLE = [[[1, 1, 0], [0, 1, 1], [1, 0, 1]], [[0, 1, 0], [0, 1, 0], [1, 1, 1]], [[1, 0, 1], [1, 0, 1], [1, 1, 1]], [[0, 1, 1], [1, 0, 1], [0, 1, 0]], [[0, 1, 0], [1, 1, 0], [0, 1, 1]], [[1, 1, 1], [0, 0, 1], [1, 0, 1]]]

def _apply_shape_trigger_cycle(current_symbol: list[list[int]]) -> list[list[int]]:
    """Advance HUD symbol one step in the shape trigger cycle.

    The cycle is rotation-equivariant: if the current symbol is a rotated
    version of a cycle entry, the output is the NEXT cycle entry with the
    same rotation applied.

    Returns the new symbol, or current_symbol unchanged if it doesn't match
    any (rotated) cycle entry.
    """
    for rot_count in range(4):

        def _rotate_n(sym, n):
            s = [r[:] for r in sym]
            for _ in range(n):
                s = rotate_symbol_90cw(s)
            return s
        for idx, base_shape in enumerate(SHAPE_TRIGGER_CYCLE):
            rotated = _rotate_n(base_shape, rot_count)
            if rotated == current_symbol:
                next_idx = (idx + 1) % len(SHAPE_TRIGGER_CYCLE)
                return _rotate_n(SHAPE_TRIGGER_CYCLE[next_idx], rot_count)
    return [r[:] for r in current_symbol]

def render_shape_trigger(grid: np.ndarray, center: tuple[int, int]) -> None:
    cr, cc = center
    for dr, dc in SHAPE_TRIGGER_OFFSETS:
        grid[cr + dr][cc + dc] = WHITE_COLOR

def clear_shape_trigger(grid: np.ndarray, center: tuple[int, int]) -> None:
    cr, cc = center
    for dr, dc in SHAPE_TRIGGER_OFFSETS:
        grid[cr + dr][cc + dc] = WALKABLE_COLOR

def render_turn_counter(grid: np.ndarray, turns_remaining: int, total_turns: int) -> None:
    for r in BAR_ROWS:
        for i in range(total_turns):
            c = BAR_COL_START + i
            if c > BAR_COL_END:
                break
            grid[r][c] = BAR_COLOR if i < turns_remaining else BAR_EMPTY_COLOR

def render_yellow_refill(grid: np.ndarray, pos: tuple[int, int]) -> None:
    r, c = pos
    for dr in range(3):
        for dc in range(3):
            if dr == 1 and dc == 1:
                grid[r + dr][c + dc] = REFILL_CENTER
            else:
                grid[r + dr][c + dc] = REFILL_COLOR

def clear_yellow_refill(grid: np.ndarray, pos: tuple[int, int]) -> None:
    r, c = pos
    for dr in range(3):
        for dc in range(3):
            grid[r + dr][c + dc] = WALKABLE_COLOR
RAINBOW_PATTERN = [[9, 14, 14], [9, 0, 8], [12, 12, 8]]

def render_rainbow_box(grid: np.ndarray, center: tuple[int, int]) -> None:
    cr, cc = center
    for dr in range(-1, 2):
        for dc in range(-1, 2):
            grid[cr + dr][cc + dc] = RAINBOW_PATTERN[dr + 1][dc + 1]

def clear_rainbow_box(grid: np.ndarray, center: tuple[int, int]) -> None:
    cr, cc = center
    for dr in range(-1, 2):
        for dc in range(-1, 2):
            grid[cr + dr][cc + dc] = WALKABLE_COLOR

def render_gate_inner_border(grid: np.ndarray, cfg: LevelConfig) -> None:
    """Open gate inner border: rows just inside top/bottom and cols just inside left/right → 0."""
    if cfg.gate_box_topleft is None or cfg.gate_box_size is None:
        return
    br, bc = cfg.gate_box_topleft
    bh, bw = cfg.gate_box_size
    for c in range(bc + 1, bc + bw - 1):
        grid[br + 1][c] = WHITE_COLOR
        grid[br + bh - 2][c] = WHITE_COLOR
    for r in range(br + 2, br + bh - 2):
        grid[r][bc + 1] = WHITE_COLOR
        grid[r][bc + bw - 2] = WHITE_COLOR

def clear_gate_interior(grid: np.ndarray, cfg: LevelConfig) -> None:
    """After player enters gate, make entire interior walkable (color 3)."""
    if cfg.gate_box_topleft is None or cfg.gate_box_size is None:
        return
    br, bc = cfg.gate_box_topleft
    bh, bw = cfg.gate_box_size
    for r in range(br + 1, br + bh - 1):
        for c in range(bc + 1, bc + bw - 1):
            grid[r][c] = WALKABLE_COLOR

def player_overlaps_gate_box(pos: tuple[int, int], cfg: LevelConfig) -> bool:
    """Check if player is fully contained within the gate box (same as exit logic)."""
    if cfg.gate_box_topleft is None or cfg.gate_box_size is None:
        return False
    pr, pc = pos
    br, bc = cfg.gate_box_topleft
    bh, bw = cfg.gate_box_size
    return pr >= br and pr + PLAYER_SIZE <= br + bh and (pc >= bc) and (pc + PLAYER_SIZE <= bc + bw)

def _check_gate_match(env, cfg: LevelConfig) -> bool:
    """Check if HUD matches gate symbol + color."""
    if cfg.gate_symbol is None:
        return False
    shape_match = symbols_match(env.hud_symbol, cfg.gate_symbol)
    if not shape_match:
        return False
    if cfg.gate_symbol_color is not None:
        return getattr(env, 'hud_color', cfg.hud_symbol_color) == cfg.gate_symbol_color
    return True
RAINBOW_COLORS = set(RAINBOW_COLOR_CYCLE) | {14}

def can_player_move(grid: np.ndarray, pos: tuple[int, int], action_id: int, exit_active: bool=False, gate_matched: bool=False) -> tuple[int, int] | None:
    dr, dc = ACTION_DELTAS[action_id]
    nr, nc = (pos[0] + dr, pos[1] + dc)
    if nr < 0 or nc < 0 or nr + PLAYER_SIZE > GRID_SIZE or (nc + PLAYER_SIZE > GRID_SIZE):
        return None
    for r in range(nr, nr + PLAYER_SIZE):
        for c in range(nc, nc + PLAYER_SIZE):
            v = int(grid[r][c])
            if v == WALKABLE_COLOR:
                continue
            if v == CROSS_COLOR_CENTER or v == CROSS_COLOR_ARM:
                continue
            if exit_active and (v == EXIT_BORDER_ACTIVE or v == EXIT_INTERIOR_BG or v == EXIT_SYMBOL_COLOR):
                continue
            if gate_matched and (v == EXIT_INTERIOR_BG or v == 8):
                continue
            if v == REFILL_COLOR or v == REFILL_CENTER:
                continue
            if v in RAINBOW_COLORS:
                continue
            return None
    return (nr, nc)

def player_overlaps_cross(pos: tuple[int, int], cross_center: tuple[int, int]) -> bool:
    pr, pc = pos
    cr, cc = cross_center
    return pr <= cr - 1 and pr + PLAYER_SIZE > cr + 2 and (pc <= cc - 1) and (pc + PLAYER_SIZE > cc + 2)

def player_overlaps_exit_box(pos: tuple[int, int], cfg: LevelConfig) -> bool:
    pr, pc = pos
    br, bc = cfg.exit_box_topleft
    bh, bw = cfg.exit_box_size
    return pr >= br and pr + PLAYER_SIZE <= br + bh and (pc >= bc) and (pc + PLAYER_SIZE <= bc + bw)

def player_overlaps_refill(pos: tuple[int, int], refill_pos: tuple[int, int]) -> bool:
    pr, pc = pos
    rr, rc = refill_pos
    return pr <= rr and pr + PLAYER_SIZE > rr + 3 and (pc <= rc) and (pc + PLAYER_SIZE > rc + 3)

def player_overlaps_rainbow(pos: tuple[int, int], rainbow_center: tuple[int, int]) -> bool:
    pr, pc = pos
    cr, cc = rainbow_center
    return pr <= cr - 1 and pr + PLAYER_SIZE > cr + 2 and (pc <= cc - 1) and (pc + PLAYER_SIZE > cc + 2)

def cycle_hud_color(current_color: int) -> int:
    try:
        idx = RAINBOW_COLOR_CYCLE.index(current_color)
        return RAINBOW_COLOR_CYCLE[(idx + 1) % len(RAINBOW_COLOR_CYCLE)]
    except ValueError:
        return RAINBOW_COLOR_CYCLE[0]

def shortest_path_actions_known_geometry(walkable_mask: np.ndarray, start: tuple[int, int], goal: tuple[int, int], *, player_size: int=PLAYER_SIZE) -> list[int]:
    start = (int(start[0]), int(start[1]))
    goal = (int(goal[0]), int(goal[1]))
    if start == goal:
        return []
    rows, cols = walkable_mask.shape

    def can_move(pos, action_id):
        dr, dc = ACTION_DELTAS[action_id]
        nr, nc = (pos[0] + dr, pos[1] + dc)
        if nr < 0 or nc < 0 or nr + player_size > rows or (nc + player_size > cols):
            return None
        if not bool(walkable_mask[nr:nr + player_size, nc:nc + player_size].all()):
            return None
        return (nr, nc)
    q = deque([start])
    prev: dict[tuple[int, int], tuple[tuple[int, int], int] | None] = {start: None}
    while q:
        cur = q.popleft()
        for action_id in (1, 2, 3, 4):
            nxt = can_move(cur, action_id)
            if nxt is None or nxt in prev:
                continue
            prev[nxt] = (cur, action_id)
            if nxt == goal:
                q.clear()
                break
            q.append(nxt)
    if goal not in prev:
        return []
    out: list[int] = []
    cur = goal
    while cur != start:
        parent, action_id = prev[cur]
        out.append(action_id)
        cur = parent
    out.reverse()
    return out

def load_initial_grid(level: int) -> np.ndarray:
    cfg = get_level_config(level)
    if cfg is None:
        return np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.int8)
    game_dir = Path(__file__).resolve().parent
    grid_path = game_dir / cfg.initial_grid_file
    if grid_path.exists():
        lines = grid_path.read_text().strip().splitlines()
        return np.array([[int(ch, 16) for ch in row] for row in lines], dtype=np.int8)
    return np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.int8)

def _check_exit_match(env, cfg) -> bool:
    """Check if both shape and color match for exit activation."""
    shape_match = symbols_match(env.hud_symbol, cfg.exit_symbol)
    if not shape_match:
        return False
    if cfg.rainbow_box_center is not None:
        return getattr(env, 'hud_color', cfg.hud_symbol_color) == cfg.exit_symbol_color
    return True

def apply_shared_model_mechanics(env, action, *, data=None, reasoning=None) -> None:
    """Core game mechanics applied on every step."""
    from arcengine import GameAction as GA
    cfg = get_level_config(env.current_level)
    if cfg is None:
        return
    action_id = int(getattr(action, 'value', action))
    if not hasattr(env, 'hud_color'):
        env.hud_color = cfg.hud_symbol_color
    if not hasattr(env, 'rainbow_consumed'):
        env.rainbow_consumed = False
    if not hasattr(env, 'shape_consumed'):
        env.shape_consumed = False
    if not hasattr(env, 'gate_matched'):
        env.gate_matched = False
    if not hasattr(env, 'gate_cleared'):
        env.gate_cleared = False
    new_pos = can_player_move(env.grid, env.player_pos, action_id, exit_active=env.exit_active, gate_matched=env.gate_matched)
    if new_pos is not None and new_pos != env.player_pos:
        clear_player(env.grid, env.player_pos)
        env.player_pos = new_pos
        render_player(env.grid, env.player_pos)
    if cfg.shape_trigger_center is not None:
        if not env.shape_consumed and player_overlaps_cross(env.player_pos, cfg.shape_trigger_center):
            env.shape_consumed = True
            clear_shape_trigger(env.grid, cfg.shape_trigger_center)
            env.hud_symbol = _apply_shape_trigger_cycle(env.hud_symbol)
            env.exit_active = _check_exit_match(env, cfg)
            render_hud_symbol(env.grid, env.hud_symbol, env.exit_active, symbol_color=getattr(env, 'hud_color', HUD_SYMBOL_COLOR))
            if env.exit_active:
                render_exit_box_border(env.grid, cfg, True)
        if env.shape_consumed and (not player_overlaps_cross(env.player_pos, cfg.shape_trigger_center)):
            if not env.exit_active:
                env.shape_consumed = False
                render_shape_trigger(env.grid, cfg.shape_trigger_center)
        if cfg.cross_center is not None:
            if not env.cross_consumed and player_overlaps_cross(env.player_pos, cfg.cross_center):
                env.cross_consumed = True
                clear_cross(env.grid, cfg.cross_center)
                env.hud_symbol = rotate_symbol_90cw(env.hud_symbol)
                env.rotations_done += 1
                env.exit_active = _check_exit_match(env, cfg)
                render_hud_symbol(env.grid, env.hud_symbol, env.exit_active, symbol_color=getattr(env, 'hud_color', HUD_SYMBOL_COLOR))
                if env.exit_active:
                    render_exit_box_border(env.grid, cfg, True)
            if env.cross_consumed and (not player_overlaps_cross(env.player_pos, cfg.cross_center)):
                if not env.exit_active:
                    env.cross_consumed = False
                    render_cross(env.grid, cfg.cross_center)
    elif cfg.has_shape_trigger:
        if not env.cross_consumed and player_overlaps_cross(env.player_pos, cfg.cross_center):
            env.cross_consumed = True
            clear_shape_trigger(env.grid, cfg.cross_center)
            env.hud_symbol = [r[:] for r in cfg.exit_symbol]
            env.exit_active = _check_exit_match(env, cfg)
            render_hud_symbol(env.grid, env.hud_symbol, env.exit_active, symbol_color=getattr(env, 'hud_color', HUD_SYMBOL_COLOR))
            if env.exit_active:
                render_exit_box_border(env.grid, cfg, True)
        if env.cross_consumed and (not player_overlaps_cross(env.player_pos, cfg.cross_center)):
            if not env.exit_active:
                env.cross_consumed = False
                render_shape_trigger(env.grid, cfg.cross_center)
    else:
        if not env.cross_consumed and player_overlaps_cross(env.player_pos, cfg.cross_center):
            env.cross_consumed = True
            clear_cross(env.grid, cfg.cross_center)
            env.hud_symbol = rotate_symbol_90cw(env.hud_symbol)
            env.rotations_done += 1
            env.exit_active = _check_exit_match(env, cfg)
            render_hud_symbol(env.grid, env.hud_symbol, env.exit_active, symbol_color=getattr(env, 'hud_color', HUD_SYMBOL_COLOR))
            if env.exit_active:
                render_exit_box_border(env.grid, cfg, True)
        if env.cross_consumed and (not player_overlaps_cross(env.player_pos, cfg.cross_center)):
            if not env.exit_active:
                env.cross_consumed = False
                render_cross(env.grid, cfg.cross_center)
    if cfg.rainbow_box_center is not None:
        if not env.rainbow_consumed and player_overlaps_rainbow(env.player_pos, cfg.rainbow_box_center):
            env.rainbow_consumed = True
            clear_rainbow_box(env.grid, cfg.rainbow_box_center)
            env.hud_color = cycle_hud_color(env.hud_color)
            env.exit_active = _check_exit_match(env, cfg)
            render_hud_symbol(env.grid, env.hud_symbol, env.exit_active, symbol_color=env.hud_color)
            if env.exit_active:
                render_exit_box_border(env.grid, cfg, True)
        if env.rainbow_consumed and (not player_overlaps_rainbow(env.player_pos, cfg.rainbow_box_center)):
            if not env.exit_active:
                env.rainbow_consumed = False
                render_rainbow_box(env.grid, cfg.rainbow_box_center)
    if cfg.gate_symbol is not None and (not env.gate_cleared):
        gate_now_matched = _check_gate_match(env, cfg)
        if gate_now_matched and (not env.gate_matched):
            env.gate_matched = True
            render_gate_inner_border(env.grid, cfg)
            render_hud_symbol(env.grid, env.hud_symbol, True, symbol_color=getattr(env, 'hud_color', HUD_SYMBOL_COLOR))
        elif not gate_now_matched and env.gate_matched:
            env.gate_matched = False
        if env.gate_matched and player_overlaps_gate_box(env.player_pos, cfg):
            env.gate_cleared = True
            env.gate_matched = False
            clear_gate_interior(env.grid, cfg)
            render_hud_symbol(env.grid, env.hud_symbol, False, symbol_color=getattr(env, 'hud_color', HUD_SYMBOL_COLOR))
    for i, rpos in enumerate(cfg.yellow_refill_positions):
        if not env.refills_consumed[i] and player_overlaps_refill(env.player_pos, rpos):
            env.refills_consumed[i] = True
            clear_yellow_refill(env.grid, rpos)
            env.turns_remaining = cfg.turn_budget
            render_turn_counter(env.grid, env.turns_remaining, cfg.turn_budget)
    env.turns_remaining -= 1
    render_turn_counter(env.grid, env.turns_remaining, cfg.turn_budget)
    if env.exit_active and player_overlaps_exit_box(env.player_pos, cfg):
        env.level_complete = True
    if env.turns_remaining <= 0:
        env.lives -= 1
        if env.lives <= 0:
            env.game_over = True
        else:
            env.turns_remaining = cfg.turn_budget
            render_turn_counter(env.grid, env.turns_remaining, cfg.turn_budget)
