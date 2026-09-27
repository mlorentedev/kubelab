"""Every alert rule's `runbook_url` opens a runbook that exists (BACKUP-055 AC6).

The link is what the operator clicks from the page. Two rules (R2 backup health
and PVC/disk) pointed at `docs/runbooks/backup-restore.md`, a file that does not
exist, so the one pointer an alert carries led to a 404 at the moment it was
needed. Nothing noticed, because nothing opens the link until something fires.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
RULES_DIR = REPO / "infra/k8s/base/services/grafana-alerting"
PREFIX = "https://github.com/mlorentedev/kubelab/blob/master/"


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
