from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

ORDER = ["agent_reported", "exact_reproduction", "pit", "availability_lag", "costs", "frozen_oos"]
LABELS = {
    "agent_reported": "Agent reported",
    "exact_reproduction": "Exact reproduction",
    "pit": "+ PIT",
    "availability_lag": "+ availability lag",
    "costs": "+ costs",
    "frozen_oos": "Frozen OOS",
}


def plot_audit_waterfall(stages: dict[str, float], path: str | Path, metric: str = "Sharpe") -> None:
    keys = [k for k in ORDER if k in stages]
    if not keys:
        raise ValueError("no recognized stages")
    vals = [float(stages[k]) for k in keys]
    labels = [LABELS[k] for k in keys]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.barh(labels[::-1], vals[::-1])
    ax.set_xlabel(metric)
    ax.set_title(f"Alpha Audit Waterfall — {metric}")
    for i, v in enumerate(vals[::-1]):
        ax.text(v, i, f" {v:.2f}", va="center")
    fig.tight_layout()
    fig.savefig(path, format=Path(path).suffix.lstrip(".") or "svg")
    plt.close(fig)
