# Repository Setup

This guide describes the local setup needed to compile the P4 program and run
the test harness for this repository.

## System Tools

Install the P4/BMv2 and Mininet tools used by the project:

```bash
# Required for P4 compile checks
p4c-bm2-ss --version

# Required for BMv2 runtime experiments and future packet tests
simple_switch --version
simple_switch_CLI --help

# Required for Mininet experiments
mn --version
```

If any command is missing, install the matching package or build it from the
P4/BMv2 toolchain used by your course environment.

## Python Test Environment

Use a virtual environment instead of installing packages into the system
Python:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

The virtual environment is ignored by git.

## Verification Commands

Run these from the repository root:

```bash
# Compile the P4 program
make test-p4-compile

# Run static P4 and proposal-status tests
make test-static PYTHON=.venv/bin/python

# Run traffic-script unit tests
make test-python PYTHON=.venv/bin/python

# Run the default non-runtime test suite
make test PYTHON=.venv/bin/python
```

The BMv2/PTF runtime scaffold is opt-in:

```bash
make test-p4-runtime PYTHON=.venv/bin/python
```

Runtime packet tests may require root privileges, BMv2 runtime setup, and PTF
interface wiring. The current scaffold skips packet-level cases until those
tests are implemented.

## Generated Files

The repository ignores local build and experiment artifacts, including:

- Python bytecode and pytest caches
- virtual environments
- generated P4/BMv2 JSON outputs
- packet captures and experiment results
- editor and OS metadata
