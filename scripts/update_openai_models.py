#!/usr/bin/env python3
"""Fetch documented OpenAI model IDs from official docs and write snapshots.

This script is docs-first:
- It scrapes the official OpenAI model catalog page for top-level model IDs.
- It visits each model page to collect documented aliases and snapshots.
- Optionally, it can also query GET /v1/models for account-visible IDs.

Outputs:
- docs/openai-models.json
- docs/openai-models.md
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON_PATH = PROJECT_ROOT / "docs" / "openai-models.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "docs" / "openai-models.md"
CATALOG_URL = "https://developers.openai.com/api/docs/models/all"
LIST_MODELS_API_URL = "https://api.openai.com/v1/models"

CATALOG_CARD_RE = re.compile(
    r'<a href="/api/docs/models/(?P<model_id>[A-Za-z0-9._-]+)"[^>]*>'
    r".*?<div class=\"font-semibold\">(?P<display_name>.*?)</div>"
    r"(?P<body>.*?)</a>",
    re.S,
)
MODEL_TOKEN_RE = re.compile(r"\b[a-z0-9][a-z0-9._-]{2,}\b")


def fetch_text(url: str, *, headers: dict[str, str] | None = None) -> str:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request) as response:
        return response.read().decode("utf-8", "replace")


def strip_tags(raw_html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_display_name(raw_html: str) -> str:
    return strip_tags(raw_html)


def family_prefix_for_model(model_id: str) -> str:
    for suffix in ("-latest", "-stable", "-preview"):
        if model_id.endswith(suffix):
            return model_id[: -len(suffix)]
    return model_id


def looks_like_model_token(token: str) -> bool:
    if token.endswith((".png", ".jpg", ".jpeg", ".css", ".js", ".xml")):
        return False
    if token in {"api", "docs", "models", "snapshots", "aliases", "default"}:
        return False
    if not any(ch.isalpha() for ch in token):
        return False
    if not any(ch.isdigit() for ch in token):
        return False
    return True


def catalog_entries_from_html(catalog_html: str) -> list[dict[str, Any]]:
    entries_by_id: dict[str, dict[str, Any]] = {}
    for match in CATALOG_CARD_RE.finditer(catalog_html):
        model_id = match.group("model_id")
        if model_id == "all":
            continue
        body = match.group("body")
        display_name = normalize_display_name(match.group("display_name"))
        description = normalize_display_name(body)
        deprecated = "Deprecated" in description
        current = entries_by_id.get(model_id)
        candidate = {
            "model_id": model_id,
            "display_name": display_name,
            "deprecated": deprecated,
            "page_url": f"https://developers.openai.com/api/docs/models/{model_id}",
        }
        if current is None:
            entries_by_id[model_id] = candidate
            continue
        current["deprecated"] = bool(current["deprecated"] or deprecated)
        if len(display_name) > len(str(current["display_name"])):
            current["display_name"] = display_name
    return [entries_by_id[key] for key in sorted(entries_by_id)]


def snapshot_ids_from_html(model_id: str, model_html: str) -> list[str]:
    marker = "Snapshots</div>"
    start = model_html.find(marker)
    if start < 0:
        return [model_id]

    end = model_html.find('<div class="h-px w-full bg-primary-soft"></div>', start)
    if end < 0:
        end = len(model_html)
    section = model_html[start:end]
    section_text = strip_tags(section)

    family_prefix = family_prefix_for_model(model_id)
    model_names: set[str] = {model_id}
    for token in MODEL_TOKEN_RE.findall(section_text):
        if not looks_like_model_token(token):
            continue
        if token == model_id:
            model_names.add(token)
            continue
        if token.startswith(model_id + "-"):
            model_names.add(token)
            continue
        if family_prefix and token.startswith(family_prefix + "-"):
            model_names.add(token)
    return sorted(model_names)


def fetch_account_visible_model_ids(api_key: str) -> list[str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = json.loads(fetch_text(LIST_MODELS_API_URL, headers=headers))
    data = payload.get("data", [])
    if not isinstance(data, list):
        raise RuntimeError("GET /v1/models returned unexpected JSON shape")
    model_ids = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", "")).strip()
        if model_id:
            model_ids.append(model_id)
    return sorted(set(model_ids))


def build_snapshot(*, include_api_list: bool) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    catalog_html = fetch_text(CATALOG_URL)
    top_level_models = catalog_entries_from_html(catalog_html)

    all_documented_names: set[str] = set()
    deprecated_top_level_ids = sorted(
        entry["model_id"] for entry in top_level_models if bool(entry["deprecated"])
    )
    for entry in top_level_models:
        model_html = fetch_text(str(entry["page_url"]))
        names = snapshot_ids_from_html(str(entry["model_id"]), model_html)
        entry["documented_names"] = names
        all_documented_names.update(names)

    snapshot: dict[str, Any] = {
        "generated_at_utc": generated_at,
        "source": {
            "catalog_url": CATALOG_URL,
            "catalog_type": "official_openai_docs",
            "notes": (
                "This is a docs-derived catalog of documented model IDs, aliases, and snapshots. "
                "Account-visible availability can differ."
            ),
        },
        "top_level_model_count": len(top_level_models),
        "documented_name_count": len(all_documented_names),
        "top_level_models": top_level_models,
        "documented_names": sorted(all_documented_names),
        "deprecated_top_level_model_ids": deprecated_top_level_ids,
        "regenerate": {
            "docs_only": "python scripts/update_openai_models.py",
            "with_api_list": (
                "OPENAI_API_KEY=... python scripts/update_openai_models.py --include-api-list"
            ),
        },
    }

    if include_api_list:
        api_key = str(os.getenv("OPENAI_API_KEY", "")).strip()
        if not api_key:
            raise RuntimeError("--include-api-list requires OPENAI_API_KEY")
        snapshot["account_visible_model_ids"] = fetch_account_visible_model_ids(api_key)

    return snapshot


def render_markdown(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# OpenAI Models Snapshot")
    lines.append("")
    lines.append("Generated from official OpenAI docs.")
    lines.append("")
    lines.append(f"- Generated at: `{snapshot['generated_at_utc']}`")
    lines.append(f"- Catalog source: `{snapshot['source']['catalog_url']}`")
    lines.append(f"- Top-level model IDs: `{snapshot['top_level_model_count']}`")
    lines.append(f"- Documented names incl. snapshots/aliases: `{snapshot['documented_name_count']}`")
    lines.append("")
    lines.append("## Regenerate")
    lines.append("")
    lines.append("```bash")
    lines.append(str(snapshot["regenerate"]["docs_only"]))
    lines.append(str(snapshot["regenerate"]["with_api_list"]))
    lines.append("```")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- This file is docs-derived. It reflects what OpenAI documents publicly, not necessarily every model your account can access."
    )
    lines.append(
        "- If you need the account-visible list too, rerun with `--include-api-list` and `OPENAI_API_KEY`."
    )
    lines.append("")
    lines.append("## Documented Model Names")
    lines.append("")
    lines.append("```text")
    for model_name in snapshot["documented_names"]:
        lines.append(str(model_name))
    lines.append("```")
    lines.append("")
    lines.append("## Top-level Models")
    lines.append("")
    for entry in snapshot["top_level_models"]:
        suffix = " (deprecated)" if bool(entry["deprecated"]) else ""
        lines.append(f"### {entry['model_id']}{suffix}")
        lines.append("")
        lines.append(f"- Display name: {entry['display_name']}")
        lines.append(f"- Page: {entry['page_url']}")
        lines.append("- Documented names:")
        for name in entry["documented_names"]:
            lines.append(f"  - {name}")
        lines.append("")
    if "account_visible_model_ids" in snapshot:
        lines.append("## Account-visible Model IDs")
        lines.append("")
        lines.append("```text")
        for model_id in snapshot["account_visible_model_ids"]:
            lines.append(str(model_id))
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update OpenAI model snapshots from official docs.")
    parser.add_argument(
        "--json-path",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help=f"Path to write JSON output (default: {DEFAULT_JSON_PATH})",
    )
    parser.add_argument(
        "--md-path",
        type=Path,
        default=DEFAULT_MD_PATH,
        help=f"Path to write Markdown output (default: {DEFAULT_MD_PATH})",
    )
    parser.add_argument(
        "--include-api-list",
        action="store_true",
        help="Also query GET /v1/models using OPENAI_API_KEY and store account-visible IDs.",
    )
    return parser.parse_args(argv)


def write_outputs(snapshot: dict[str, Any], *, json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(snapshot), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        snapshot = build_snapshot(include_api_list=bool(args.include_api_list))
        write_outputs(snapshot, json_path=args.json_path, md_path=args.md_path)
    except urllib.error.URLError as exc:
        print(f"failed to fetch OpenAI docs: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"wrote {args.json_path}")
    print(f"wrote {args.md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
