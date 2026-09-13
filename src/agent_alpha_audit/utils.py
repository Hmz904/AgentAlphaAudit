from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BLOCKED_KEYS = {"data", "df", "array", "values", "workspace", "cache", "model"}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def json_fingerprint(obj: Any) -> str:
    return sha256_text(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str))


def _index_key(x: Any) -> str:
    if isinstance(x, tuple):
        return ".".join(str(v) for v in x)
    return str(x)


def safe_jsonable(obj: Any, depth: int = 0, max_depth: int = 5, max_items: int = 100) -> Any:
    """Best-effort compact serialization for audit events.

    Important design choice: pandas objects are serialized *before* generic object
    introspection. RD-Agent/Qlib stores experiment metrics in ``Experiment.result``
    and that value is commonly a pandas Series with a MultiIndex. Falling through
    to ``Series.__dict__`` loses the values and silently turns real runs into an
    empty metric ledger.
    """
    if depth > max_depth:
        return f"<{type(obj).__name__}>"
    if obj is None or isinstance(obj, (bool, int, float, str)):
        if isinstance(obj, str) and len(obj) > 12000:
            return obj[:12000] + "...[truncated]"
        return obj
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, Path):
        return str(obj)

    if isinstance(obj, pd.Series):
        out: dict[str, Any] = {}
        items = list(obj.items())
        for i, (k, v) in enumerate(items[:max_items]):
            out[_index_key(k)] = safe_jsonable(v, depth + 1, max_depth, max_items)
        if len(items) > max_items:
            out["__truncated__"] = len(items) - max_items
        return out

    if isinstance(obj, pd.DataFrame):
        # DataFrames can be large. Preserve a bounded, metric-friendly snapshot.
        rows = min(len(obj), max_items)
        cols = min(len(obj.columns), max_items)
        sub = obj.iloc[:rows, :cols]
        return {
            "__pandas_dataframe__": True,
            "shape": [int(obj.shape[0]), int(obj.shape[1])],
            "columns": [_index_key(c) for c in sub.columns],
            "records": [
                {str(k): safe_jsonable(v, depth + 2, max_depth, max_items) for k, v in row.items()}
                for row in sub.to_dict(orient="records")
            ],
        }

    if isinstance(obj, np.ndarray):
        flat = obj.reshape(-1)
        vals = [safe_jsonable(v, depth + 1, max_depth, max_items) for v in flat[:max_items]]
        return {"__ndarray__": True, "shape": list(obj.shape), "values": vals}

    if is_dataclass(obj):
        obj = asdict(obj)
    if hasattr(obj, "model_dump"):
        try:
            obj = obj.model_dump()
        except Exception:  # noqa: BLE001, S110 - best-effort serializer
            pass
    if isinstance(obj, dict):
        out = {}
        for i, (k, v) in enumerate(obj.items()):
            if i >= max_items:
                out["__truncated__"] = len(obj) - max_items
                break
            ks = str(k)
            if ks.lower() in BLOCKED_KEYS:
                out[ks] = f"<{type(v).__name__}: omitted>"
            else:
                out[ks] = safe_jsonable(v, depth + 1, max_depth, max_items)
        return out
    if isinstance(obj, (list, tuple, set)):
        vals = list(obj)
        return [safe_jsonable(v, depth + 1, max_depth, max_items) for v in vals[:max_items]]
    if hasattr(obj, "__dict__"):
        d = {k: v for k, v in vars(obj).items() if not k.startswith("_")}
        if d:
            return safe_jsonable(d, depth + 1, max_depth, max_items)
    return repr(obj)[:12000]
