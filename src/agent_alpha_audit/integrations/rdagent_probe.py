from __future__ import annotations

"""Runtime probe for Microsoft RD-Agent(Q), pinned audit target v0.8.0.

The probe is deliberately in-process and serial. RD-Agent can execute workflow
steps in subprocesses when ``subproc_step`` is enabled or max parallelism exceeds
one; ordinary monkeypatches do not propagate to those subprocesses. This module
therefore fails loudly rather than silently producing an incomplete audit trail.
"""

import datetime as dt
import json
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from ..config_audit import inspect_runtime_config, reconcile_runtime_config_with_lock
from ..utils import json_fingerprint, safe_jsonable

_ACTIVE_TRIAL_ID: ContextVar[str] = ContextVar("agent_alpha_audit_active_trial_id", default="unknown")


class EventSink:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, tag: str, obj: Any, trial_id: Any, meta: dict[str, Any] | None = None) -> None:
        payload = safe_jsonable(obj)
        event = {
            "schema": "agent-alpha-audit.rdagent-event.v2",
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            "trial_id": str(trial_id),
            "tag": tag,
            "payload": payload,
            "payload_sha256": json_fingerprint(payload),
            "meta": meta or {},
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _successful_factor_tasks(exp: Any) -> list[dict[str, Any]]:
    """Return factor tasks whose implementation feedback is truthy.

    RD-Agent's factor runner builds combined factor data from sub-workspaces paired
    with truthy CoSTEER feedback. Capturing the same condition lets the audit record
    the actual cumulative factor-library state rather than reconstructing it from
    feedback decisions or from all proposed formulations.
    """
    tasks = list(getattr(exp, "sub_tasks", None) or [])
    feedbacks = getattr(exp, "prop_dev_feedback", None)
    if not tasks or feedbacks is None:
        return []
    try:
        fbs = list(feedbacks)
    except TypeError:
        return []
    out: list[dict[str, Any]] = []
    for task, fb in zip(tasks, fbs):
        try:
            ok = bool(fb)
        except Exception:  # noqa: BLE001 - third-party truthiness may raise
            ok = False
        if not ok:
            continue
        name = getattr(task, "factor_name", None) or getattr(task, "name", None)
        formulation = getattr(task, "factor_formulation", None)
        if formulation is not None:
            out.append({"name": str(name) if name is not None else None, "formulation": str(formulation)})
    return out


def _factor_state_snapshot(obj: Any) -> dict[str, Any]:
    current = _successful_factor_tasks(obj)
    cumulative: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str]] = set()
    for exp in list(getattr(obj, "based_experiments", None) or []) + [obj]:
        for task in _successful_factor_tasks(exp):
            key = (task.get("name"), task["formulation"])
            if key not in seen:
                seen.add(key)
                cumulative.append(task)
    return {"current_successful": current, "cumulative_successful": cumulative}


def _runner_snapshot(obj: Any) -> dict[str, Any]:
    """Extract the audit-relevant public surface of an RD-Agent Experiment."""
    try:
        result = obj.result
    except Exception as exc:  # noqa: BLE001 - preserve result-access failure as evidence
        result = {"__result_access_error__": repr(exc)}
    return {
        "experiment_type": type(obj).__name__,
        "result": safe_jsonable(result),
        "sub_results": safe_jsonable(getattr(obj, "sub_results", None)),
        "hypothesis": safe_jsonable(getattr(obj, "hypothesis", None)),
        "stdout": safe_jsonable(getattr(obj, "stdout", None)),
        "factor_state": safe_jsonable(_factor_state_snapshot(obj)),
    }


def _feedback_from_trace(loop: Any, returned: Any) -> Any:
    """Support both RD-Agent 0.8.0 and newer feedback contracts.

    v0.8.0 appends ``(experiment, feedback)`` to ``trace.hist`` and returns None.
    Newer main currently returns the feedback object directly. Prefer the explicit
    return when present; otherwise read the just-appended trace entry.
    """
    if returned is not None:
        return returned
    hist = getattr(getattr(loop, "trace", None), "hist", None)
    if hist:
        last = hist[-1]
        if isinstance(last, (tuple, list)) and len(last) >= 2:
            return last[1]
    return None


def _assert_inprocess_serial_mode() -> None:
    """Fail if RD-Agent workflow steps may execute outside this interpreter."""
    try:
        from rdagent.core.conf import RD_AGENT_SETTINGS
    except ImportError:
        # Faithful-stub tests do not need the full RD-Agent package.
        return
    max_parallel = int(RD_AGENT_SETTINGS.get_max_parallel())
    subproc = bool(getattr(RD_AGENT_SETTINGS, "subproc_step", False))
    if subproc or max_parallel > 1:
        raise RuntimeError(
            "AgentAlphaAudit runtime probe requires in-process serial RD-Agent execution: "
            f"subproc_step={subproc}, max_parallel={max_parallel}. Set subproc_step=False "
            "and step_semaphore=1 before installing the probe."
        )


