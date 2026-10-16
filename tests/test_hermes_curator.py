"""The curator's analyzer, hermes-kubelab's recurrence detector (spec AI-012 AC6).

A host unit of the agent's user reads the vault clone and the repositories' public
lessons and writes the candidate clusters to one file in the zone. The behaviour is
tested by running the script on a fixture corpus; the unit by what its text grants.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

from tests.test_hermes_config import HERMES, _render

ROLE = Path(__file__).resolve().parent.parent / "infra/ansible/roles/agent_stack"
SCRIPT = ROLE / "files/curator/curator-analyze.py"

SAME_CAUSE = (
    "- The webhook secret rotated in SOPS but the running pod kept the old environment value, "
    "because environment variables are injected once at container start and nothing re-reads them."
)
SAME_CAUSE_AGAIN = (
    "- A rotated credential in SOPS never reached the pod: environment variables are read once at container "
    "start, so the running container kept the stale value until a restart nobody triggered."
)
OTHER = (
    "- Mermaid rendering failed on the dashboard because the diagram label contained an unescaped "
    "parenthesis, which the parser treats as a node shape delimiter."
)


# Rarity weighting drops words that most units share, so a recurrence is only visible among
# enough unrelated lessons, as in a real corpus.
FILLER = [
    "- Prometheus scrape intervals shorter than the exporter's refresh produced duplicate samples "
    "in the dashboard panels.",
    "- The Terraform provider upgrade renamed an attribute, so the plan proposed replacing the load balancer listener.",
    "- Helm chart values merged lists by replacement, which silently dropped the sidecar container "
    "from the rendered manifest.",
    "- Certificate renewal failed because the resolver challenge record pointed at an expired "
    "delegation in the registrar.",
    "- The nightly backup verified checksums but never attempted a restore, so a corrupted archive passed every check.",
    "- Kernel upgrade changed the network interface naming, breaking the static address configuration after reboot.",
]


def _load():
    spec = importlib.util.spec_from_file_location("curator_analyze", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["curator_analyze"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def analyzer():
    return _load()


def _vault(root: Path, sessions: dict[str, str]) -> Path:
    (root / "00_meta").mkdir(parents=True)
    sessions = {**sessions, **{f"2026-03-0{i + 1}-filler.md": text for i, text in enumerate(FILLER)}}
    for name, bullet in sessions.items():
        path = root / "10_projects" / "demo" / "sessions" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nid: s\n---\n\n## Findings\n\n{bullet}\n\n## Next action\n\n{OTHER}\n")
    return root


def _run(analyzer, vault: Path, out: Path, *extra: str) -> int:
    return analyzer_main(analyzer, ["--vault", str(vault), "--out", str(out), *extra])


def analyzer_main(analyzer, argv: list[str]) -> int:
    old = sys.argv
    sys.argv = ["curator-analyze.py", *argv]
    try:
        return analyzer.main()
    finally:
        sys.argv = old


def test_a_root_cause_seen_on_two_dates_is_a_candidate(analyzer, tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault", {"2026-01-01-a.md": SAME_CAUSE, "2026-02-02-b.md": SAME_CAUSE_AGAIN})
    out = tmp_path / "zone/curator/candidates.json"
    assert _run(analyzer, vault, out) == 0
    report = json.loads(out.read_text())
    [candidate] = report["candidates"]
    assert candidate["dates"] == ["2026-01-01", "2026-02-02"]
    assert report["corpus_files"] == 2 + len(FILLER)


def test_a_lesson_seen_once_is_not_a_candidate(analyzer, tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault", {"2026-01-01-a.md": SAME_CAUSE})
    out = tmp_path / "candidates.json"
    assert _run(analyzer, vault, out) == 0
    assert json.loads(out.read_text())["candidates"] == []


def test_the_next_action_section_is_not_a_lesson(analyzer, tmp_path: Path) -> None:
    """Activity-log sections are the boilerplate that drowns real recurrences."""
    vault = _vault(tmp_path / "vault", {"2026-01-01-a.md": SAME_CAUSE, "2026-02-02-b.md": SAME_CAUSE_AGAIN})
    out = tmp_path / "candidates.json"
    _run(analyzer, vault, out)
    excerpts = json.dumps(json.loads(out.read_text()))
    assert "Mermaid" not in excerpts


def test_the_file_is_replaced_whole_and_nothing_else_is_written(analyzer, tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault", {"2026-01-01-a.md": SAME_CAUSE})
    out = tmp_path / "zone/curator/candidates.json"
    out.parent.mkdir(parents=True)
    out.write_text("{}")
    assert _run(analyzer, vault, out) == 0
    assert [p.name for p in out.parent.iterdir()] == ["candidates.json"], "no temporary file is left behind"
    assert "candidates" in json.loads(out.read_text())


def test_a_directory_that_is_not_a_vault_is_refused(analyzer, tmp_path: Path, capsys) -> None:
    assert _run(analyzer, tmp_path, tmp_path / "c.json") == 2
    assert "not a vault root" in capsys.readouterr().err


def _tarball(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_lessons_are_taken_from_category_folders_and_the_single_file_layout(
    analyzer, tmp_path: Path, monkeypatch
) -> None:
    """kubelab groups its lessons into category folders: a top-level listing sees none of them."""
    archive = _tarball(
        {
            "demo-abc/docs/lessons/_index.md": b"index",
            "demo-abc/docs/lessons/containers/lesson-001-a.md": b"# one",
            "demo-abc/docs/lessons/containers/_index.md": b"index",
            "demo-abc/docs/lessons/notes.txt": b"not markdown",
            "demo-abc/docs/lessons.md": b"# single",
            "demo-abc/src/lesson-002-b.md": b"# elsewhere",
        }
    )
    monkeypatch.setattr(analyzer.urllib.request, "urlopen", lambda *_a, **_k: io.BytesIO(archive))
    counts = analyzer.fetch_github_lessons(["mlorentedev/demo"], tmp_path)
    assert counts == {"mlorentedev/demo": 2}
    taken = sorted(
        str(p.relative_to(tmp_path / "mlorentedev_demo")) for p in (tmp_path / "mlorentedev_demo").rglob("*.md")
    )
    assert taken == ["containers/lesson-001-a.md", "lessons.md"], "kept under their category folder"


def test_two_categories_may_hold_the_same_file_name_and_neither_is_lost(analyzer, tmp_path: Path, monkeypatch) -> None:
    archive = _tarball({"demo-abc/docs/lessons/a/note.md": b"# a", "demo-abc/docs/lessons/b/note.md": b"# b"})
    monkeypatch.setattr(analyzer.urllib.request, "urlopen", lambda *_a, **_k: io.BytesIO(archive))
    assert analyzer.fetch_github_lessons(["mlorentedev/demo"], tmp_path) == {"mlorentedev/demo": 2}


def test_a_path_that_climbs_out_of_the_lessons_is_not_extracted(analyzer, tmp_path: Path, monkeypatch) -> None:
    archive = _tarball({"demo-abc/docs/lessons/../../../escape.md": b"# x", "demo-abc/docs/lessons/ok.md": b"# ok"})
    monkeypatch.setattr(analyzer.urllib.request, "urlopen", lambda *_a, **_k: io.BytesIO(archive))
    assert analyzer.fetch_github_lessons(["mlorentedev/demo"], tmp_path) == {"mlorentedev/demo": 1}
    assert not list(tmp_path.parent.glob("escape.md")) and not (tmp_path / "escape.md").exists()


def test_a_fetched_lesson_names_its_repository_and_category_as_its_source(analyzer, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    (cache / "mlorentedev_demo" / "containers").mkdir(parents=True)
    lesson = cache / "mlorentedev_demo" / "containers" / "lesson-001-sync.md"
    lesson.write_text(SAME_CAUSE)
    units = analyzer.load_corpus([lesson], tmp_path / "vault", (cache,))
    assert {u["source"] for u in units} == {"mlorentedev_demo/containers/lesson-001-sync.md"}


def test_the_vaults_lessons_index_is_read_as_a_lessons_file(analyzer) -> None:
    """The check once compared a basename with a path, so this branch could never match."""
    assert analyzer.is_lessons_file(Path("/v/10_projects/kubelab/lessons/_index.md"))
    assert not analyzer.is_lessons_file(Path("/v/10_projects/kubelab/sessions/2026-01-01-a.md"))


def test_a_stream_that_drops_mid_archive_leaves_no_partial_corpus(analyzer, tmp_path: Path, monkeypatch) -> None:
    """A truncated download must read as a failed fetch (exit 3), never as a smaller valid corpus."""
    archive = _tarball({f"demo-abc/docs/lessons/lesson-{n:03d}-x.md": b"# lesson " * 4000 for n in range(40)})
    monkeypatch.setattr(analyzer.urllib.request, "urlopen", lambda *_a, **_k: io.BytesIO(archive[: len(archive) // 2]))
    counts = analyzer.fetch_github_lessons(["mlorentedev/demo"], tmp_path)
    assert counts == {"mlorentedev/demo": 0}
    assert not any(tmp_path.iterdir()), "neither the target nor the staging directory may survive"


def test_a_repository_that_yields_no_lessons_fails_the_run_instead_of_reading_as_quiet(
    analyzer, tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(analyzer, "fetch_github_lessons", lambda repos, cache: {repo: 0 for repo in repos})
    vault = _vault(tmp_path / "vault", {"2026-01-01-a.md": SAME_CAUSE})
    status = _run(
        analyzer, vault, tmp_path / "c.json", "--repos", "mlorentedev/demo", "--cache-dir", str(tmp_path / "c")
    )
    assert status == 3
    assert "no lessons fetched from mlorentedev/demo" in capsys.readouterr().err
    assert not (tmp_path / "c.json").exists(), "a failed fetch must not leave a candidates file claiming a clean corpus"


# --------------------------------------------------------------------------- the unit


def _unit(kind: str) -> str:
    return _render(f"curator-analyze.{kind}.j2")


def test_the_unit_runs_as_the_agents_user_with_only_the_candidates_directory_writable() -> None:
    unit = _unit("service")
    assert f"User={HERMES['user']}" in unit
    writable = [line for line in unit.splitlines() if line.startswith("ReadWritePaths=")]
    assert len(writable) == 1 and writable[0].endswith("/curator")
    assert "ProtectSystem=strict" in unit and "NoNewPrivileges=yes" in unit


def test_the_unit_stops_with_the_egress_rule_and_pages_on_failure() -> None:
    unit = _unit("service")
    assert "Requisite=agent-stack-egress.service" in unit
    assert "OnFailure=kubelab-notify@%n.service" in unit


def test_the_unit_reads_the_agents_clone_not_the_root_only_mirror() -> None:
    """The mirror sits in the root-only stack directory: the agent's uid cannot open it."""
    exec_start = " ".join(
        line for line in _unit("service").splitlines() if "curator-analyze.py" in line or "--" in line
    )
    assert "/vault " in exec_start or "vault \\" in exec_start
    assert "vault-mirror" not in exec_start


