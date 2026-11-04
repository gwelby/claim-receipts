PY ?= python3

.PHONY: test validate all
all: test validate

test:
	$(PY) tests/test_ledger.py

validate:
	hermes plugins validate .
