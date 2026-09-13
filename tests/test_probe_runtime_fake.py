import asyncio
import json
import sys
import types

import pandas as pd

from agent_alpha_audit.adapters.rdagent import RDAgentSidecarAdapter
from agent_alpha_audit.integrations.rdagent_probe import EventSink, install_quant_probe


class FakeSettings:
    step_semaphore = 1
    subproc_step = False

    @staticmethod
    def get_max_parallel():
        return 1


class FakeHypothesis:
    def __init__(self, hypothesis="H7", reason="reason", action="factor"):
        self.hypothesis = hypothesis
        self.reason = reason
        self.action = action


class FakeHypothesisFeedback:
    """Faithful to RD-Agent 0.8.0 HypothesisFeedback public attributes."""

    def __init__(self, decision=True):
        self.decision = decision
        self.reason = "improved"
        self.observations = "validation improved"
        self.hypothesis_evaluation = "supported"
        self.new_hypothesis = "next"
        self.acceptable = None


class FakeRunningInfo:
    def __init__(self, result):
        self.result = result
        self.running_time = 1.2


class FakeExperiment:
    """Faithful to RD-Agent Experiment.result -> running_info.result contract."""

    def __init__(self, result):
        self.running_info = FakeRunningInfo(result)
        self.sub_results = {"rank_ic": 0.022}
        self.hypothesis = FakeHypothesis()
        self.stdout = "ok"

    @property
    def result(self):
        return self.running_info.result


def _install_fake_rdagent(monkeypatch, loop_cls):
    # When the real pinned RD-Agent package is installed, preserve its package
    # parents so imports such as rdagent.scenarios.* retain a valid __path__.
    # Only replace the two leaf modules needed by these unit tests.
    try:
        import rdagent
        import rdagent.app
        import rdagent.app.qlib_rd_loop
        import rdagent.core  # noqa: F401
    except ImportError:
        package_names = [
            "rdagent",
            "rdagent.app",
            "rdagent.app.qlib_rd_loop",
            "rdagent.core",
        ]
        for name in package_names:
            module = types.ModuleType(name)
            module.__path__ = []
            monkeypatch.setitem(sys.modules, name, module)

    quant_mod = types.ModuleType("rdagent.app.qlib_rd_loop.quant")
    quant_mod.QuantRDLoop = loop_cls
    monkeypatch.setitem(sys.modules, "rdagent.app.qlib_rd_loop.quant", quant_mod)

    conf_mod = types.ModuleType("rdagent.core.conf")
    conf_mod.RD_AGENT_SETTINGS = FakeSettings()
    monkeypatch.setitem(sys.modules, "rdagent.core.conf", conf_mod)


def test_probe_captures_v080_feedback_and_qlib_series(monkeypatch, tmp_path):
    idx = pd.MultiIndex.from_tuples(
        [
            ("excess_return_with_cost", "annualized_return"),
            ("excess_return_with_cost", "information_ratio"),
            ("excess_return_with_cost", "max_drawdown"),
        ]
    )
    qlib_result = pd.Series([0.121, 1.23, -0.087], index=idx)

    class FakeQuantRDLoop:
        # RD-Agent workflow LoopBase uses this internal key.
        LOOP_IDX_KEY = "_LOOP_IDX"

        def __init__(self):
            self.loop_idx = 7
            self.trace = types.SimpleNamespace(hist=[])

        def _propose(self, *args, **kwargs):
            return FakeHypothesis()

        async def direct_exp_gen(self, prev_out):
            return {"propose": FakeHypothesis(), "exp_gen": {"formula": "rank(close)"}}

        def coding(self, prev_out):
            return {"code": "x = 1"}

        def running(self, prev_out):
            return FakeExperiment(qlib_result)

        def feedback(self, prev_out):
            # RD-Agent 0.8.0 behavior: append to trace and return None.
            fb = FakeHypothesisFeedback(decision=True)
            self.trace.hist.append((prev_out.get("running"), fb))

    _install_fake_rdagent(monkeypatch, FakeQuantRDLoop)

    event_path = tmp_path / "events.jsonl"
    install_quant_probe(event_path)

    # Confirmatory run-config proves the agent-visible windows are disjoint from frozen OOS.
    EventSink(event_path).emit(
        "run_config",
        {
            "run_lock": {
                "train_start": "2018-01-01",
                "train_end": "2020-12-31",
                "validation_start": "2021-01-01",
                "validation_end": "2021-12-31",
                "agent_visible_test_start": "2022-01-01",
                "agent_visible_test_end": "2022-12-31",
                "frozen_oos_start": "2023-01-01",
                "frozen_oos_end": "2024-12-31",
            }
        },
        "__run__",
    )

    loop = FakeQuantRDLoop()
    loop._propose()
    prev = {"_LOOP_IDX": 7}
    asyncio.run(loop.direct_exp_gen(prev))
    loop.coding(prev)
    exp = loop.running(prev)
    prev["running"] = exp
    assert loop.feedback(prev) is None

    events = [json.loads(x) for x in event_path.read_text(encoding="utf-8").splitlines()]
    trial_events = [e for e in events if e["trial_id"] == "7"]
    assert [e["tag"] for e in trial_events] == [
        "proposal",
        "experiment_generation",
        "coder_result",
        "runner_result",
        "feedback",
    ]
    assert trial_events[-1]["payload"]["decision"] is True
    assert trial_events[3]["payload"]["result"]["excess_return_with_cost.information_ratio"] == 1.23

    trials = RDAgentSidecarAdapter().parse(event_path, "contract")
    assert len(trials) == 1
    t = trials[0]
    assert t.decision is True
    assert t.feedback_seen == "validation improved"
    assert t.metrics["information_ratio"] == 1.23
    assert t.metrics["annualized_return"] == 0.121
    assert t.metrics["max_drawdown"] == -0.087
    assert t.metrics["rank_ic"] == 0.022
    assert t.holdout_access == "unknown"  # dates in a lock alone are not behavioral holdout evidence


