from agent_alpha_audit.integrations.rdagent_probe import EventSink


def test_probe_module_imports_without_rdagent():
    # Probe installation is optional and should not import RD-Agent until install_quant_probe is called.
    assert EventSink is not None
