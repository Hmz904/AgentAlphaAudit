from __future__ import annotations

import numpy as np


def summarize_known_truth_fdp(false_discoveries, rejections) -> dict[str, float]:
    """Summarize FDP tails when truth labels are known.

    Intended for controlled-null/synthetic stress tests only. Real factor audits do not
    have access to V (the number of false discoveries) and must not report empirical FDP.
    """
    v = np.asarray(false_discoveries, dtype=float)
    r = np.asarray(rejections, dtype=float)
    if v.shape != r.shape:
        raise ValueError("false_discoveries and rejections must have the same shape")
    if np.any(v < 0) or np.any(r < 0) or np.any(v > r):
        raise ValueError("require 0 <= V <= R")
    fdp = np.divide(v, np.maximum(r, 1.0))
    return {
        "mean_fdp": float(np.mean(fdp)),
        "median_fdp": float(np.median(fdp)),
        "fdp_q95": float(np.quantile(fdp, 0.95)),
        "prob_fdp_gt_0_5": float(np.mean(fdp > 0.5)),
        "mFDR_ratio_EV_ER": float(np.mean(v) / max(np.mean(r), 1e-12)),
        "mean_rejections": float(np.mean(r)),
    }
