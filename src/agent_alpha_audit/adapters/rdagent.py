from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..models import TrialRecord
from ..utils import json_fingerprint, sha256_text
from .base import AgentAdapter

METRIC_ALIASES = {
    "sharpe": "sharpe",
    "sharpe_ratio": "sharpe",
    "information_ratio": "information_ratio",
    "ic": "ic",
    "icir": "icir",
    "rank_ic": "rank_ic",
    "rank_icir": "rank_icir",
    "annualized_return": "annualized_return",
    "annualized_rate_of_return": "annualized_return",
    "arr": "annualized_return",
    "max_drawdown": "max_drawdown",
    "mdd": "max_drawdown",
    "turnover": "turnover",
}


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                out.update(_flatten(v, key))
            else:
                out[key] = v
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    return out


def _search_strings(payload: Any, patterns: list[str]) -> list[str]:
    flat = _flatten(payload)
    vals: list[str] = []
    for k, v in flat.items():
        kl = k.lower()
        if any(p in kl for p in patterns) and isinstance(v, (str, int, float, bool)):
            vals.append(str(v))
    return vals


def _first(payload: Any, patterns: list[str]) -> str | None:
    vals = _search_strings(payload, patterns)
    return vals[0] if vals else None


def _metrics(payload: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in _flatten(payload).items():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        # Qlib Series MultiIndex keys are serialized as dot-separated paths, so the
        # last component still names the actual metric (e.g. information_ratio).
        leaf = re.split(r"[.\[\]]+", k.lower())[-1].strip()
        if leaf in METRIC_ALIASES:
            out[METRIC_ALIASES[leaf]] = float(v)
    return out


def _factor_exprs(payload: Any) -> list[str]:
    candidates = _search_strings(payload, ["expression", "formula"])
    seen, out = set(), []
    for x in candidates:
        if x not in seen and len(x) <= 4000:
            seen.add(x)
            out.append(x)
    return out


def _parse_date(x: str | None) -> dt.date | None:
    if not x:
        return None
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def _overlap(a0: str | None, a1: str | None, b0: str | None, b1: str | None) -> bool | None:
    aa0, aa1, bb0, bb1 = map(_parse_date, (a0, a1, b0, b1))
    if None in (aa0, aa1, bb0, bb1):
        return None
    return max(aa0, bb0) <= min(aa1, bb1)


def _run_config(all_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for ev in all_events:
        if ev.get("tag") == "run_config" and isinstance(ev.get("payload"), dict):
            return ev["payload"]
    return None


def _holdout_status(all_events: list[dict[str, Any]], lock: dict[str, Any] | None) -> str:
    """Behavioral/physical holdout evidence, not lock self-consistency.

    `no` requires both (i) installed runtime Qlib template segments/provider reconciled
    to the lock and (ii) the calendar under that exact provider_uri physically ending
    before frozen OOS. A lock by itself is never enough.
    """
    cfg = _run_config(all_events)
    if not lock or not cfg:
        return "unknown"
    rec = cfg.get("template_reconciliation")
    cutoff = cfg.get("physical_data_cutoff")
    runtime_cfgs = [
        ev.get("payload") for ev in all_events
        if ev.get("tag") == "runtime_qlib_config" and isinstance(ev.get("payload"), dict)
    ]
    runtime_match = bool(runtime_cfgs) and all(x.get("status") == "match" for x in runtime_cfgs)
    if (
        isinstance(rec, dict) and rec.get("status") == "match"
        and isinstance(cutoff, dict) and cutoff.get("status") == "physically_excluded"
        and runtime_match
    ):
        return "no"
    return "unknown"


def _extract_lock(all_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for ev in all_events:
        if ev.get("tag") != "run_config":
            continue
        payload = ev.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("run_lock"), dict):
            return payload["run_lock"]
    return None


class RDAgentSidecarAdapter(AgentAdapter):
    """Parse JSONL emitted by integrations.rdagent_probe.

    Sidecar-only by design: no RD-Agent pickle/session deserialization.
    """

    def parse(self, path: str | Path, run_id: str) -> list[TrialRecord]:
        events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        all_events: list[dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                ev = json.loads(line)
                all_events.append(ev)
                trial_id = str(ev.get("trial_id", "unknown"))
                if trial_id.startswith("__"):
                    continue
                events[trial_id].append(ev)

        lock = _extract_lock(all_events)
        holdout_status = _holdout_status(all_events, lock)
        records: list[TrialRecord] = []
        for tid in sorted(events, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x)):
            evs = events[tid]
            by_tag = {e.get("tag"): e for e in evs}
            proposal = by_tag.get("proposal", {}).get("payload", {})
            runner = by_tag.get("runner_result", {}).get("payload", {})
            feedback = by_tag.get("feedback", {}).get("payload", {})
            exp = by_tag.get("experiment_generation", {}).get("payload", {})
            cfg = _run_config(all_events) or {}
            action = _first(proposal, ["action"]) or ("factor" if cfg.get("scenario") == "factor" else None)
            hypothesis = _first(proposal, ["hypothesis", "hypothesis_text", "statement"])
            rationale = _first(proposal, ["reason", "rationale"])
            decision_raw = _first(feedback, ["decision"])
            decision = None
            if decision_raw is not None:
                decision = decision_raw.lower() in {"true", "1", "yes"}
            # Trial expressions come from the generated experiment, not the runner's cumulative state.
            exprs = _factor_exprs({"experiment": exp})
            cumulative_exprs = _factor_exprs({"factor_state": (runner or {}).get("factor_state", {})})
            metrics = _metrics(runner)
            feedback_text = (
                _first(feedback, ["observations"])
                or _first(feedback, ["hypothesis_evaluation"])
                or _first(feedback, ["reason"])
            )
            raw_hash = json_fingerprint(evs)
            id_sources = {str(e.get("tag")): (e.get("meta") or {}).get("id_source", "unrecorded") for e in evs}
            runtime_cfgs = [e.get("payload") for e in evs if e.get("tag") == "runtime_qlib_config"]
            timestamps = [e.get("timestamp") for e in evs if e.get("timestamp")]
            record = TrialRecord(
                run_id=run_id,
                trial_id=tid,
                parent_trial_id=None,
                agent="Microsoft RD-Agent(Q)",
                timestamp=min(timestamps) if timestamps else None,
                action=action,
                hypothesis=hypothesis,
                rationale=rationale,
                factor_expressions=exprs,
                code_hash=sha256_text(
                    json.dumps(by_tag.get("coder_result", {}).get("payload", {}), sort_keys=True, default=str)
                ),
                train_start=lock.get("train_start") if lock else None,
                train_end=lock.get("train_end") if lock else None,
                valid_start=lock.get("validation_start") if lock else None,
                valid_end=lock.get("validation_end") if lock else None,
                test_start=lock.get("agent_visible_test_start") if lock else None,
                test_end=lock.get("agent_visible_test_end") if lock else None,
                metrics=metrics,
                decision=decision,
                feedback_seen=feedback_text,
                holdout_access=holdout_status,
                artifacts={
                    "id_sources": json.dumps(id_sources, sort_keys=True),
                    "runtime_qlib_configs": json.dumps(runtime_cfgs, ensure_ascii=False, sort_keys=True),
                    "cumulative_factor_expressions": json.dumps(cumulative_exprs, ensure_ascii=False),
                },
                raw_payload_hash=raw_hash,
            )
            records.append(record)
        return records
