"""Every named Docker volume on the Beelink has a backup ruling — or a test fails.

The gap this closes is narrow and specific. `backup.sources` is an allow-list, and
`tests/test_backup_sources.py` says so in its own docstring: *"an allow-list that only
validates what it declares cannot report what it forgot."* It guards the shape of what
is declared and is structurally unable to notice an omission.

`postgres` is the omission that shows why that matters. It is excluded from
`backup.sources` on the stated grounds that it has "no consumer yet, so there is
nothing to lose", and that it "joins this list the day something writes to it".
Something writes to it — Vikunja shipped on 2026-08-27 and its tables are populated.
The exclusion is now false, the file still asserts it, and no test noticed because a
comment is not a mechanism. (Tracked as #1111; this file does not fix it, because a
PVC is not a compose volume.)

So: **the decision has to be a declaration, and the declaration has to be exhaustive
over something enumerable.** The compose template is enumerable — it names every volume
it creates — so every one of them must appear in `backup.sources` or in
`backup.excluded`, and adding a volume without ruling on it fails here.

**This does NOT close BACKUP-044 AC6, and must not be read as doing so.** AC6 asks what
exists on disk on a live node and is absent from the declaration; that needs the node
and belongs in `tests/infra/` behind `require_vpn`. This asks the static half — what
the template creates that nobody has ruled on. Two different questions, and only one of
them can run with the homelab powered off.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
COMMON_YAML = REPO / "infra/config/values/common.yaml"
COMPOSE_TEMPLATE = REPO / "infra/ansible/roles/beelink_services/templates/compose.yml.j2"

NODE = "beelink"


def _declared_volumes() -> set[str]:
    """The `name:` of every volume the Beelink compose template declares.

    The rendered NAME rather than the compose key: `runner_data` is declared as
    `github_runner_data` on the daemon, and the daemon's name is what a backup would
    have to address. Parsed from the top-level `volumes:` block by hand because the
    file is a Jinja template and rendering it here would need the whole variable set
    for an answer that does not depend on any of them.
    """
    names: set[str] = set()
    in_block = False
    for raw in COMPOSE_TEMPLATE.read_text().splitlines():
        if raw.startswith("volumes:"):
            in_block = True
            continue
        if in_block:
            if raw and not raw.startswith((" ", "\t")):
                break  # a new top-level key ends the block
            stripped = raw.strip()
            if stripped.startswith("name:"):
                names.add(stripped.split(":", 1)[1].strip())
    return names


@pytest.fixture(scope="module")
def backup() -> dict:
    return yaml.safe_load(COMMON_YAML.read_text())["backup"]


def test_the_template_declares_volumes_at_all(backup: dict) -> None:
    """Guard the guard, on the value the assertion below actually consumes.

    If the parser returns an empty set, every membership check underneath is
    trivially satisfied and this file passes while ruling on nothing — an empty
    expectation is not a weak expectation, it matches everything (lesson-416). The
    floor is a small anchor rather than a copy of the full set, so legitimately
    adding a volume does not fail here.
    """
    volumes = _declared_volumes()

    assert volumes, (
        "no volumes parsed out of the compose template. Either the `volumes:` block "
        "moved or the parser broke; both make the coverage assertion vacuous."
    )
    assert "act_runner_data" in volumes, (
        f"the parser found {sorted(volumes)} but not the runner's volume, so it is "
        "reading the file differently than intended."
    )


def test_every_compose_volume_has_a_backup_ruling(backup: dict) -> None:
    """Backed up, or excluded with a reason. Silence is not a third option."""
    sources = set((backup.get("sources") or {}).get(NODE, {}))
    excluded = set((backup.get("excluded") or {}).get(NODE, {}))

    unruled = _declared_volumes() - sources - excluded

    assert not unruled, (
        f"volumes with no backup ruling on {NODE}: {sorted(unruled)}.\n"
        "Add each to `backup.sources` if its contents are canonical, or to "
        "`backup.excluded` with a reason if they are rebuildable. An undeclared "
        "volume is not 'not backed up' — it is nobody having decided, which is how "
        "state reaches a node and stays uncovered without anyone choosing that."
    )


def test_an_exclusion_states_why(backup: dict) -> None:
    """A reason, not a bare name.

    The whole failure this file exists for is a rationale nobody could re-check.
    `postgres`'s exclusion reads convincingly and is now false; the only defence is
    that the reason is written where the next reader will meet it.
    """
    for volume, entry in ((backup.get("excluded") or {}).get(NODE, {})).items():
        assert isinstance(entry, dict) and entry.get("reason", "").strip(), (
            f"`{volume}` is excluded with no reason. A bare exclusion is "
            "indistinguishable from an oversight the moment its author is gone."
        )


def test_nothing_is_both_backed_up_and_excluded(backup: dict) -> None:
    """The two lists must not disagree.

    An entry in both is a contradiction that reads as coverage from either side, and
    whichever one a consumer checks first wins silently.
    """
    both = set((backup.get("sources") or {}).get(NODE, {})) & set((backup.get("excluded") or {}).get(NODE, {}))

    assert not both, f"declared as both backed up and excluded on {NODE}: {sorted(both)}"
