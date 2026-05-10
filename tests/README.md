# Test Suite

The tests are organized around what exists in the repository today, with clear
markers for runtime packet tests and proposal components that are not yet
implemented.

## Layout

| Path | Purpose |
|---|---|
| `tests/static/` | Compiles the P4 program and checks generated BMv2 JSON shape. |
| `tests/traffic/` | Unit-tests traffic script behavior with subprocess/sysctl operations mocked. |
| `tests/topo/` | Unit-tests topology host mapping and generated BMv2 runtime commands. |
| `tests/eval/` | Unit-tests pcap text parsing and summary helpers. |
| `tests/controller/` | Unit-tests the dynamic-threshold policy and runtime output parser. |
| `tests/p4runtime/` | BMv2/PTF runtime-test scaffold for future packet-level dataplane tests. |
| `tests/proposal/` | Smoke checks for proposal components that have been promoted into implemented modules. |

## Running Tests

Create a local virtual environment first:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Run the default suite:

```bash
make test PYTHON=.venv/bin/python
```

Run the full pytest collection directly:

```bash
.venv/bin/python -m pytest
```

## Static P4 Tests

`tests/static/test_p4_program.py` compiles `p4src/l4s.p4` with
`p4c-bm2-ss` and verifies that the generated BMv2 JSON exposes the expected
forwarding tables, actions, and register arrays.

These tests require `p4c-bm2-ss`. If the compiler is missing, the tests skip.

## Traffic Tests

`tests/traffic/` covers the Python scripts under `traffic/` without launching
real system commands. `tests/topo/` similarly checks topology command
generation without starting Mininet or BMv2. The tests verify:

- load-profile bandwidth and timing calculations
- invalid `--l4s-fraction` rejection
- L4S iptables ECN rewrite rule shape
- L4S and Classic `iperf3` command construction
- Classic ECN vs non-ECN sysctl choices
- receiver `tcpdump` command construction
- stable topology host-to-switch port mapping
- generated `ipv4_lpm`, `l2_forward`, and register initialization commands
- ECN codepoint counting from tcpdump pcap text
- dynamic threshold decisions and `simple_switch_CLI` register parsing

## Runtime Scaffold

`tests/p4runtime/test_runtime_scaffold.py` reserves the BMv2/PTF runtime-test
surface. By default, these tests are skipped. To run the scaffold:

```bash
make test-p4-runtime PYTHON=.venv/bin/python
```

Packet-level tests are intentionally still marked skipped until a PTF harness
starts BMv2, installs runtime table/register state, and wires test interfaces.

## Proposal Pending Tests

`tests/proposal/test_pending_components.py` documents expected future modules
from the project proposal. `topo.topology`, `eval.parse_pcap`, and the first
controller modules have moved out of this pending list because they are now
implemented.
