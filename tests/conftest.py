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


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-mark replay tests that aren't already marked."""
    for item in items:
        # Auto-mark replay tests
        if (
            "usb_replay" in item.module.__name__
            and not item.get_closest_marker("replay_consistency")
            and not item.get_closest_marker("property_test")
            and not item.get_closest_marker("hardware")
            and not item.get_closest_marker("hardware_correctness")
        ):
            item.add_marker(pytest.mark.replay_consistency)
