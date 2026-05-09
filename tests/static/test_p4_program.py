import json
import shutil
import subprocess

import pytest


EXPECTED_TABLES = {
    "IngressImpl.ipv4_lpm",
    "IngressImpl.l2_forward",
}

EXPECTED_ACTIONS = {
    "IngressImpl.drop",
    "IngressImpl.set_nhop",
    "IngressImpl.set_egress",
    "IngressImpl.set_mcast_grp",
}

EXPECTED_REGISTERS = {
    "reg_l4s_threshold",
    "reg_classic_threshold",
    "reg_classic_protection_threshold",
    "reg_classic_protection_budget",
    "reg_l4s_qdepth",
    "reg_classic_qdepth",
    "reg_l4s_delay",
    "reg_classic_delay",
    "reg_l4s_growth",
    "reg_classic_growth",
    "reg_l4s_prev_enq_qdepth",
    "reg_classic_prev_enq_qdepth",
}


def compile_p4(tmp_path):
    p4c = shutil.which("p4c-bm2-ss")
    if not p4c:
        pytest.skip("p4c-bm2-ss is not installed")

    output = tmp_path / "l4s.json"
    subprocess.run(
        [p4c, "p4src/l4s.p4", "-o", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(output.read_text())


def test_p4_program_compiles(tmp_path):
    data = compile_p4(tmp_path)

    assert data["program"] == "p4src/l4s.p4"
    assert data["parsers"]
    assert data["pipelines"]


def test_p4_json_exposes_forwarding_tables(tmp_path):
    data = compile_p4(tmp_path)

    tables = {
        table["name"]
        for pipeline in data["pipelines"]
        for table in pipeline.get("tables", [])
    }

    assert EXPECTED_TABLES <= tables


def test_p4_json_exposes_expected_actions(tmp_path):
    data = compile_p4(tmp_path)

    actions = {action["name"] for action in data["actions"]}

    assert EXPECTED_ACTIONS <= actions


def test_p4_json_exposes_threshold_and_telemetry_registers(tmp_path):
    data = compile_p4(tmp_path)

    registers = {register["name"] for register in data["register_arrays"]}

    assert EXPECTED_REGISTERS <= registers
