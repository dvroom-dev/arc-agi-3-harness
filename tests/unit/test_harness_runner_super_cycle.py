from harness_runner_super_cycle import noop_super_cycle_error


def test_noop_super_cycle_allows_fresh_supervise_start_head_after_fork() -> None:
    assert (
        noop_super_cycle_error(
            stdout="",
            new_events=[],
            head_before_resume={
                "head_id": "fork_old",
                "doc_hash": "abc",
                "provider_thread_id": None,
            },
            head_after_resume={
                "head_id": "fork_new",
                "parent_id": "fork_old",
                "action_summary": "supervise:start",
                "doc_hash": "abc",
                "provider_thread_id": None,
            },
        )
        is None
    )


def test_noop_super_cycle_allows_fresh_supervise_start_sibling_head() -> None:
    assert (
        noop_super_cycle_error(
            stdout="",
            new_events=[],
            head_before_resume={
                "head_id": "fork_first_start",
                "parent_id": "fork_soft",
                "action_summary": "supervise:start",
                "doc_hash": "abc",
                "provider_thread_id": None,
            },
            head_after_resume={
                "head_id": "fork_second_start",
                "parent_id": "fork_soft",
                "action_summary": "supervise:start",
                "doc_hash": "abc",
                "provider_thread_id": None,
            },
        )
        is None
    )


def test_noop_super_cycle_errors_on_same_doc_head_advance_without_real_transition() -> None:
    err = noop_super_cycle_error(
        stdout="",
        new_events=[],
        head_before_resume={
            "head_id": "fork_old",
            "doc_hash": "abc",
            "provider_thread_id": None,
        },
        head_after_resume={
            "head_id": "fork_new",
            "parent_id": "fork_unrelated",
            "action_summary": "fork (hard)",
            "doc_hash": "abc",
            "provider_thread_id": None,
        },
    )
    assert err is not None
    assert "no-op provider cycle" in err


def test_noop_super_cycle_errors_when_stop_recovery_reuses_same_provider_thread() -> None:
    err = noop_super_cycle_error(
        stdout="",
        new_events=[],
        head_before_resume={
            "head_id": "fork_stop",
            "action_summary": "stop (hard)",
            "doc_hash": "abc",
            "provider_thread_id": "thread_stale",
        },
        head_after_resume={
            "head_id": "fork_restart",
            "parent_id": "fork_stop",
            "action_summary": "supervise:start",
            "doc_hash": "def",
            "provider_thread_id": "thread_stale",
        },
    )
    assert err is not None
    assert "empty recovery cycle after a stop decision" in err
