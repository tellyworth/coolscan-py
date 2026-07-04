.PHONY: lint lint-fix test test-fast format type-check check-all validate-fixtures smoke-test-hardware generate-golden-fixture generate-batch-fixture replay-check

# Linting and code quality
lint:
	@echo "Running flake8..."
	flake8 coolscan tests --count --select=E9,F63,F7,F82 --show-source --statistics
	@echo "Running mypy..."
	mypy coolscan --ignore-missing-imports || true

lint-fix:
	@echo "Running black formatter..."
	black coolscan tests

# Testing
test:
	pytest tests -v

test-fast:
	pytest tests -v --tb=short -x

# Property tests only (fixture-agnostic invariant tests)
test-properties:
	pytest tests/test_protocol_properties.py -v -m property_test

# Hardware smoke tests (skip gracefully if no scanner)
smoke-test-hardware:
	pytest tests/test_hardware_smoke.py -v -m hardware --tb=short

# Type checking
type-check:
	mypy coolscan --ignore-missing-imports

# Format code
format:
	black coolscan tests

# Validate capture fixture consistency
validate-fixtures:
	@echo "Validating capture fixtures..."
	python3 scripts/validate_fixtures.py

# Generate golden fixture from pcapng capture
generate-golden-fixture:
	@echo "Generating golden fixture from pcapng..."
	python3 scripts/generate_fixture_from_pcapng.py

generate-batch-fixture:
	@echo "Generating batch fixture from pcapng..."
	python3 scripts/generate_fixture_from_pcapng.py --pcap ls40-batch.pcapng --output reference/golden_batch.txt

# Run all checks (lint + test; fixtures are optional diagnostics)
check-all: lint test
	@echo "All checks passed!"

# Replay regression check against golden fixture (optional diagnostic)
replay-check:
	PYTHONPATH=. python3 scripts/replay_regression_check.py

# Quick syntax check (catches indentation errors)
syntax-check:
	@echo "Checking Python syntax..."
	@python3 -m py_compile coolscan/protocol.py coolscan/scanner.py coolscan/device.py coolscan/cli.py 2>&1 || (echo "Syntax errors found!" && exit 1)
	@echo "Syntax check passed!"
