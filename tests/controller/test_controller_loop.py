import json

from controller.controller import REGISTER_NAMES, run_controller
from controller.threshold_policy import ThresholdPolicyConfig


class FakeRuntime:
    def __init__(self):
        self.registers = {
            REGISTER_NAMES["threshold"]: 30,
            REGISTER_NAMES["classic_threshold"]: 80,
            REGISTER_NAMES["classic_protection_threshold"]: 16,
            REGISTER_NAMES["l4s_qdepth"]: 0,
            REGISTER_NAMES["classic_qdepth"]: 50,
            REGISTER_NAMES["l4s_delay"]: 0,
            REGISTER_NAMES["l4s_growth"]: 0,
            REGISTER_NAMES["classic_growth"]: 10,
        }
        self.writes = []

    def read_register(self, name):
        return self.registers[name]

    def write_register(self, name, value):
        self.registers[name] = value
        self.writes.append((name, value))


def test_controller_protects_classic_when_classic_backlog_is_visible(tmp_path):
    runtime = FakeRuntime()
    log_path = tmp_path / "controller_trace.jsonl"

    run_controller(
        runtime=runtime,
        config=ThresholdPolicyConfig(
            classic_backlog_threshold=20,
            tighten_step=5,
            relax_step=2,
            classic_adjust_step=2,
        ),
        interval_s=0,
        iterations=1,
        log_path=log_path,
    )

    assert (REGISTER_NAMES["threshold"], 25) in runtime.writes
    assert (REGISTER_NAMES["classic_threshold"], 82) in runtime.writes
    assert (REGISTER_NAMES["classic_protection_threshold"], 18) in runtime.writes

    row = json.loads(log_path.read_text())
    assert row["reason"] == "classic_backlog"
    assert row["protection_action"] == "protect_classic"
    assert row["new_classic_threshold"] == 82
    assert row["new_protection_threshold"] == 18


def test_controller_caps_classic_protection(tmp_path):
    runtime = FakeRuntime()
    runtime.registers[REGISTER_NAMES["classic_threshold"]] = 99
    runtime.registers[REGISTER_NAMES["classic_protection_threshold"]] = 31
    log_path = tmp_path / "controller_trace.jsonl"

    run_controller(
        runtime=runtime,
        config=ThresholdPolicyConfig(
            classic_backlog_threshold=20,
            classic_max_threshold=100,
            classic_protection_max_threshold=32,
            classic_adjust_step=2,
        ),
        interval_s=0,
        iterations=1,
        log_path=log_path,
    )

    assert (REGISTER_NAMES["classic_threshold"], 100) in runtime.writes
    assert (REGISTER_NAMES["classic_protection_threshold"], 32) in runtime.writes
