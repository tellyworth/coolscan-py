"""Verify that every command-sending method in protocol.py has a @sends decorator.

Uses AST analysis to find all direct command-sending patterns, then cross-references
against the @sends registry.  Fails if any discovered command code is missing from
the registry, preventing silent drift as new commands are added.
"""

import ast
import re
from pathlib import Path

import pytest

_PROTOCOL = Path(__file__).resolve().parent.parent / "coolscan" / "protocol.py"


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _find_command_codes(tree: ast.AST) -> set[int]:
    """Walk the AST of protocol.py and extract all command byte values sent.

    Only scans within method bodies of the CoolscanProtocol class to avoid
    picking up table definitions and module-level constants.

    Recognised patterns (first byte of each command):

    - ``self._build_6byte_command(0xCC, ...)``
    - ``struct.pack("BBBBBBBBBB", 0xCC, ...)``
    - ``bytes.fromhex("CC...")``
    - ``bytes([0xCC, ...])`` / ``bytearray([0xCC, ...])``
    - ``self._parse_command("CC ...")``
    - ``self._pack_byte(0xCC)``

    Returns the set of unique command codes (int).
    """
    codes: set[int] = set()

    # Only scan within CoolscanProtocol class methods
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name != "CoolscanProtocol":
            continue
        # Scan only within this class
        for child in ast.walk(node):
            codes.update(_scan_node(child))

    return codes


def _scan_node(node: ast.AST) -> set[int]:
    """Extract command codes from a single AST node."""
    codes: set[int] = set()

    # --- _build_6byte_command(0xCC, ...) ---
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_build_6byte_command"
        and node.args
    ):
        code = _extract_hex_int(node.args[0])
        if code is not None:
            codes.add(code)

    # --- struct.pack("BBBBBBBBBB", 0xCC, ...) ---
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "pack"
        and len(node.args) >= 2
    ):
        fmt = _extract_string(node.args[0])
        if fmt == "BBBBBBBBBB":
            code = _extract_hex_int(node.args[1])
            if code is not None:
                codes.add(code)

    # --- bytes.fromhex("CC...") ---
    # Only match 6-byte (12 hex chars) or 10-byte (20 hex chars) CDBs
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "fromhex"
        and len(node.args)
    ):
        hexstr = _extract_string(node.args[0])
        if hexstr and len(hexstr) in (12, 20):
            try:
                codes.add(int(hexstr[:2], 16))
            except ValueError:
                pass

    # --- bytes([0xCC, ...]) / bytearray([0xCC, ...]) ---
    # Only match 6-byte or 10-byte CDBs (not data payloads)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in ("bytes", "bytearray")
        and node.args
        and isinstance(node.args[0], ast.List)
        and len(node.args[0].elts) in (6, 10)
    ):
        code = _extract_hex_int(node.args[0].elts[0])
        if code is not None:
            codes.add(code)

    # --- self._parse_command("CC ...") ---
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_parse_command"
        and node.args
    ):
        cmdstr = _extract_string(node.args[0])
        if cmdstr:
            first_byte = cmdstr.strip().split()[0] if cmdstr.strip() else ""
            if len(first_byte) >= 2:
                try:
                    codes.add(int(first_byte[:2], 16))
                except ValueError:
                    pass

    # --- self._pack_byte(0xCC) ---
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_pack_byte"
        and node.args
    ):
        code = _extract_hex_int(node.args[0])
        if code is not None:
            codes.add(code)

    return codes


def _extract_hex_int(node: ast.expr) -> int | None:
    """Extract an integer value from a Constant or UnaryMinus node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    # Handle negative constants like -1 (not relevant for command codes)
    return None


def _extract_string(node: ast.expr) -> str | None:
    """Extract a string value from a Constant node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


# ---------------------------------------------------------------------------
# Decorator discovery (regex-based, simpler than full AST for decorators)
# ---------------------------------------------------------------------------

def _find_decorated_codes(source: str) -> set[int]:
    """Extract command codes from @sends decorators via regex.

    Matches lines like:
        @sends(0x12)
        @sends(0xe0, 0xc1)
    """
    codes: set[int] = set()
    pattern = re.compile(r"@sends\((.+)\)")
    for line in source.splitlines():
        m = pattern.search(line)
        if m:
            for token in m.group(1).split(","):
                token = token.strip()
                if token.startswith("0x"):
                    try:
                        codes.add(int(token, 16))
                    except ValueError:
                        pass
    return codes


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCommandRegistryCoverage:
    """Every command byte sent by protocol.py must be covered by @sends."""

    @pytest.fixture()
    def source(self) -> str:
        return _PROTOCOL.read_text(encoding="utf-8")

    @pytest.fixture()
    def tree(self, source: str) -> ast.AST:
        return ast.parse(source)

    @pytest.fixture()
    def ast_codes(self, tree: ast.AST) -> set[int]:
        return _find_command_codes(tree)

    @pytest.fixture()
    def decorated_codes(self, source: str) -> set[int]:
        return _find_decorated_codes(source)

    def test_all_sent_commands_decorated(
        self, ast_codes: set[int], decorated_codes: set[int]
    ) -> None:
        """No command byte should be sent without a @sends decorator."""
        missing = ast_codes - decorated_codes
        assert not missing, (
            f"Command codes sent but not decorated with @sends: "
            f"{', '.join(f'0x{c:02x}' for c in sorted(missing))}"
        )

    def test_no_orphan_decorators(
        self, ast_codes: set[int], decorated_codes: set[int]
    ) -> None:
        """Every @sends code should correspond to an actual send site."""
        extra = decorated_codes - ast_codes
        assert not extra, (
            f"@sends codes with no matching send site in AST: "
            f"{', '.join(f'0x{c:02x}' for c in sorted(extra))}"
        )

    def test_registry_matches_decorators(
        self, source: str, decorated_codes: set[int]
    ) -> None:
        """The live registry (from @sends decorators) matches the source."""
        from coolscan.command_registry import registry

        registry_codes = registry.all_codes()
        assert registry_codes == decorated_codes, (
            f"Registry codes {sorted(registry_codes)} != "
            f"decorated codes {sorted(decorated_codes)}"
        )
