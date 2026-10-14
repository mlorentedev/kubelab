"""Every alert rule's `runbook_url` opens a runbook that exists (BACKUP-055 AC6).

The link is what the operator clicks from the page. Two rules (R2 backup health
and PVC/disk) pointed at `docs/runbooks/backup-restore.md`, a file that does not
exist, so the one pointer an alert carries led to a 404 at the moment it was
needed. Nothing noticed, because nothing opens the link until something fires.

The same holds for every link into this repo that a deployed page carries: the
homepage linked ADR-038 by a name it lost in a rename, and 404'd (#1524).
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
RULES_DIR = REPO / "infra/k8s/base/services/grafana-alerting"
PREFIX = "https://github.com/mlorentedev/kubelab/blob/master/"
REPO_LINK = re.compile(r"https://github\.com/mlorentedev/kubelab/(?:blob|tree|raw)/([^/\s\"'`)<>]+)/([^\s\"'`)<>]+)")
# A link that ends a sentence in prose ("see .../adr-040.md.") keeps its period in the
# capture; GitHub and browsers drop it, so the guard does too.
SENTENCE_END = ".,;:"
# What ships links into this repo: manifests (homepage, alert rules) and the toolkit.
LINK_SOURCES = ("infra/k8s", "toolkit")
# The template the homepage is rendered from, where #1524's broken link lived.
HOMEPAGE_TEMPLATE = "infra/k8s/base/services/homepage-templates/services.yaml.j2"


def _github_anchor(heading: str) -> str:
    """GitHub's heading slug: lowercase, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _runbook_urls() -> list:
    found = []
    for path in sorted(RULES_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        for group in data.get("groups", []):
            for rule in group.get("rules", []):
                url = rule.get("annotations", {}).get("runbook_url")
                if url:
                    found.append(pytest.param(rule["uid"], url, id=rule["uid"]))
    return found


def test_rules_carry_runbook_urls() -> None:
    """A floor, so the parametrised test below cannot pass by finding nothing."""
    assert len(_runbook_urls()) >= 5


@pytest.mark.parametrize("uid,url", _runbook_urls())
def test_runbook_url_names_a_committed_file(uid: str, url: str) -> None:
    assert url.startswith(PREFIX), f"{uid}: runbook_url is not a link into this repo's master: {url}"
    relative, _, anchor = url.removeprefix(PREFIX).partition("#")
    path = REPO / relative
    assert path.is_file(), f"{uid}: runbook_url names a missing file: {relative}"
    if anchor:
        headings = re.findall(r"^#+ (.+)$", path.read_text(), flags=re.MULTILINE)
        anchors = {_github_anchor(h) for h in headings}
        assert anchor in anchors, f"{uid}: {relative} has no heading for #{anchor}"


def _repo_links() -> list:
    found = set()
    for root in LINK_SOURCES:
        for path in sorted((REPO / root).rglob("*")):
            if path.is_file() and path.suffix in {".yaml", ".yml", ".j2", ".py", ".js"}:
                for ref, target in REPO_LINK.findall(path.read_text(encoding="utf-8", errors="ignore")):
                    found.add((str(path.relative_to(REPO)), f"{ref}:{target.rstrip(SENTENCE_END)}"))
    return [pytest.param(src, target, id=f"{src}->{target}") for src, target in sorted(found)]


def test_shipped_pages_link_into_the_repo() -> None:
    """A floor, so the parametrised test below cannot pass by finding nothing.

    The homepage template is named on its own: a count alone stays green if a change
    to the suffixes or the sources stops reading the file the regression was in.
    """
    sources = {param.values[0] for param in _repo_links()}
    assert len(_repo_links()) >= 10
    assert HOMEPAGE_TEMPLATE in sources


@pytest.mark.parametrize("source,target", _repo_links())
def test_every_repo_link_resolves(source: str, target: str) -> None:
    ref, _, target = target.partition(":")
    assert ref == "master", f"{source}: links ref {ref!r}; master is this repo's only permanent branch"
    relative, _, anchor = target.partition("#")
    path = REPO / relative.rstrip("/")
    assert path.exists(), f"{source}: links a path this tree does not have: {relative}"
    if anchor:
        headings = re.findall(r"^#+ (.+)$", path.read_text(), flags=re.MULTILINE)
        assert anchor in {_github_anchor(h) for h in headings}, f"{source}: {relative} has no heading for #{anchor}"