def test_probe_records_proposal_before_later_failure(monkeypatch, tmp_path):
    class FakeQuantRDLoop:
        LOOP_IDX_KEY = "_LOOP_IDX"

        def __init__(self):
            self.loop_idx = 3
            self.trace = types.SimpleNamespace(hist=[])

        def _propose(self):
            return FakeHypothesis("H3")

        async def direct_exp_gen(self, prev_out):
            raise RuntimeError("conversion failed")

        def coding(self, prev_out):
            raise AssertionError

        def running(self, prev_out):
            raise AssertionError

        def feedback(self, prev_out):
            raise AssertionError

    _install_fake_rdagent(monkeypatch, FakeQuantRDLoop)
    event_path = tmp_path / "events.jsonl"
    install_quant_probe(event_path)
    loop = FakeQuantRDLoop()
    loop._propose()
    events = [json.loads(x) for x in event_path.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 1
    assert events[0]["tag"] == "proposal"
    assert events[0]["trial_id"] == "3"


def test_probe_refuses_parallel_or_subprocess_execution(monkeypatch, tmp_path):
    class ParallelSettings:
        step_semaphore = 2
        subproc_step = False

        @staticmethod
        def get_max_parallel():
            return 2

    class FakeQuantRDLoop:
        def _propose(self):
            return None
        async def direct_exp_gen(self, prev_out):
            return None
        def coding(self, prev_out):
            return None
        def running(self, prev_out):
            return None
        def feedback(self, prev_out):
            return None

    _install_fake_rdagent(monkeypatch, FakeQuantRDLoop)
    sys.modules["rdagent.core.conf"].RD_AGENT_SETTINGS = ParallelSettings()
    import pytest
    with pytest.raises(RuntimeError, match="serial"):
        install_quant_probe(tmp_path / "events.jsonl")


def test_probe_observes_actual_workspace_config_before_qrun(monkeypatch, tmp_path):
    lock = {
        'train_start':'2008-01-01','train_end':'2014-12-31',
        'validation_start':'2015-01-01','validation_end':'2016-12-31',
        'agent_visible_test_start':'2017-01-01','agent_visible_test_end':'2020-08-01',
    }
    yaml = '''\nqlib_init:\n  provider_uri: "~/.qlib/qlib_data/cn_data"\ntask:\n  dataset:\n    kwargs:\n      segments:\n        train: [2008-01-01, 2014-12-31]\n        valid: [2015-01-01, 2016-12-31]\n        test: [2017-01-01, 2020-08-01]\n'''

    class FakeQlibFBWorkspace:
        def __init__(self, root):
            self.workspace_path = root
        def execute(self, qlib_config_name='conf.yaml', run_env=None, *args, **kwargs):
            return {'ok': 1}, 'stdout'

    workspace_mod = types.ModuleType('rdagent.scenarios.qlib.experiment.workspace')
    workspace_mod.QlibFBWorkspace = FakeQlibFBWorkspace
    for name in [
        'rdagent.scenarios', 'rdagent.scenarios.qlib', 'rdagent.scenarios.qlib.experiment'
    ]:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, 'rdagent.scenarios.qlib.experiment.workspace', workspace_mod)

    class FakeQuantRDLoop:
        LOOP_IDX_KEY = '_LOOP_IDX'
        def __init__(self):
            self.loop_idx = 1
            self.trace = types.SimpleNamespace(hist=[])
        def _propose(self): return FakeHypothesis('H1')
        async def direct_exp_gen(self, prev_out): return {'exp_gen': {'formula':'x'}}
        def coding(self, prev_out): return {'code':'x'}
        def running(self, prev_out):
            root = tmp_path/'ws'; root.mkdir(exist_ok=True)
            (root/'conf.yaml').write_text(yaml)
            ws = FakeQlibFBWorkspace(root)
            ws.execute('conf.yaml')
            return FakeExperiment(pd.Series({'information_ratio': 1.0}))
        def feedback(self, prev_out):
            fb=FakeHypothesisFeedback(True); self.trace.hist.append((None,fb)); 

    _install_fake_rdagent(monkeypatch, FakeQuantRDLoop)
    event_path=tmp_path/'runtime_events.jsonl'
    from agent_alpha_audit.integrations.rdagent_probe import install_rdagent_probe
    install_rdagent_probe(
        event_path,
        loop_cls=FakeQuantRDLoop,
        run_lock=lock,
        expected_provider_uri='~/.qlib/qlib_data/cn_data',
    )
    loop=FakeQuantRDLoop(); prev={'_LOOP_IDX':1}
    loop.running(prev)
    events=[json.loads(x) for x in event_path.read_text().splitlines()]
    cfg=[e for e in events if e['tag']=='runtime_qlib_config']
    assert len(cfg)==1
    assert cfg[0]['trial_id']=='1'
    assert cfg[0]['payload']['status']=='match'
    assert len(cfg[0]['payload']['config_sha256'])==64
