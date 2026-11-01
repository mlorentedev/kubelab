"""The lab edge's runbook runs nothing by hand, and publishes no adapter's MAC (NET-005 task 35).

AC11: the runbook names three human steps (the adapters, the portal login and
payment, the PSK on client devices) and no others, so a read of it finds no shell
command outside a Make target. Prose may describe what a human does with a
screwdriver or a browser; a shell fence is an instruction to run, and every one
it holds must be `make`. `tests/test_runbook_targets_exist.py` already checks that
each target exists; this file checks that nothing else is there.

ADR-075 C7: the repository is public, and nothing that lets a stranger claim the
lab's access is committed. Linux names a USB adapter after its MAC
(`enx<12 hex digits>`), so an interface name in a runbook publishes the adapter's
address. The edge's uplink is `uplink0`, named by the role from SOPS.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RUNBOOK = REPO / "docs" / "runbooks" / "lab-edge.md"
INSTRUCTIONAL = [REPO / "docs" / "runbooks", REPO / "docs" / "troubleshooting"]

# Indented too: a fence inside a list item is still an instruction to run.
SHELL_FENCE = re.compile(r"^[ \t]*```(?:bash|sh|shell|console|zsh)\s*\n(.*?)^[ \t]*```", re.M | re.S)
MAC_NAMED = re.compile(r"\benx[0-9a-f]{12}\b")

# A DEBT LEDGER, and it may only shrink. Empty since task 35's follow-up.
KNOWN_MAC_NAMES: dict[str, str] = {}


def _shell_lines(text: str) -> list[str]:
    """The commands in the shell fences: blank lines and comments are not commands."""
    lines = [line.strip() for fence in SHELL_FENCE.findall(text) for line in fence.splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def _outside_make(text: str) -> list[str]:
    return [line for line in _shell_lines(text) if not line.startswith("make ")]


def test_the_runbook_has_commands_to_check() -> None:
    """Guard the guard: a fence pattern that matched nothing would pass any runbook,
    and an untagged fence is one the pattern never reads."""
    text = RUNBOOK.read_text(encoding="utf-8")
    assert len(_shell_lines(text)) >= 5
    openers = re.findall(r"^[ \t]*```(.*)$", text, re.M)[::2]
    assert all(tag.strip() for tag in openers), "an untagged fence: tag it `bash` if it holds commands"


def test_every_command_in_the_runbook_is_a_make_target() -> None:
    outside = _outside_make(RUNBOOK.read_text(encoding="utf-8"))
    assert not outside, f"lab-edge.md tells the reader to run commands that are not Make targets: {outside}"


def test_a_shell_line_that_is_not_make_is_caught() -> None:
    sample = (
        "```bash\n# a comment\nmake edge-status\nssh rpi4 sudo reboot\n```\n"
        "```yaml\nnot: a command\n```\n"
        "1. In a list item:\n\n   ```bash\n   sudo reboot\n   ```\n"
    )
    assert _shell_lines(sample) == ["make edge-status", "ssh rpi4 sudo reboot", "sudo reboot"]
    assert _outside_make(sample) == ["ssh rpi4 sudo reboot", "sudo reboot"]


def _documents() -> list[Path]:
    return sorted(path for root in INSTRUCTIONAL for path in root.rglob("*.md"))


@pytest.mark.parametrize("doc", _documents(), ids=lambda path: str(path.relative_to(REPO)))
def test_no_instruction_names_an_adapter_by_its_mac(doc: Path) -> None:
    rel = str(doc.relative_to(REPO))
    if rel in KNOWN_MAC_NAMES:
        pytest.skip(KNOWN_MAC_NAMES[rel])
    assert not MAC_NAMED.search(doc.read_text(encoding="utf-8")), (
        f"{rel} names adapters by their MAC: write `enx<MAC>` or the role's name (ADR-075 C7)"
    )


def test_the_ledger_names_only_scanned_documents() -> None:
    """An entry outside the scan would excuse nothing, and hide that the scan narrowed.
    The scan must see the runbook too: a moved directory would collect no case at all."""
    scanned = {str(path.relative_to(REPO)) for path in _documents()}
    assert str(RUNBOOK.relative_to(REPO)) in scanned, f"the MAC scan does not read {RUNBOOK.name}"
    assert set(KNOWN_MAC_NAMES) <= scanned, f"not scanned: {sorted(set(KNOWN_MAC_NAMES) - scanned)}"


def test_the_ledger_only_shrinks() -> None:
    clean = [rel for rel in KNOWN_MAC_NAMES if not MAC_NAMED.search((REPO / rel).read_text(encoding="utf-8"))]
    assert not clean, f"these no longer name an adapter by its MAC; remove them from KNOWN_MAC_NAMES: {clean}"
