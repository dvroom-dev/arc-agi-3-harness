from __future__ import annotations

import io
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np

import game_state


def _frame():
    return SimpleNamespace(
        state=SimpleNamespace(value="NOT_FINISHED"),
        levels_completed=0,
        win_levels=7,
        available_actions=[1, 2, 3, 4],
    )


def test_hex_to_rgb() -> None:
    assert game_state._hex_to_rgb("#FFFFFF") == (255, 255, 255)
    assert game_state._hex_to_rgb("000000") == (0, 0, 0)


def test_render_grid_to_terminal_fallback(monkeypatch) -> None:
    monkeypatch.setattr(game_state, "RICH_AVAILABLE", False)
    buf = io.StringIO()
    pixels = np.zeros((2, 2), dtype=np.int8)
    game_state.render_grid_to_terminal(
        pixels,
        _frame(),
        label="L",
        last_action="ACTION1",
        transition_log=["x"],
        error="boom",
        file=buf,
    )
    out = buf.getvalue()
    assert "state=NOT_FINISHED" in out
    assert "ERROR:" in out


def test_render_grid_to_terminal_rich_path(monkeypatch) -> None:
    class FakeStyle:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeText:
        def __init__(self):
            self.parts = []

        def append(self, s, style=None):
            self.parts.append((s, style))

    class FakeConsole:
        def __init__(self, file=None, highlight=False):
            self.file = file

        def print(self, obj):
            if hasattr(obj, "parts"):
                self.file.write("GRID\n")
            else:
                self.file.write(str(obj) + "\n")

    monkeypatch.setattr(game_state, "RICH_AVAILABLE", True)
    monkeypatch.setattr(game_state, "Style", FakeStyle)
    monkeypatch.setattr(game_state, "Text", FakeText)
    monkeypatch.setattr(game_state, "Console", FakeConsole)
    buf = io.StringIO()
    pixels = np.zeros((4, 4), dtype=np.int8)
    game_state.render_grid_to_terminal(pixels, _frame(), file=buf)
    assert "GRID" in buf.getvalue()


def test_render_grid_to_image_without_pillow(monkeypatch, tmp_path: Path) -> None:
    fake_pil = ModuleType("PIL")

    class FakeImageObj:
        def __init__(self):
            self.saved = None

        def save(self, path):
            Path(path).write_bytes(b"png")

    class FakeImageModule:
        @staticmethod
        def new(mode, size):
            return FakeImageObj()

    class FakeDraw:
        def rectangle(self, *args, **kwargs):
            return None

        def line(self, *args, **kwargs):
            return None

    class FakeImageDrawModule:
        @staticmethod
        def Draw(img):
            return FakeDraw()

    fake_pil.Image = FakeImageModule
    fake_pil.ImageDraw = FakeImageDrawModule
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", FakeImageModule)
    monkeypatch.setitem(sys.modules, "PIL.ImageDraw", FakeImageDrawModule)

    out = tmp_path / "grid.png"
    game_state.render_grid_to_image(np.zeros((4, 4), dtype=np.int8), out, scale=2, grid_lines=True)
    assert out.exists()

