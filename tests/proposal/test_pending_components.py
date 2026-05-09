import importlib

import pytest


@pytest.mark.xfail(raises=ModuleNotFoundError, reason="controller module is not implemented yet", strict=True)
def test_controller_threshold_policy_module_exists():
    importlib.import_module("controller.threshold_policy")


@pytest.mark.xfail(raises=ModuleNotFoundError, reason="controller runtime API is not implemented yet", strict=True)
def test_controller_runtime_api_module_exists():
    importlib.import_module("controller.runtime_api")


@pytest.mark.xfail(raises=ModuleNotFoundError, reason="Mininet topology module is not implemented yet", strict=True)
def test_topology_module_exists():
    importlib.import_module("topo.topology")


@pytest.mark.xfail(raises=ModuleNotFoundError, reason="evaluation pcap parser is not implemented yet", strict=True)
def test_eval_pcap_parser_module_exists():
    importlib.import_module("eval.parse_pcap")
