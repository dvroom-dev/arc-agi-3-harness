from __future__ import annotations


def noop_super_cycle_error(
    *,
    stdout: str,
    new_events: list[dict],
    head_before_resume: dict[str, str | int | None] | None,
    head_after_resume: dict[str, str | int | None] | None,
) -> str | None:
    if stdout.strip() or new_events or head_after_resume is None:
        return None
    if (
        head_before_resume is not None
        and str(head_before_resume.get("action_summary") or "").startswith("stop")
        and head_after_resume.get("action_summary") == "supervise:start"
        and head_before_resume.get("provider_thread_id")
        and head_before_resume.get("provider_thread_id") == head_after_resume.get("provider_thread_id")
    ):
        return (
            "super completed an empty recovery cycle after a stop decision: "
            "fresh supervise:start head reused the same provider thread id "
            "without producing assistant output or history events"
        )
    if head_after_resume.get("provider_thread_id"):
        return None

    head_advanced = (
        head_before_resume is not None
        and head_before_resume.get("head_id") != head_after_resume.get("head_id")
    )
    same_doc = (
        head_before_resume is not None
        and head_before_resume.get("doc_hash") == head_after_resume.get("doc_hash")
    )
    resumed_into_fresh_supervise_head = head_after_resume.get("action_summary") == "supervise:start"
    if resumed_into_fresh_supervise_head:
        return None
    if not head_advanced or not same_doc:
        return None

    return (
        "super completed a no-op provider cycle: "
        "empty assistant response, no history events, "
        "no provider thread id, and unchanged transcript content"
    )
