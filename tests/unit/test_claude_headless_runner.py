from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from claude_headless_runner import (
    build_claude_headless_command,
    build_claude_headless_env,
    summarize_claude_stream,
)


def test_build_claude_headless_command_reads_prompt_and_tools(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Solve the task.\n", encoding="utf-8")
    system_prompt_file = tmp_path / "system.txt"
    system_prompt_file.write_text("System prompt.\n", encoding="utf-8")

    args = Namespace(
        permission_mode="dontAsk",
        model="opus",
        session_id="session-123",
        session_persistence=False,
        allowed_tools=["Bash,Read", "Edit"],
        disallowed_tools=[],
        add_dir=[],
        system_prompt_file=str(system_prompt_file),
        append_system_prompt_file=None,
        effort="medium",
        max_budget_usd=None,
        dangerously_skip_permissions=False,
        prompt_file=str(prompt_file),
    )

    cmd = build_claude_headless_command(args)

    assert cmd[:4] == ["claude", "-p", "--output-format", "stream-json"]
    assert "--no-session-persistence" in cmd
    assert "Solve the task.\n" == cmd[-1]
    assert "Bash Read Edit" in cmd
    assert "System prompt.\n" in cmd


def test_build_claude_headless_env_enables_telemetry() -> None:
    args = Namespace(
        otel_exporter_otlp_endpoint="http://otel.example/v1/traces",
        otel_exporter_otlp_headers="authorization=Bearer test",
        otel_service_name="bench-compare",
        otel_log_user_prompts=True,
    )

    env = build_claude_headless_env(args)

    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://otel.example/v1/traces"
    assert env["OTEL_EXPORTER_OTLP_HEADERS"] == "authorization=Bearer test"
    assert env["OTEL_SERVICE_NAME"] == "bench-compare"
    assert env["OTEL_LOG_USER_PROMPTS"] == "1"


def test_summarize_claude_stream_counts_tools_and_usage() -> None:
    records = [
        {"type": "system", "subtype": "init", "session_id": "sess-1", "model": "claude-opus-4-6"},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Planning"},
                    {"type": "tool_use", "name": "Bash"},
                ]
            },
        },
        {"type": "tool_result", "tool_name": "Bash", "duration_ms": 87},
        {"type": "usage", "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}},
    ]

    summary = summarize_claude_stream(records, wall_ms=1234)

    assert summary["session_id"] == "sess-1"
    assert summary["model"] == "claude-opus-4-6"
    assert summary["wall_ms"] == 1234
    assert summary["assistant_messages"] == 1
    assert summary["tool_calls_by_name"] == {"Bash": 1}
    assert summary["tool_results_by_name"] == {"Bash": 1}
    assert summary["tool_duration_ms_total"] == 87
    assert summary["usage"] == {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
