PY ?= python3
PYFLAGS ?= -B

.PHONY: test acceptance validate all

all: test acceptance validate

# Every tests/test_*.py except the acceptance scorer, which needs its own target.
test:
	@for f in tests/test_*.py; do \
	  case "$$f" in *acceptance*) continue;; esac; \
	  $(PY) $(PYFLAGS) "$$f" || exit 1; \
	done

acceptance:
	$(PY) $(PYFLAGS) tests/test_acceptance.py

validate:
	hermes plugins validate .
