PY ?= python3

.PHONY: test validate acceptance all
all: test acceptance validate

test:
	$(PY) tests/test_ledger.py

acceptance:
	$(PY) tests/test_acceptance.py

validate:
	hermes plugins validate .
