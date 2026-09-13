import hashlib
import json

import pytest

from agent_alpha_audit.reconcile import (
    ReconciliationError,
    reconcile_rows,
)


def sha(payload):
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def event(
    trial_id,
    tag,
    payload,
    ts,
    source="s0",
    line=1,
):
    return {
        "schema": "x",
        "trial_id": trial_id,
        "tag": tag,
        "payload": payload,
        "payload_sha256": sha(payload),
        "timestamp": ts,
        "meta": {},
        "_audit_source": source,
        "_audit_line": line,
        "_audit_stream_index": int(source[-1]),
    }


def run_config(
    source,
    ts,
    *,
    train_end="2014-12-31",
    resume=False,
):
    payload = {
        "scenario": "factor",
        "run_kind": "confirmatory",
        "loop_n": 30,
        "run_lock": {
            "status": "LOCKED",
            "train_end": train_end,
        },
    }

    if resume:
        payload["resume_checkout_path"] = (
            f"/tmp/{source}/checkout"
        )
        payload["resume_session"] = (
            f"/tmp/{source}/session"
        )

    return event(
        "__run__",
        "run_config",
        payload,
        ts,
        source,
        1,
    )


def test_resume_only_config_differences_are_allowed():
    rows = [
        run_config(
            "s0",
            "2026-01-01T00:00:00+00:00",
        ),
        run_config(
            "s1",
            "2026-01-01T01:00:00+00:00",
            resume=True,
        ),
        event(
            "0",
            "proposal",
            {"p": "a"},
            "2026-01-01T00:10:00+00:00",
            "s0",
            2,
        ),
    ]

    _, report = reconcile_rows(
        rows,
        ["s0", "s1"],
    )

    c = report["run_config_consistency"]
    assert c["run_lock_consistent"] is True
    assert c["semantic_run_config_consistent"] is True


def test_locked_protocol_drift_hard_fails():
    rows = [
        run_config(
            "s0",
            "2026-01-01T00:00:00+00:00",
        ),
        run_config(
            "s1",
            "2026-01-01T01:00:00+00:00",
            train_end="2015-12-31",
            resume=True,
        ),
    ]

    with pytest.raises(
        ReconciliationError,
        match="run_lock drift",
    ):
        reconcile_rows(
            rows,
            ["s0", "s1"],
        )


def test_new_distinct_proposal_starts_new_attempt():
    rows = [
        run_config(
            "s0",
            "2026-01-01T00:00:00+00:00",
        ),
        run_config(
            "s1",
            "2026-01-01T01:00:00+00:00",
            resume=True,
        ),
        event(
            "18",
            "proposal",
            {"p": "old"},
            "2026-01-01T00:10:00+00:00",
            "s0",
            2,
        ),
        event(
            "18",
            "proposal",
            {"p": "new"},
            "2026-01-01T01:10:00+00:00",
            "s1",
            2,
        ),
        event(
            "18",
            "experiment_generation",
            {"x": "new"},
            "2026-01-01T01:11:00+00:00",
            "s1",
            3,
        ),
        event(
            "18",
            "coder_result",
            {"code": "new"},
            "2026-01-01T01:12:00+00:00",
            "s1",
            4,
        ),
        event(
            "18",
            "runner_result",
            {"metric": 1},
            "2026-01-01T01:13:00+00:00",
            "s1",
            5,
        ),
    ]

    logical, report = reconcile_rows(
        rows,
        ["s0", "s1"],
    )

    t18 = [
        x
        for x in logical
        if x.get("trial_id") == "18"
    ]

    proposal = [
        x
        for x in t18
        if x["tag"] == "proposal"
    ]

    assert len(proposal) == 1
    assert proposal[0]["payload"] == {"p": "new"}

    tr = report["trial_attempts"][0]
    assert tr["attempt_count"] == 2
    assert tr["canonical_attempt_index"] == 1
    assert tr["superseded_attempt_count"] == 1


def test_resume_can_continue_same_attempt_across_sources():
    feedback = {"decision": "done"}

    rows = [
        run_config(
            "s0",
            "2026-01-01T00:00:00+00:00",
        ),
        run_config(
            "s1",
            "2026-01-01T01:00:00+00:00",
            resume=True,
        ),
        event(
            "17",
            "proposal",
            {"p": "same"},
            "2026-01-01T00:10:00+00:00",
            "s0",
            2,
        ),
        event(
            "17",
            "experiment_generation",
            {"x": 1},
            "2026-01-01T00:11:00+00:00",
            "s0",
            3,
        ),
        event(
            "17",
            "coder_result",
            {"code": 1},
            "2026-01-01T01:10:00+00:00",
            "s1",
            2,
        ),
        event(
            "17",
            "feedback",
            feedback,
            "2026-01-01T01:11:00+00:00",
            "s1",
            3,
        ),
        event(
            "17",
            "feedback",
            feedback,
            "2026-01-01T01:12:00+00:00",
            "s1",
            4,
        ),
    ]

    logical, report = reconcile_rows(
        rows,
        ["s0", "s1"],
    )

    t17 = [
        x
        for x in logical
        if x.get("trial_id") == "17"
    ]

    assert {
        x["tag"]
        for x in t17
    } == {
        "proposal",
        "experiment_generation",
        "coder_result",
        "feedback",
    }

    tr = report["trial_attempts"][0]
    assert tr["attempt_count"] == 1
    assert report["exact_duplicate_groups"] == 1


def test_conflicting_same_stage_inside_attempt_fails():
    rows = [
        run_config(
            "s0",
            "2026-01-01T00:00:00+00:00",
        ),
        event(
            "0",
            "proposal",
            {"p": "a"},
            "2026-01-01T00:10:00+00:00",
            "s0",
            2,
        ),
        event(
            "0",
            "coder_result",
            {"code": "A"},
            "2026-01-01T00:11:00+00:00",
            "s0",
            3,
        ),
        event(
            "0",
            "coder_result",
            {"code": "B"},
            "2026-01-01T00:12:00+00:00",
            "s0",
            4,
        ),
    ]

    with pytest.raises(
        ReconciliationError,
        match="conflicting payloads",
    ):
        reconcile_rows(rows, ["s0"])