def _install_workspace_execute_probe(
    sink: EventSink,
    *,
    run_lock: dict[str, Any] | None = None,
    expected_provider_uri: str | None = None,
) -> None:
    """Observe the exact workspace config passed to qrun, and hard-gate it when locked.

    Static template inspection is only a preflight. This wrapper observes the file in
    ``experiment_workspace.workspace_path`` immediately before upstream
    ``QlibFBWorkspace.execute`` invokes qrun.
    """
    try:
        from rdagent.scenarios.qlib.experiment.workspace import QlibFBWorkspace
    except ImportError:
        return
    if getattr(QlibFBWorkspace, "__agent_alpha_audit_execute_probe__", False):
        return
    original_execute = QlibFBWorkspace.execute

    def execute(self, qlib_config_name: str = "conf.yaml", run_env: dict | None = None, *args, **kwargs):
        config_path = Path(self.workspace_path) / qlib_config_name
        tid = _ACTIVE_TRIAL_ID.get()
        meta = {"id_source": "active_running_context", "observation": "actual_workspace_before_qrun"}
        try:
            if run_lock is not None:
                snap = reconcile_runtime_config_with_lock(
                    config_path, run_lock, expected_provider_uri=expected_provider_uri
                )
            else:
                snap = inspect_runtime_config(config_path)
            snap["run_env"] = safe_jsonable(run_env or {})
            sink.emit("runtime_qlib_config", snap, tid, meta)
        except Exception as exc:
            try:
                snap = inspect_runtime_config(config_path)
            except Exception as inspect_exc:  # noqa: BLE001 - preserve gate inspection failure
                snap = {
                    "config_path": str(config_path),
                    "status": "inspection_failed",
                    "inspection_error": repr(inspect_exc),
                }
            snap["status"] = "mismatch_or_unreadable"
            snap["gate_error"] = repr(exc)
            snap["run_env"] = safe_jsonable(run_env or {})
            sink.emit("runtime_qlib_config", snap, tid, meta)
            raise
        return original_execute(
            self, *args, qlib_config_name=qlib_config_name, run_env=run_env or {}, **kwargs
        )

    QlibFBWorkspace.execute = execute
    QlibFBWorkspace.__agent_alpha_audit_execute_probe__ = True


def install_rdagent_probe(
    path: str | Path,
    loop_cls: type | None = None,
    *,
    run_lock: dict[str, Any] | None = None,
    expected_provider_uri: str | None = None,
) -> None:
    """Monkeypatch an RD-Agent RDLoop subclass at proposal/coding/running/feedback boundaries.

    The first locked audit target is FactorRDLoop, but QuantRDLoop is supported for pilot
    integration tests. Trial IDs rely on the serial workflow invariant: `_propose` is
    called from `direct_exp_gen` while `self.loop_idx` equals the active loop.
    """
    _assert_inprocess_serial_mode()
    if loop_cls is None:
        try:
            from rdagent.app.qlib_rd_loop.quant import QuantRDLoop
        except ImportError as e:
            raise RuntimeError("RD-Agent is not installed; install the pinned target environment first") from e
        loop_cls = QuantRDLoop

    if getattr(loop_cls, "__agent_alpha_audit_probe__", False):
        return

    sink = EventSink(path)
    _install_workspace_execute_probe(
        sink, run_lock=run_lock, expected_provider_uri=expected_provider_uri
    )
    original_propose = loop_cls._propose
    original_direct = loop_cls.direct_exp_gen
    original_coding = loop_cls.coding
    original_running = loop_cls.running
    original_feedback = loop_cls.feedback

    def _trial_id(self, prev_out):
        key = getattr(self, "LOOP_IDX_KEY", None)
        if key is not None and isinstance(prev_out, dict) and key in prev_out:
            return prev_out[key]
        return getattr(self, "loop_idx", "unknown")

    def propose(self, *args, **kwargs):
        out = original_propose(self, *args, **kwargs)
        # Proposal is recorded immediately, before experiment conversion/coding can fail.
        # The ID is valid because the audit wrapper forces serial in-process execution.
        sink.emit("proposal", out, getattr(self, "loop_idx", "unknown"), {"id_source": "self.loop_idx"})
        return out

    async def direct_exp_gen(self, prev_out):
        out = await original_direct(self, prev_out)
        tid = _trial_id(self, prev_out)
        if isinstance(out, dict):
            sink.emit("experiment_generation", out.get("exp_gen"), tid, {"id_source": "prev_out.LOOP_IDX_KEY"})
        else:
            sink.emit("experiment_generation", out, tid, {"id_source": "prev_out.LOOP_IDX_KEY"})
        return out

    def wrap_sync(original: Callable, tag: str, transform: Callable[[Any], Any] | None = None):
        def wrapped(self, prev_out):
            out = original(self, prev_out)
            payload = transform(out) if transform is not None else out
            sink.emit(tag, payload, _trial_id(self, prev_out), {"id_source": "prev_out.LOOP_IDX_KEY"})
            return out
        return wrapped

    def feedback(self, prev_out):
        _assert_inprocess_serial_mode()
        out = original_feedback(self, prev_out)
        payload = _feedback_from_trace(self, out)
        sink.emit("feedback", payload, _trial_id(self, prev_out), {"id_source": "prev_out.LOOP_IDX_KEY"})
        return out

    def running(self, prev_out):
        tid = _trial_id(self, prev_out)
        token = _ACTIVE_TRIAL_ID.set(str(tid))
        try:
            out = original_running(self, prev_out)
        finally:
            _ACTIVE_TRIAL_ID.reset(token)
        sink.emit(
            "runner_result",
            _runner_snapshot(out),
            tid,
            {"id_source": "prev_out.LOOP_IDX_KEY"},
        )
        return out

    loop_cls._propose = propose
    loop_cls.direct_exp_gen = direct_exp_gen
    loop_cls.coding = wrap_sync(original_coding, "coder_result")
    loop_cls.running = running
    loop_cls.feedback = feedback
    loop_cls.__agent_alpha_audit_probe__ = True


def install_quant_probe(path: str | Path) -> None:
    """Backward-compatible alias for older integrations/tests."""
    install_rdagent_probe(path)
