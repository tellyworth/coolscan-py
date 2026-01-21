.PHONY: lint lint-fix test test-fast format type-check check-all

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

# Type checking
type-check:
	mypy coolscan --ignore-missing-imports

# Format code
format:
	black coolscan tests

# Run all checks (lint + test)
check-all: lint test
	@echo "✅ All checks passed!"

# Quick syntax check (catches indentation errors)
syntax-check:
	@echo "Checking Python syntax..."
	@python3 -m py_compile coolscan/protocol.py coolscan/scanner.py coolscan/device.py coolscan/cli.py 2>&1 || (echo "❌ Syntax errors found!" && exit 1)
	@echo "✅ Syntax check passed!"
