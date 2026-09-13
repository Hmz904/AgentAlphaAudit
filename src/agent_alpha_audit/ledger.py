from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import TrialRecord

DDL = """
CREATE TABLE IF NOT EXISTS trials (
  run_id TEXT NOT NULL,
  trial_id TEXT NOT NULL,
  parent_trial_id TEXT,
  agent TEXT NOT NULL,
  timestamp TEXT,
  model TEXT,
  action TEXT,
  hypothesis TEXT,
  rationale TEXT,
  factor_names_json TEXT NOT NULL,
  factor_expressions_json TEXT NOT NULL,
  prompt_hash TEXT,
  code_hash TEXT,
  data_snapshot TEXT,
  train_start TEXT,
  train_end TEXT,
  valid_start TEXT,
  valid_end TEXT,
  test_start TEXT,
  test_end TEXT,
  metrics_json TEXT NOT NULL,
  decision INTEGER,
  feedback_seen TEXT,
  holdout_access TEXT NOT NULL,
  cost_bps REAL,
  artifacts_json TEXT NOT NULL,
  raw_payload_hash TEXT,
  PRIMARY KEY (run_id, trial_id)
);
CREATE INDEX IF NOT EXISTS idx_trials_run ON trials(run_id);
"""


class TrialLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(DDL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def upsert(self, trial: TrialRecord) -> None:
        d = trial.to_dict()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO trials (
              run_id, trial_id, parent_trial_id, agent, timestamp, model, action, hypothesis, rationale,
              factor_names_json, factor_expressions_json, prompt_hash, code_hash, data_snapshot,
              train_start, train_end, valid_start, valid_end, test_start, test_end, metrics_json, decision,
              feedback_seen, holdout_access, cost_bps, artifacts_json, raw_payload_hash
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                d["run_id"], d["trial_id"], d["parent_trial_id"], d["agent"], d["timestamp"],
                d["model"], d["action"], d["hypothesis"], d["rationale"],
                json.dumps(d["factor_names"], ensure_ascii=False),
                json.dumps(d["factor_expressions"], ensure_ascii=False),
                d["prompt_hash"], d["code_hash"], d["data_snapshot"],
                d["train_start"], d["train_end"], d["valid_start"], d["valid_end"],
                d["test_start"], d["test_end"],
                json.dumps(d["metrics"], ensure_ascii=False, sort_keys=True),
                None if d["decision"] is None else int(d["decision"]),
                d["feedback_seen"], d["holdout_access"], d["cost_bps"],
                json.dumps(d["artifacts"], ensure_ascii=False, sort_keys=True),
                d["raw_payload_hash"],
            ),
        )
        self.conn.commit()

    def trials(self, run_id: str) -> list[TrialRecord]:
        self.conn.row_factory = sqlite3.Row
        rows = self.conn.execute(
            "SELECT * FROM trials WHERE run_id=? ORDER BY CAST(trial_id AS INTEGER), trial_id", (run_id,)
        ).fetchall()
        out: list[TrialRecord] = []
        for r in rows:
            out.append(
                TrialRecord(
                    run_id=r["run_id"], trial_id=r["trial_id"], parent_trial_id=r["parent_trial_id"],
                    agent=r["agent"], timestamp=r["timestamp"], model=r["model"], action=r["action"],
                    hypothesis=r["hypothesis"], rationale=r["rationale"],
                    factor_names=json.loads(r["factor_names_json"]),
                    factor_expressions=json.loads(r["factor_expressions_json"]),
                    prompt_hash=r["prompt_hash"], code_hash=r["code_hash"], data_snapshot=r["data_snapshot"],
                    train_start=r["train_start"], train_end=r["train_end"], valid_start=r["valid_start"],
                    valid_end=r["valid_end"], test_start=r["test_start"], test_end=r["test_end"],
                    metrics=json.loads(r["metrics_json"]),
                    decision=None if r["decision"] is None else bool(r["decision"]),
                    feedback_seen=r["feedback_seen"], holdout_access=r["holdout_access"],
                    cost_bps=r["cost_bps"], artifacts=json.loads(r["artifacts_json"]),
                    raw_payload_hash=r["raw_payload_hash"],
                )
            )
        return out

    def run_ids(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT run_id FROM trials ORDER BY run_id")]
