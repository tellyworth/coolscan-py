"""Command registry for Nikon Coolscan protocol.

Provides a ``@sends`` decorator that annotates protocol methods with the
command codes they transmit.  At import time the registry auto-discovers
all decorated methods and builds a reverse lookup (command code → methods).

Used by ``scripts/analyze_capture.py --annotate`` to cross-reference captured
commands against implemented handlers, and by ``tests/test_command_registry.py``
to verify no command code is unannotated.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, ClassVar, Dict, List, Set, TypeVar

F = TypeVar("F", bound=Callable)

# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def sends(*codes: int) -> Callable[[F], F]:
    """Mark a method as sending the given USB command codes.

    The decorator records the mapping (method_name → codes) in the module-level
    :data:`registry`.

    Usage::

        @sends(0x12)
        def inquiry(self, page: int = -1) -> bytes:
            ...

        @sends(0xe0, 0xc1)
        def eject_medium(self) -> bool:
            ...
    """

    def decorator(fn: F) -> F:
        key = f"{fn.__qualname__}"
        registry._register(key, codes)
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class CommandRegistry:
    """Auto-discovered mapping of command codes to protocol methods."""

    # command code (int) → list of fully-qualified method names
    _handlers: ClassVar[Dict[int, List[str]]] = defaultdict(list)
    # method name → list of command codes (raw registration order)
    _methods: ClassVar[Dict[str, List[int]]] = defaultdict(list)

    def _register(self, name: str, codes: tuple[int, ...]) -> None:
        self._methods[name] = list(codes)
        for code in codes:
            self._handlers[code].append(name)

    def handlers(self, code: int) -> List[str]:
        """Return the list of method names that handle *code*."""
        return list(self._handlers.get(code, []))

    def all_codes(self) -> Set[int]:
        """Return the set of all registered command codes."""
        return set(self._handlers.keys())

    def method_codes(self, name: str) -> List[int]:
        """Return the command codes registered for *name*."""
        return list(self._methods.get(name, []))

    def summary(self) -> Dict[int, List[str]]:
        """Return a sorted dict of code → methods (for display/tests)."""
        return {code: sorted(methods) for code, methods in sorted(self._handlers.items())}


registry = CommandRegistry()


def _auto_discover() -> None:
    """Trigger import of ``coolscan.protocol`` so decorators execute.

    Called once at module import time.  The ``@sends`` decorator registers
    methods at decoration time, so importing ``CoolscanProtocol`` is enough
    to populate the registry.  Falls through silently if pyusb is missing.
    """
    try:
        from coolscan.protocol import CoolscanProtocol  # noqa: F401
    except ImportError:
        pass  # protocol.py may not be importable (missing pyusb)


_auto_discover()
