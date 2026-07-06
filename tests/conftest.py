"""Shared pytest configuration for coolscan-py tests."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "replay_consistency: tests that validate internal consistency against "
        "a simulated scanner fixture (NOT hardware correctness)",
    )
    config.addinivalue_line(
        "markers",
        "hardware_correctness: tests that validate wire-format correctness "
        "against actual hardware",
    )
    config.addinivalue_line(
        "markers",
        "property_test: fixture-agnostic invariant tests (resilient to "
        "non-determinism)",
    )
    config.addinivalue_line(
        "markers",
        "hardware: tests that require a real LS-40 ED scanner connected",
    )