def test_the_script_the_unit_runs_is_roots_and_outside_the_agents_home() -> None:
    tasks = yaml.safe_load((ROLE / "tasks/curator.yml").read_text())
    [install] = [t for b in tasks for t in b.get("block", []) if t.get("name") == "Install the analyzer"]
    copy = install["ansible.builtin.copy"]
    assert copy["owner"] == "root" and copy["dest"].startswith("{{ agent_stack_vault_libexec }}/")


def test_the_timer_catches_up_a_week_the_node_slept_through() -> None:
    timer = _unit("timer")
    assert "Persistent=true" in timer
    assert f"OnCalendar={HERMES['curator']['schedule']}" in timer


def test_the_provision_proves_the_analyzer_read_a_corpus() -> None:
    tasks = yaml.safe_load((ROLE / "tasks/curator.yml").read_text())
    names = [t.get("name") for b in tasks for t in b.get("block", [])]
    assert names.index("Run the analyzer once") < names.index("Read the candidates back")
    assert names.index("Verify the analyzer read a corpus") < names.index("Enable the analyzer timer")


def test_every_repository_is_an_owner_slash_name() -> None:
    """The shape only. Whether each is public is proven by the fetch itself: an unreachable
    repository yields no lessons and fails the run (exit 3), at every provision and every week."""
    for repo in HERMES["curator"]["repos"]:
        owner, _, name = repo.partition("/")
        assert owner and name and "/" not in name
