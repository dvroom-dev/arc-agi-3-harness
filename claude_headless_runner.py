from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any


def _read_text(path: Path | None) -> str | None:
    if path is None:
        return None
    return path.read_text(encoding="utf-8")


def _normalize_tools(values: list[str]) -> list[str]:
    tools: list[str] = []
    for value in values:
        for item in str(value).replace(",", " ").split():
            item = item.strip()
            if item:
                tools.append(item)
    return tools


def build_claude_headless_command(args: argparse.Namespace) -> list[str]:
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--input-format",
        "text",
        "--permission-mode",
        args.permission_mode,
        "--model",
        args.model,
        "--session-id",
        args.session_id,
    ]
    if not args.session_persistence:
        cmd.append("--no-session-persistence")
    if args.allowed_tools:
        cmd.extend(["--allowedTools", " ".join(_normalize_tools(args.allowed_tools))])
    if args.disallowed_tools:
        cmd.extend(["--disallowedTools", " ".join(_normalize_tools(args.disallowed_tools))])
    for add_dir in args.add_dir:
        cmd.extend(["--add-dir", add_dir])
    if args.system_prompt_file:
        cmd.extend(["--system-prompt", _read_text(Path(args.system_prompt_file)) or ""])
    if args.append_system_prompt_file:
        cmd.extend(["--append-system-prompt", _read_text(Path(args.append_system_prompt_file)) or ""])
    if args.effort:
        cmd.extend(["--effort", args.effort])
    if args.max_budget_usd is not None:
        cmd.extend(["--max-budget-usd", str(args.max_budget_usd)])
    if args.dangerously_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    cmd.append(_read_text(Path(args.prompt_file)) or "")
    return cmd


def build_claude_headless_env(args: argparse.Namespace) -> dict[str, str]:
    env = dict(os.environ)
    env["CLAUDE_CODE_ENABLE_TELEMETRY"] = "1"
    if args.otel_exporter_otlp_endpoint:
        env["OTEL_EXPORTER_OTLP_ENDPOINT"] = args.otel_exporter_otlp_endpoint
    if args.otel_exporter_otlp_headers:
        env["OTEL_EXPORTER_OTLP_HEADERS"] = args.otel_exporter_otlp_headers
    if args.otel_service_name:
        env["OTEL_SERVICE_NAME"] = args.otel_service_name
    if args.otel_log_user_prompts:
        env["OTEL_LOG_USER_PROMPTS"] = "1"
    return env


def _extract_message_content(record: dict[str, Any]) -> list[dict[str, Any]]:
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [entry for entry in content if isinstance(entry, dict)]


def summarize_claude_stream(records: list[dict[str, Any]], *, wall_ms: int) -> dict[str, Any]:
    tool_calls = Counter()
    tool_results = Counter()
    tool_duration_ms_total = 0
    usage: dict[str, int] = {}
    session_id: str | None = None
    model: str | None = None
    assistant_messages = 0
    first_tool_index: int | None = None

    for idx, record in enumerate(records):
        if not session_id:
            raw_session = record.get("session_id") or record.get("thread_id")
            if isinstance(raw_session, str) and raw_session.strip():
                session_id = raw_session.strip()
        if not model and isinstance(record.get("model"), str):
            model = str(record["model"])

        if record.get("type") == "usage" and isinstance(record.get("usage"), dict):
            for key, value in record["usage"].items():
                try:
                    usage[str(key)] = int(value)
                except Exception:
                    continue

        content = _extract_message_content(record)
        if record.get("type") == "assistant":
            has_assistant_output = False
            for entry in content:
                entry_type = str(entry.get("type") or "")
                if entry_type == "tool_use":
                    name = str(entry.get("name") or "").strip() or "unknown"
                    tool_calls[name] += 1
                    if first_tool_index is None:
                        first_tool_index = idx
                    has_assistant_output = True
                elif entry_type == "text" and str(entry.get("text") or "").strip():
                    has_assistant_output = True
            if has_assistant_output:
                assistant_messages += 1

        if record.get("type") == "tool_result":
            tool_name = str(
                record.get("tool_name")
                or record.get("name")
                or record.get("tool")
                or "unknown"
            ).strip() or "unknown"
            tool_results[tool_name] += 1
            try:
                tool_duration_ms_total += int(record.get("duration_ms") or 0)
            except Exception:
                pass

    return {
        "session_id": session_id,
        "model": model,
        "wall_ms": int(wall_ms),
        "assistant_messages": assistant_messages,
        "tool_calls_by_name": dict(sorted(tool_calls.items())),
        "tool_results_by_name": dict(sorted(tool_results.items())),
        "tool_duration_ms_total": int(tool_duration_ms_total),
        "usage": usage,
        "first_tool_event_index": first_tool_index,
        "stream_events": len(records),
    }


def run_claude_headless(args: argparse.Namespace) -> Path:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "stdout.ndjson"
    stderr_path = output_dir / "stderr.log"
    summary_path = output_dir / "summary.json"
    metadata_path = output_dir / "metadata.json"

    cmd = build_claude_headless_command(args)
    env = build_claude_headless_env(args)
    started = time.monotonic()
    proc = subprocess.run(
        cmd,
        cwd=str(Path(args.cwd).resolve()),
        env=env,
        text=True,
        capture_output=True,
    )
    wall_ms = int(round((time.monotonic() - started) * 1000))

    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")

    records: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except Exception:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)

    summary = summarize_claude_stream(records, wall_ms=wall_ms)
    summary["return_code"] = proc.returncode
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    metadata = {
        "command": cmd,
        "cwd": str(Path(args.cwd).resolve()),
        "env_overrides": {
            key: env[key]
            for key in [
                "CLAUDE_CODE_ENABLE_TELEMETRY",
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                "OTEL_EXPORTER_OTLP_HEADERS",
                "OTEL_SERVICE_NAME",
                "OTEL_LOG_USER_PROMPTS",
            ]
            if key in env
        },
        "output_files": {
            "stdout_ndjson": str(stdout_path),
            "stderr_log": str(stderr_path),
            "summary_json": str(summary_path),
        },
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    if proc.returncode != 0:
        raise RuntimeError(
            f"Claude headless run failed with exit code {proc.returncode}. "
            f"See {stderr_path} and {stdout_path}."
        )
    return summary_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Claude Code headless with OpenTelemetry enabled and capture raw artifacts.",
    )
    parser.add_argument("--cwd", required=True, help="Working directory for the Claude run.")
    parser.add_argument("--prompt-file", required=True, help="Path to the prompt text file.")
    parser.add_argument("--output-dir", required=True, help="Directory for stdout/stderr/summary artifacts.")
    parser.add_argument("--model", default="opus", help="Claude model or alias.")
    parser.add_argument("--permission-mode", default="dontAsk")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--session-id", default=str(uuid.uuid4()))
    parser.add_argument("--system-prompt-file")
    parser.add_argument("--append-system-prompt-file")
    parser.add_argument("--allowed-tools", action="append", default=[])
    parser.add_argument("--disallowed-tools", action="append", default=[])
    parser.add_argument("--add-dir", action="append", default=[])
    parser.add_argument("--max-budget-usd", type=float)
    parser.add_argument("--otel-exporter-otlp-endpoint")
    parser.add_argument("--otel-exporter-otlp-headers")
    parser.add_argument("--otel-service-name", default="arc-agi-claude-headless")
    parser.add_argument("--otel-log-user-prompts", action="store_true")
    parser.add_argument("--dangerously-skip-permissions", action="store_true")
    parser.add_argument("--session-persistence", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary_path = run_claude_headless(args)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
