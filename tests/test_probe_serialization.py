import json

import pandas as pd

from agent_alpha_audit.integrations.rdagent_probe import EventSink
from agent_alpha_audit.utils import safe_jsonable


class Obj:
    def __init__(self):
        self.hypothesis = "abc"
        self.data = list(range(10000))


def test_event_sink_omits_bulk_data(tmp_path):
    path = tmp_path / "events.jsonl"
    EventSink(path).emit("proposal", Obj(), 0)
    obj = json.loads(path.read_text().strip())
    assert obj["payload"]["hypothesis"] == "abc"
    assert "omitted" in obj["payload"]["data"]


def test_pandas_multiindex_series_preserves_metric_names():
    s = pd.Series(
        [0.11, 1.17],
        index=pd.MultiIndex.from_tuples(
            [("excess_return_with_cost", "annualized_return"), ("excess_return_with_cost", "information_ratio")]
        ),
    )
    payload = safe_jsonable(s)
    assert payload["excess_return_with_cost.annualized_return"] == 0.11
    assert payload["excess_return_with_cost.information_ratio"] == 1.17


def test_runner_snapshot_captures_successful_cumulative_factor_state():
    from types import SimpleNamespace

    from agent_alpha_audit.integrations.rdagent_probe import _runner_snapshot

    class FB:
        def __init__(self, ok): self.final_decision=ok
        def __bool__(self): return self.final_decision
    class Exp:
        def __init__(self, tasks, oks, based=None):
            self.sub_tasks=[SimpleNamespace(factor_name=n, factor_formulation=f) for n,f in tasks]
            self.prop_dev_feedback=[FB(x) for x in oks]
            self.based_experiments=based or []
            self.running_info=SimpleNamespace(result=None)
            self.sub_results={}; self.hypothesis=None; self.stdout=''
        @property
        def result(self): return self.running_info.result

    prev=Exp([('a','f_a'),('bad','f_bad')],[True,False])
    cur=Exp([('b','f_b')],[True],[prev])
    snap=_runner_snapshot(cur)
    assert snap['factor_state']['current_successful']==[{'name':'b','formulation':'f_b'}]
    assert snap['factor_state']['cumulative_successful']==[
        {'name':'a','formulation':'f_a'}, {'name':'b','formulation':'f_b'}
    ]
