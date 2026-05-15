.PHONY: test test-static test-python test-p4-compile test-p4-runtime

P4C ?= p4c-bm2-ss
PYTHON ?= python3
P4_BUILD_JSON ?= /tmp/l4s-test.json

test: test-static test-python

test-static: test-p4-compile
	$(PYTHON) -m pytest tests/static tests/proposal

test-python:
	$(PYTHON) -m py_compile scripts/*.py
	$(PYTHON) -m py_compile controller/*.py
	$(PYTHON) -m py_compile traffic/*.py
	$(PYTHON) -m py_compile topo/*.py
	$(PYTHON) -m py_compile eval/*.py
	$(PYTHON) -m pytest tests/traffic tests/topo tests/eval tests/controller tests/scripts

test-p4-compile:
	$(P4C) p4src/l4s.p4 -o $(P4_BUILD_JSON)

test-p4-runtime:
	RUN_BMV2_RUNTIME_TESTS=1 $(PYTHON) -m pytest tests/p4runtime
