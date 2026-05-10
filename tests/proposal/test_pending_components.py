import importlib


def test_controller_threshold_policy_module_exists():
    importlib.import_module("controller.threshold_policy")


def test_controller_runtime_api_module_exists():
    importlib.import_module("controller.runtime_api")


def test_topology_module_exists():
    importlib.import_module("topo.topology")


def test_eval_pcap_parser_module_exists():
    importlib.import_module("eval.parse_pcap")
