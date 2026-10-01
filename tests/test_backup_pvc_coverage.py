"""Every prod PersistentVolumeClaim has a backup ruling, and no ruling is a deferral.

`tests/test_backup_volume_coverage.py` closed this gap for the Beelink's Docker
volumes and said, in its docstring, that it did not close it for PVCs. Postgres is
the claim that proved the gap mattered: excluded on 2026-08-22 because it was
empty, "joins this list the day something writes to it", written to by Vikunja from
2026-08-27, and still unbacked on 2026-10-01 (BACKUP-046, #1111).

Two rules, so that shape cannot recur:

- **Every claim the prod overlay renders is ruled on**, in `backup.sources.vps` or
  in `backup.excluded.vps`. Silence fails here.
- **An exclusion is a ratified tier 3, never "not yet"**. Tier 3 is the epic's
  "none, rebuilt from git" (#1923, decision 1). Anything else holds state that
  something would miss, so it is backed up. A deferral has no field to live in.

The live half (claims that exist on the cluster but not in the manifests, such as
`kube-system/traefik`, which Ansible creates) is `make backup-coverage`, because
it needs the cluster.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
COMMON_YAML = REPO / "infra/config/values/common.yaml"
PROD_OVERLAY = REPO / "infra/k8s/overlays/prod"
NODE = "vps"


@pytest.fixture(scope="module")
def backup() -> dict:
    return yaml.safe_load(COMMON_YAML.read_text())["backup"]


@pytest.fixture(scope="module")
def rendered_claims() -> set[tuple[str, str]]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not on PATH: cannot render the overlay (a skip is CANNOT CHECK, not OK)")
    out = subprocess.run(["kubectl", "kustomize", str(PROD_OVERLAY)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return {
        (doc["metadata"].get("namespace", ""), doc["metadata"]["name"])
        for doc in yaml.safe_load_all(out.stdout)
        if doc and doc.get("kind") == "PersistentVolumeClaim"
    }


def _ruled(entries: dict) -> set[tuple[str, str]]:
    return {(e["pvc"]["namespace"], e["pvc"]["claim"]) for e in entries.values() if "pvc" in e}


def test_the_overlay_renders_claims_at_all(rendered_claims: set[tuple[str, str]]) -> None:
    """An empty render would make the coverage check below pass on nothing (lesson-416)."""
    assert ("kubelab", "n8n-data") in rendered_claims, sorted(rendered_claims)


def test_every_prod_claim_has_a_backup_ruling(backup: dict, rendered_claims: set[tuple[str, str]]) -> None:
    sources = _ruled((backup.get("sources") or {}).get(NODE, {}))
    excluded = _ruled((backup.get("excluded") or {}).get(NODE, {}))

    unruled = rendered_claims - sources - excluded

    assert not unruled, (
        f"prod claims with no backup ruling: {sorted(unruled)}.\n"
        "Declare each in `backup.sources.vps` (`pvc:` plus a capture method) if it holds "
        "anything a rebuild cannot reproduce, or in `backup.excluded.vps` with a reason "
        "and `tier: 3` if it does not."
    )


def test_no_claim_is_both_backed_up_and_excluded(backup: dict) -> None:
    both = _ruled((backup.get("sources") or {}).get(NODE, {})) & _ruled((backup.get("excluded") or {}).get(NODE, {}))
    assert not both, f"ruled both ways: {sorted(both)}"


def test_every_exclusion_is_tier_3_with_a_reason(backup: dict) -> None:
    """Covers every node's exclusions, the Beelink's Docker volumes included.

    `tier` is the one field a deferral cannot honestly fill: "empty for now" is
    not tier 3, and tier 1 or 2 means the data is backed up, not excluded.
    """
    bad = []
    for node, entries in (backup.get("excluded") or {}).items():
        for name, entry in entries.items():
            if not isinstance(entry, dict) or not str(entry.get("reason", "")).strip():
                bad.append(f"{node}.{name}: no reason")
            elif entry.get("tier") != 3:
                bad.append(f"{node}.{name}: tier {entry.get('tier')!r}, only tier 3 may be excluded")
            elif "pvc" in entry and set(entry["pvc"]) != {"namespace", "claim"}:
                bad.append(f"{node}.{name}: pvc needs exactly namespace+claim")
    assert not bad, "\n".join(bad)
