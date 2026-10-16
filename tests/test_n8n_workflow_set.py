"""Every workflow file in git is either importable or excluded for a stated reason (#1685).

`make import-n8n` exits 0 having imported what it *knows about*, so a workflow added to
`infra/n8n/workflows/` without a catalog entry was an absence, not a failure: after a wiped
`n8n-data` PVC it came back by hand or not at all. The expected set is read from the
directory, never from a second hand-written list (lesson-416).
"""

from __future__ import annotations

from pathlib import Path

from toolkit.features.n8n_import import N8N_IMPORT_CATALOG, N8N_IMPORT_EXCLUDED

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = Path("infra/n8n/workflows")


def _on_disk() -> set[Path]:
    # Anchored on this file, not the working directory: a wrong cwd would otherwise list
    # nothing and leave every assertion below green over no sample at all.
    return {p.relative_to(ROOT) for p in (ROOT / WORKFLOWS).glob("*.json")}


def test_the_directory_listing_is_a_real_sample() -> None:
    assert len(_on_disk()) >= len(N8N_IMPORT_CATALOG) > 0


def test_every_workflow_file_is_imported_or_excluded() -> None:
    covered = {s.workflow_path for s in N8N_IMPORT_CATALOG} | set(N8N_IMPORT_EXCLUDED)
    assert _on_disk() - covered == set(), (
        "workflow files that `make import-n8n` would not reconstruct and nobody excluded: "
        f"{sorted(str(p) for p in _on_disk() - covered)}. Add an N8nImportSpec, or an "
        "N8N_IMPORT_EXCLUDED entry with the reason."
    )


def test_the_importer_names_no_file_that_is_not_there() -> None:
    covered = {s.workflow_path for s in N8N_IMPORT_CATALOG} | set(N8N_IMPORT_EXCLUDED)
    assert covered - _on_disk() == set(), (
        f"catalog or exclusion names a missing workflow: {sorted(str(p) for p in covered - _on_disk())}"
    )


def test_a_workflow_is_never_both_imported_and_excluded() -> None:
    imported = {s.workflow_path for s in N8N_IMPORT_CATALOG}
    assert imported & set(N8N_IMPORT_EXCLUDED) == set()


def test_an_exclusion_is_a_decision_with_a_reason() -> None:
    bare = [str(p) for p, why in N8N_IMPORT_EXCLUDED.items() if len(why.strip()) < 40]
    assert bare == [], f"an excluded workflow needs its reason spelled out: {bare}"


def test_the_readme_states_every_exclusion() -> None:
    # Per exclusion: the README section headed by the file's name must say "not imported".
    readme = (ROOT / WORKFLOWS / "README.md").read_text(encoding="utf-8")
    sections = {chunk.split("\n", 1)[0]: chunk for chunk in readme.split("\n## ")[1:]}
    missing = [
        p.name
        for p in N8N_IMPORT_EXCLUDED
        if not any(p.name in head and "not imported" in body for head, body in sections.items())
    ]
    assert missing == [], f"README must say, under its own heading, that {missing} is deliberately not imported"
