from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "update_openai_models.py"
SPEC = importlib.util.spec_from_file_location("update_openai_models", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_catalog_entries_from_html_extracts_models_and_deprecation() -> None:
    html = """
    <a href="/api/docs/models/gpt-5.4" class="x">
      <div class="font-semibold">GPT-5.4</div>
      <div class="text-sm text-secondary">Best intelligence at scale.</div>
    </a>
    <a href="/api/docs/models/dall-e-3" class="x">
      <div class="font-semibold">DALL·E 3</div>
      <div class="rounded-full">Deprecated</div>
      <div class="text-sm text-secondary">Previous generation image model.</div>
    </a>
    """
    entries = MODULE.catalog_entries_from_html(html)
    assert entries == [
        {
            "model_id": "dall-e-3",
            "display_name": "DALL·E 3",
            "deprecated": True,
            "page_url": "https://developers.openai.com/api/docs/models/dall-e-3",
        },
        {
            "model_id": "gpt-5.4",
            "display_name": "GPT-5.4",
            "deprecated": False,
            "page_url": "https://developers.openai.com/api/docs/models/gpt-5.4",
        },
    ]


def test_snapshot_ids_from_html_extracts_aliases_and_snapshots() -> None:
    html = """
    <div>Snapshots</div>
    <div class="flex flex-1 flex-col gap-4">
      <div>
        Below is a list of all available snapshots and aliases.
      </div>
      <div class="text-sm font-semibold">gpt-4o-mini-transcribe</div>
      <div>gpt-4o-mini-transcribe-2025-12-15</div>
      <div>gpt-4o-mini-transcribe-2025-03-20</div>
      <div>ignore-this-token</div>
    </div>
    <div class="h-px w-full bg-primary-soft"></div>
    """
    names = MODULE.snapshot_ids_from_html("gpt-4o-mini-transcribe", html)
    assert names == [
        "gpt-4o-mini-transcribe",
        "gpt-4o-mini-transcribe-2025-03-20",
        "gpt-4o-mini-transcribe-2025-12-15",
    ]


def test_snapshot_ids_from_html_uses_family_prefix_for_latest_aliases() -> None:
    html = """
    <div>Snapshots</div>
    <div>
      <div class="text-sm font-semibold">omni-moderation-latest</div>
      <div>omni-moderation-2025-09-10</div>
    </div>
    <div class="h-px w-full bg-primary-soft"></div>
    """
    names = MODULE.snapshot_ids_from_html("omni-moderation-latest", html)
    assert names == [
        "omni-moderation-2025-09-10",
        "omni-moderation-latest",
    ]
