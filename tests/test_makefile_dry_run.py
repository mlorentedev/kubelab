"""Every Makefile target that changes a node must accept `CHECK=1`.

`make` has no notion of an unknown variable. A target that does not thread
`--check` through does not reject `CHECK=1` — it runs, for real, and reports
success. So the flag's *absence* from one target while a sibling honours it is
not an inconsistency to tidy up later; it is a live trap whose only signal is
the change you did not intend.

Measured 2026-08-21: `make backup ENV=prod CHECK=1` was run believing it a dry
run. `make provision` accepts CHECK, `make backup` did not, and the flag went
nowhere. It deployed to all four prod nodes.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
MAKEFILE = REPO / "Makefile"

# Playbooks that make no change and for which a dry run is meaningless.
# `maintenance-notify-test` is deliberately here: its entire purpose is to
# deliver a real notification, and a delivery test that suppresses delivery
# proves nothing. `wait-node-ready` only observes.
READ_ONLY = {"maintenance-notify-test", "wait-node-ready"}

_RUN = re.compile(r"\$\(TOOLKIT\) infra ansible run -p (?P<playbook>\S+)(?P<rest>[^\n;\\]*)")


def _invocations() -> list[tuple[str, str]]:
    return [
        (m.group("playbook"), m.group("rest"))
        for m in _RUN.finditer(MAKEFILE.read_text(encoding="utf-8"))
    ]


def test_the_scan_finds_the_invocations_it_is_meant_to_guard() -> None:
    """Without this the whole module passes by finding nothing.

    The regex is the fragile part: a reformatted recipe line would quietly
    reduce this suite to zero assertions while still reporting green — the
    failure class lesson-357 catalogues, in the guard rather than the code.
    """
    playbooks = {p for p, _ in _invocations()}
    assert len(playbooks) >= 5, f"only found {sorted(playbooks)}; the recipe scan has drifted"
    assert READ_ONLY <= playbooks, (
        f"the read-only allow-list names playbooks the scan cannot see: "
        f"{sorted(READ_ONLY - playbooks)}. An entry that matches nothing exempts nothing "
        f"and hides a target that should be guarded."
    )


def test_every_mutating_ansible_target_threads_the_dry_run_flag() -> None:
    missing = sorted(
        {
            playbook
            for playbook, rest in _invocations()
            if playbook.replace("$(NODE)", "").replace("$(TARGET)", "").strip("-")
            not in READ_ONLY
            and "$(_CHECK)" not in rest
        }
    )
    assert not missing, (
        f"these targets run Ansible against real nodes and drop CHECK=1 on the floor: "
        f"{missing}. `make` does not reject an unknown variable, so passing CHECK=1 to "
        f"one of them is a real deploy that reports success — which is how all four prod "
        f"nodes were changed by a command believed to be a dry run."
    )
